"""RiskGuardian: periodic position monitor that enforces stop-loss, take-profit, and
daily loss limits by publishing auto-close decisions to STREAM_DECISIONS.

Architecture:
  - Runs as a background asyncio task (NOT a Redis stream consumer).
  - Every RISK_CHECK_INTERVAL_SECONDS it scans open positions in Postgres,
    fetches current prices from Redis, and computes unrealized PnL %.
  - If a position breaches STOP_LOSS_PCT or TAKE_PROFIT_PCT it publishes a
    sell/buy decision with signal_confidence=1.0 + reasoning_score=1.0 so the
    ExecutionEngine's weighted gate always clears (1.0*0.5 + 1.0*0.3 + 0.5*0.2 = 0.9).
  - Separately checks today's realized PnL; if it falls below
    -(portfolio_value * DAILY_LOSS_LIMIT_PCT) it activates the kill switch and
    publishes a STREAM_RISK_ALERTS event.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text

from api.constants import (
    DAILY_LOSS_LIMIT_PCT,
    DEFAULT_PAPER_CASH,
    REDIS_KEY_KILL_SWITCH,
    REDIS_KEY_KILL_SWITCH_UPDATED_AT,
    REDIS_KEY_PRICES,
    RISK_CHECK_INTERVAL_SECONDS,
    STOP_LOSS_PCT,
    STREAM_DECISIONS,
    STREAM_RISK_ALERTS,
    TAKE_PROFIT_PCT,
)
from api.database import AsyncSessionFactory
from api.events.bus import EventBus
from api.observability import log_structured


class RiskGuardian:
    """Background task that enforces position-level and portfolio-level risk limits.

    Start/stop interface mirrors the agent API so main.py can manage it uniformly.
    """

    _SOURCE = "risk_guardian"

    def __init__(self, bus: EventBus, redis_client: Any) -> None:
        self.bus = bus
        self.redis = redis_client
        self._running = False
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run(), name="risk-guardian")
        log_structured("info", "risk_guardian_started", interval=RISK_CHECK_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        while self._running:
            try:
                await self._check_positions()
                await self._check_daily_loss()
                log_structured("debug", "risk_guardian_scan_complete")
            except asyncio.CancelledError:
                raise
            except Exception:
                log_structured("warning", "risk_guardian_check_failed", exc_info=True)
            await asyncio.sleep(RISK_CHECK_INTERVAL_SECONDS)

    # ------------------------------------------------------------------
    # Position-level checks
    # ------------------------------------------------------------------

    async def _check_positions(self) -> None:
        """Read all open positions; auto-close on stop-loss or take-profit breach."""
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("""
                        SELECT id, symbol, side, qty, avg_cost, strategy_id
                        FROM positions
                        WHERE side != 'flat' AND qty > 0
                    """)
                )
                positions = result.mappings().all()
        except Exception:
            return  # DB not yet available — skip silently

        for pos in positions:
            symbol = str(pos["symbol"])
            side = str(pos["side"]).lower()
            avg_cost = float(pos["avg_cost"] or 0)
            qty = float(pos["qty"] or 0)
            strategy_id = str(pos["strategy_id"])

            if avg_cost <= 0 or qty <= 0:
                continue

            current_price = await self._get_price(symbol)
            if current_price is None or current_price <= 0:
                continue

            # Unrealized PnL % from entry
            if side == "long":
                pnl_pct = (current_price - avg_cost) / avg_cost
                close_action = "sell"
            else:  # short
                pnl_pct = (avg_cost - current_price) / avg_cost
                close_action = "buy"

            if pnl_pct <= -STOP_LOSS_PCT:
                reason = f"stop_loss({pnl_pct:.2%})"
            elif pnl_pct >= TAKE_PROFIT_PCT:
                reason = f"take_profit({pnl_pct:.2%})"
            else:
                continue  # Within acceptable range

            log_structured(
                "info",
                "risk_guardian_auto_close",
                symbol=symbol,
                side=side,
                qty=qty,
                current_price=current_price,
                avg_cost=avg_cost,
                pnl_pct=round(pnl_pct, 4),
                reason=reason,
            )
            await self._publish_close(symbol, close_action, qty, current_price, strategy_id, reason)

    # ------------------------------------------------------------------
    # Portfolio-level daily loss check
    # ------------------------------------------------------------------

    async def _check_daily_loss(self) -> None:
        """Activate kill switch if today's realized PnL breaches DAILY_LOSS_LIMIT_PCT."""
        try:
            async with AsyncSessionFactory() as session:
                today = date.today().isoformat()
                result = await session.execute(
                    text("""
                        SELECT COALESCE(SUM(pnl), 0) AS daily_pnl
                        FROM trade_performance
                        WHERE created_at >= :today
                    """),
                    {"today": today},
                )
                daily_pnl = float(result.scalar() or 0)
        except Exception:
            return  # DB not available

        loss_threshold = -(DEFAULT_PAPER_CASH * DAILY_LOSS_LIMIT_PCT)
        if daily_pnl < loss_threshold:
            log_structured(
                "warning",
                "risk_guardian_daily_loss_limit_breached",
                daily_pnl=daily_pnl,
                threshold=loss_threshold,
            )
            try:
                now = datetime.now(timezone.utc).isoformat()
                await self.redis.set(REDIS_KEY_KILL_SWITCH, "1")
                await self.redis.set(REDIS_KEY_KILL_SWITCH_UPDATED_AT, now)
                await self.bus.publish(
                    STREAM_RISK_ALERTS,
                    {
                        "type": "daily_loss_limit_breached",
                        "daily_pnl": daily_pnl,
                        "threshold": loss_threshold,
                        "kill_switch_activated": True,
                        "source": self._SOURCE,
                        "timestamp": now,
                    },
                )
            except Exception:
                log_structured("error", "risk_guardian_kill_switch_failed", exc_info=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_price(self, symbol: str) -> float | None:
        """Fetch current price from Redis price cache."""
        try:
            raw = await self.redis.get(REDIS_KEY_PRICES.format(symbol=symbol))
            if raw:
                data = json.loads(raw)
                price = data.get("price") or data.get("last_price")
                if price:
                    return float(price)
        except Exception:
            pass
        return None

    async def _publish_close(
        self,
        symbol: str,
        action: str,
        qty: float,
        price: float,
        strategy_id: str,
        reason: str,
    ) -> None:
        """Publish a risk-triggered close decision with maximum confidence scores.

        Using signal_confidence=1.0 and reasoning_score=1.0 ensures the weighted
        gate in ExecutionEngine always clears:
          1.0 * 0.50 + 1.0 * 0.30 + 0.5 * 0.20 = 0.90 >= 0.55
        """
        trace_id = str(uuid.uuid4())
        await self.bus.publish(
            STREAM_DECISIONS,
            {
                "msg_id": str(uuid.uuid4()),
                "source": self._SOURCE,
                "strategy_id": strategy_id,
                "symbol": symbol,
                "action": action,
                # Max scores — risk closes must always execute
                "signal_confidence": 1.0,
                "reasoning_score": 1.0,
                "qty": qty,
                "price": price,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "trace_id": trace_id,
                "primary_edge": f"risk_guardian:{reason}",
                "risk_factors": [reason],
                "size_pct": 1.0,  # Close entire position
                "stop_atr_x": 0.0,
                "rr_ratio": 0.0,
            },
        )
