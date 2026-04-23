"""
Deterministic P&L recomputation from raw trade data.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

P&L RECOMPUTATION:
- Always compute from entry_price → exit_price
- Never trust stored P&L as truth
- Mathematical guarantees for consistency
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.models.trade_ledger import TradeLedger
from api.observability import log_structured


class PnLRecomputer:
    """Deterministic P&L recomputation from raw trade data."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def recompute_trade_pnl(self, trade_id: str) -> dict[str, Any]:
        """Recompute P&L for a specific trade from raw data."""
        try:
            # Get the trade
            stmt = select(TradeLedger).where(TradeLedger.trade_id == trade_id)
            result = await self.session.execute(stmt)
            trade = result.scalar_one_or_none()

            if not trade:
                return {
                    "trade_id": trade_id,
                    "error": "Trade not found",
                    "recomputed_pnl": None,
                }

            # Recompute based on trade type
            if trade.trade_type == "SELL" and trade.parent_trade_id:
                # SELL trade - compute P&L from parent BUY
                recomputed_pnl = await self._compute_sell_pnl(trade)
            elif trade.trade_type == "BUY":
                # BUY trade - no P&L yet
                recomputed_pnl = Decimal("0")
            else:
                recomputed_pnl = Decimal("0")

            # Compare with stored P&L
            stored_pnl = trade.pnl_realized or Decimal("0")
            pnl_difference = abs(recomputed_pnl - stored_pnl)

            # Log significant differences
            if pnl_difference > Decimal("0.01"):  # 1 cent threshold
                log_structured(
                    "warning",
                    "pnl_recomputation_difference",
                    trade_id=trade_id,
                    stored_pnl=float(stored_pnl),
                    recomputed_pnl=float(recomputed_pnl),
                    difference=float(pnl_difference),
                )

            return {
                "trade_id": trade_id,
                "trade_type": trade.trade_type,
                "symbol": trade.symbol,
                "entry_price": float(trade.entry_price) if trade.entry_price else None,
                "exit_price": float(trade.exit_price) if trade.exit_price else None,
                "stored_pnl": float(stored_pnl),
                "recomputed_pnl": float(recomputed_pnl),
                "pnl_difference": float(pnl_difference),
                "calculation_method": "entry_to_exit_price",
                "source": "deterministic_recomputation",
            }

        except Exception as e:
            log_structured(
                "error",
                "pnl_recomputation_error",
                trade_id=trade_id,
                error=str(e),
                exc_info=True,
            )

            return {
                "trade_id": trade_id,
                "error": str(e),
                "recomputed_pnl": None,
            }

    async def _compute_sell_pnl(self, sell_trade: TradeLedger) -> Decimal:
        """Compute P&L for SELL trade from parent BUY."""
        if not sell_trade.parent_trade_id:
            return Decimal("0")

        # Get parent BUY trade
        parent_stmt = select(TradeLedger).where(TradeLedger.trade_id == sell_trade.parent_trade_id)
        parent_result = await self.session.execute(parent_stmt)
        parent_trade = parent_result.scalar_one_or_none()

        if not parent_trade:
            log_structured(
                "warning",
                "sell_trade_no_parent",
                sell_trade_id=str(sell_trade.trade_id),
                parent_trade_id=str(sell_trade.parent_trade_id),
            )
            return Decimal("0")

        # Compute P&L: (exit_price - entry_price) * quantity
        pnl = (sell_trade.exit_price - parent_trade.entry_price) * parent_trade.quantity

        log_structured(
            "debug",
            "pnl_calculated",
            sell_trade_id=str(sell_trade.trade_id),
            parent_trade_id=str(parent_trade.trade_id),
            entry_price=float(parent_trade.entry_price),
            exit_price=float(sell_trade.exit_price),
            quantity=float(parent_trade.quantity),
            calculated_pnl=float(pnl),
        )

        return pnl

    async def recompute_portfolio_pnl_strict(self, agent_id: str | None = None) -> dict[str, Any]:
        """Recompute entire portfolio P&L from raw trade data."""
        try:
            # Get all trade pairs for recomputation
            pairs = await self._get_trade_pairs(agent_id)

            total_pnl = Decimal("0")
            trade_details = []

            for pair in pairs:
                buy_trade, sell_trade = pair

                if buy_trade and sell_trade:
                    # Complete pair - compute P&L
                    pnl = (sell_trade.exit_price - buy_trade.entry_price) * buy_trade.quantity
                    total_pnl += pnl

                    trade_details.append(
                        {
                            "symbol": buy_trade.symbol,
                            "buy_trade_id": str(buy_trade.trade_id),
                            "sell_trade_id": str(sell_trade.trade_id),
                            "entry_price": float(buy_trade.entry_price),
                            "exit_price": float(sell_trade.exit_price),
                            "quantity": float(buy_trade.quantity),
                            "calculated_pnl": float(pnl),
                            "pair_status": "complete",
                        }
                    )
                elif buy_trade and not sell_trade:
                    # Open BUY trade
                    trade_details.append(
                        {
                            "symbol": buy_trade.symbol,
                            "buy_trade_id": str(buy_trade.trade_id),
                            "sell_trade_id": None,
                            "entry_price": float(buy_trade.entry_price),
                            "exit_price": None,
                            "quantity": float(buy_trade.quantity),
                            "calculated_pnl": 0.0,
                            "pair_status": "open",
                        }
                    )
                else:
                    # Unpaired SELL trade
                    trade_details.append(
                        {
                            "symbol": sell_trade.symbol,
                            "buy_trade_id": None,
                            "sell_trade_id": str(sell_trade.trade_id),
                            "entry_price": None,
                            "exit_price": float(sell_trade.exit_price),
                            "quantity": float(sell_trade.quantity),
                            "calculated_pnl": 0.0,
                            "pair_status": "orphaned",
                        }
                    )

            # Calculate portfolio metrics
            complete_pairs = [t for t in trade_details if t["pair_status"] == "complete"]
            open_positions = [t for t in trade_details if t["pair_status"] == "open"]

            winning_trades = len([t for t in complete_pairs if t["calculated_pnl"] > 0])
            total_completed_trades = len(complete_pairs)

            win_rate = (
                (winning_trades / total_completed_trades * 100) if total_completed_trades > 0 else 0
            )

            result = {
                "agent_id": agent_id,
                "total_pnl": float(total_pnl),
                "total_trades": len(trade_details),
                "complete_pairs": total_completed_trades,
                "open_positions": len(open_positions),
                "win_rate": win_rate,
                "trade_details": trade_details,
                "calculation_method": "deterministic_recomputation",
                "source": "raw_trade_data",
                "recomputation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

            log_structured(
                "info",
                "portfolio_pnl_recomputed",
                agent_id=agent_id,
                total_pnl=float(total_pnl),
                total_trades=len(trade_details),
                win_rate=win_rate,
            )

            return result

        except Exception as e:
            log_structured(
                "error",
                "portfolio_pnl_recomputation_error",
                agent_id=agent_id,
                error=str(e),
                exc_info=True,
            )

            return {
                "agent_id": agent_id,
                "error": str(e),
                "total_pnl": 0.0,
                "total_trades": 0,
                "win_rate": 0.0,
            }

    async def _get_trade_pairs(
        self, agent_id: str | None = None
    ) -> list[tuple[TradeLedger | None, TradeLedger | None]]:
        """Get all trade pairs (BUY + SELL) for recomputation."""
        # Get all trades ordered by creation time
        stmt = (
            select(TradeLedger)
            .where(TradeLedger.agent_id == agent_id if agent_id else True)
            .order_by(TradeLedger.created_at)
        )

        result = await self.session.execute(stmt)
        all_trades = result.scalars().all()

        # Group into pairs
        pairs = []
        unpaired_buys = {}

        for trade in all_trades:
            if trade.trade_type == "BUY":
                # Add to unpaired BUYs
                if trade.symbol not in unpaired_buys:
                    unpaired_buys[trade.symbol] = []
                unpaired_buys[trade.symbol].append(trade)
            elif trade.trade_type == "SELL":
                # Try to pair with oldest unpaired BUY
                if trade.symbol in unpaired_buys and unpaired_buys[trade.symbol]:
                    buy_trade = unpaired_buys[trade.symbol].pop(0)
                    pairs.append((buy_trade, trade))
                else:
                    # Orphaned SELL
                    pairs.append((None, trade))

        # Add remaining unpaired BUYs
        for _symbol, buys in unpaired_buys.items():
            for buy_trade in buys:
                pairs.append((buy_trade, None))

        return pairs

    async def validate_pnl_consistency(self, agent_id: str | None = None) -> dict[str, Any]:
        """Validate P&L consistency across all trades."""
        try:
            # Get all trades with their P&L
            stmt = select(
                TradeLedger.trade_id,
                TradeLedger.trade_type,
                TradeLedger.symbol,
                TradeLedger.entry_price,
                TradeLedger.exit_price,
                TradeLedger.quantity,
                TradeLedger.pnl_realized,
                TradeLedger.parent_trade_id,
            ).where(TradeLedger.agent_id == agent_id if agent_id else True)

            result = await self.session.execute(stmt)
            trades = result.scalars().all()

            inconsistencies = []
            validated_trades = []

            for trade in trades:
                # Recompute P&L for this trade
                if trade.trade_type == "SELL" and trade.parent_trade_id:
                    # Find parent trade
                    parent_trade = next(
                        (t for t in trades if t.trade_id == trade.parent_trade_id), None
                    )

                    if parent_trade:
                        # Compute expected P&L
                        expected_pnl = (
                            trade.exit_price - parent_trade.entry_price
                        ) * parent_trade.quantity
                        actual_pnl = trade.pnl_realized or Decimal("0")

                        if abs(expected_pnl - actual_pnl) > Decimal("0.01"):
                            inconsistencies.append(
                                {
                                    "trade_id": str(trade.trade_id),
                                    "symbol": trade.symbol,
                                    "issue": "pnl_mismatch",
                                    "expected_pnl": float(expected_pnl),
                                    "actual_pnl": float(actual_pnl),
                                    "difference": float(abs(expected_pnl - actual_pnl)),
                                }
                            )
                        else:
                            validated_trades.append(
                                {
                                    "trade_id": str(trade.trade_id),
                                    "symbol": trade.symbol,
                                    "pnl_validated": True,
                                    "pnl_value": float(actual_pnl),
                                }
                            )

            return {
                "agent_id": agent_id,
                "total_trades": len(trades),
                "validated_trades": len(validated_trades),
                "inconsistent_trades": len(inconsistencies),
                "consistency_rate": (len(validated_trades) / len(trades) * 100) if trades else 100,
                "inconsistencies": inconsistencies,
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            log_structured(
                "error",
                "pnl_consistency_validation_error",
                agent_id=agent_id,
                error=str(e),
                exc_info=True,
            )

            return {
                "agent_id": agent_id,
                "error": str(e),
                "total_trades": 0,
                "inconsistent_trades": 0,
                "consistency_rate": 0.0,
            }
