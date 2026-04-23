"""
Execution Wrapper - Mock vs Live execution handler.

This service implements the "Mock vs Live" execution flow that ensures
the system can run in paper trading mode without risking real money.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.core.models.trade_ledger import TradeLedger
from api.observability import log_structured
from api.services.trade_ledger_service import TradeLedgerService


class ExecutionMode:
    """Constants for execution modes."""

    MOCK = "MOCK"
    LIVE = "LIVE"


class ExecutionResult:
    """Result of an execution attempt."""

    def __init__(
        self,
        success: bool,
        trade_id: uuid.UUID | None = None,
        filled_price: Decimal | None = None,
        filled_quantity: Decimal | None = None,
        error_message: str | None = None,
        execution_mode: str = ExecutionMode.MOCK,
        exchange_order_id: str | None = None,
    ):
        self.success = success
        self.trade_id = trade_id
        self.filled_price = filled_price
        self.filled_quantity = filled_quantity
        self.error_message = error_message
        self.execution_mode = execution_mode
        self.exchange_order_id = exchange_order_id
        self.timestamp = datetime.now(timezone.utc)


class MockExchange:
    """Mock exchange for paper trading."""

    def __init__(self):
        self.order_counter = 1000
        self.market_data: dict[str, Decimal] = {}

    def set_market_price(self, symbol: str, price: Decimal) -> None:
        """Set the current market price for a symbol."""
        self.market_data[symbol] = price

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        order_type: str = "market",
        price: Decimal | None = None,
    ) -> ExecutionResult:
        """Simulate placing an order on the exchange."""

        await asyncio.sleep(0.01)  # Simulate network latency

        # Get market price (use provided price for limit orders, current market for market orders)
        if order_type == "market":
            filled_price = self.market_data.get(symbol, Decimal("100.00"))  # Default mock price
        else:
            filled_price = price

        # Generate mock order ID
        order_id = f"MOCK_{self.order_counter}"
        self.order_counter += 1

        # Always succeed in mock mode
        return ExecutionResult(
            success=True,
            trade_id=uuid.uuid4(),
            filled_price=filled_price,
            filled_quantity=quantity,
            execution_mode=ExecutionMode.MOCK,
            exchange_order_id=order_id,
        )


class LiveExchange:
    """Live exchange integration (placeholder for real broker API)."""

    def __init__(self, api_key: str, secret_key: str, base_url: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        order_type: str = "market",
        price: Decimal | None = None,
    ) -> ExecutionResult:
        """
        Place a real order on the exchange.

        This is a placeholder implementation. In production, this would
        integrate with the actual broker API (e.g., Alpaca, Interactive Brokers).
        """

        # TODO: Implement real exchange integration
        # For now, return an error to prevent accidental live trading
        return ExecutionResult(
            success=False,
            error_message="Live trading not yet implemented - use MOCK mode",
            execution_mode=ExecutionMode.LIVE,
        )


class ExecutionWrapper:
    """
    Execution wrapper that handles Mock vs Live execution flows.

    The flow:
    1. Signal Received: Agent says BUY/SELL
    2. Mode Check: System checks EXECUTION_MODE
    3. Mock Path: Simulate fill, write to DB as MOCK_FILL, send notification
    4. Live Path: Send order to Exchange API, wait for confirmation, write to DB
    5. UI Feedback: Notification includes "Mock" or "Live" tag
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.trade_ledger_service = TradeLedgerService(session)

        # Initialize exchanges
        self.mock_exchange = MockExchange()

        # Only initialize live exchange if configured and in production
        if (
            settings.BROKER_MODE == "live"
            and settings.ALPACA_API_KEY
            and settings.ALPACA_SECRET_KEY
        ):
            self.live_exchange = LiveExchange(
                api_key=settings.ALPACA_API_KEY,
                secret_key=settings.ALPACA_SECRET_KEY,
                base_url=settings.ALPACA_BASE_URL,
            )
        else:
            self.live_exchange = None

    def get_execution_mode(self) -> str:
        """Get the current execution mode based on settings."""
        return ExecutionMode.LIVE if settings.BROKER_MODE == "live" else ExecutionMode.MOCK

    async def execute_trade(
        self,
        agent_id: str,
        strategy_id: uuid.UUID,
        symbol: str,
        trade_type: str,  # "BUY" or "SELL"
        quantity: Decimal,
        confidence_score: float | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        requested_price: Decimal | None = None,
    ) -> tuple[ExecutionResult, TradeLedger | None]:
        """
        Execute a trade using the appropriate execution mode.

        Returns:
            Tuple[ExecutionResult, TradeLedger or None]
        """

        execution_mode = self.get_execution_mode()

        log_structured(
            "info",
            "execution_wrapper_start",
            agent_id=agent_id,
            symbol=symbol,
            trade_type=trade_type,
            quantity=float(quantity),
            execution_mode=execution_mode,
            trace_id=trace_id,
        )

        # Execute the trade
        if execution_mode == ExecutionMode.MOCK:
            execution_result = await self._execute_mock_trade(
                symbol, trade_type, quantity, requested_price
            )
        else:
            execution_result = await self._execute_live_trade(
                symbol, trade_type, quantity, requested_price
            )

        # Create trade ledger entry if execution was successful
        trade_ledger_entry = None
        if execution_result.success:
            if trade_type == "BUY":
                trade_ledger_entry = await self.trade_ledger_service.create_buy_trade(
                    agent_id=agent_id,
                    strategy_id=strategy_id,
                    symbol=symbol,
                    quantity=execution_result.filled_quantity or quantity,
                    entry_price=execution_result.filled_price or Decimal("0"),
                    confidence_score=confidence_score,
                    execution_mode=execution_result.execution_mode,
                    trace_id=trace_id,
                    metadata={
                        **(metadata or {}),
                        "exchange_order_id": execution_result.exchange_order_id,
                        "requested_price": float(requested_price) if requested_price else None,
                    },
                )
            elif trade_type == "SELL":
                trade_ledger_entry, parent_buy = await self.trade_ledger_service.create_sell_trade(
                    agent_id=agent_id,
                    strategy_id=strategy_id,
                    symbol=symbol,
                    quantity=execution_result.filled_quantity or quantity,
                    exit_price=execution_result.filled_price or Decimal("0"),
                    confidence_score=confidence_score,
                    execution_mode=execution_result.execution_mode,
                    trace_id=trace_id,
                    metadata={
                        **(metadata or {}),
                        "exchange_order_id": execution_result.exchange_order_id,
                        "requested_price": float(requested_price) if requested_price else None,
                    },
                )

        log_structured(
            "info",
            "execution_wrapper_complete",
            agent_id=agent_id,
            symbol=symbol,
            trade_type=trade_type,
            execution_mode=execution_result.execution_mode,
            success=execution_result.success,
            filled_price=float(execution_result.filled_price)
            if execution_result.filled_price
            else None,
            filled_quantity=float(execution_result.filled_quantity)
            if execution_result.filled_quantity
            else None,
            trade_ledger_id=str(trade_ledger_entry.trade_id) if trade_ledger_entry else None,
            error_message=execution_result.error_message,
            trace_id=trace_id,
        )

        return execution_result, trade_ledger_entry

    async def _execute_mock_trade(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> ExecutionResult:
        """Execute a mock trade."""

        # Set mock market price if provided
        if price:
            self.mock_exchange.set_market_price(symbol, price)

        return await self.mock_exchange.place_order(
            symbol=symbol,
            side=side.lower(),
            quantity=quantity,
            order_type="market" if price is None else "limit",
            price=price,
        )

    async def _execute_live_trade(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> ExecutionResult:
        """Execute a live trade."""

        if not self.live_exchange:
            return ExecutionResult(
                success=False,
                error_message="Live exchange not configured",
                execution_mode=ExecutionMode.LIVE,
            )

        try:
            return await self.live_exchange.place_order(
                symbol=symbol,
                side=side.lower(),
                quantity=quantity,
                order_type="market" if price is None else "limit",
                price=price,
            )
        except Exception as e:
            log_structured(
                "error",
                "execution_wrapper_live_trade_error",
                symbol=symbol,
                side=side,
                quantity=float(quantity),
                error=str(e),
                exc_info=True,
            )
            return ExecutionResult(
                success=False,
                error_message=f"Live trade failed: {str(e)}",
                execution_mode=ExecutionMode.LIVE,
            )

    async def get_execution_status(self) -> dict[str, Any]:
        """Get the current execution status and configuration."""

        return {
            "execution_mode": self.get_execution_mode(),
            "broker_mode": settings.BROKER_MODE,
            "mock_exchange_available": True,
            "live_exchange_available": self.live_exchange is not None,
            "alpaca_configured": bool(settings.ALPACA_API_KEY and settings.ALPACA_SECRET_KEY),
            "alpaca_paper_trading": settings.ALPACA_PAPER,
            "alpaca_base_url": settings.ALPACA_BASE_URL,
        }


# Factory function for dependency injection
async def get_execution_wrapper(session: AsyncSession) -> ExecutionWrapper:
    """Factory function to create ExecutionWrapper instance."""
    return ExecutionWrapper(session)
