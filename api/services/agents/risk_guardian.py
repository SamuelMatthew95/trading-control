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
import time
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
    AgentAction,
    EventType,
    FieldName,
    PositionSide,
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
        # Position cache: avoid a full DB scan on every check interval.
        # Invalidated (a) after publishing an auto-close, so the next scan
        # picks up the updated state, and (b) after _CACHE_MAX_AGE_SECONDS so
        # externally-opened positions (e.g. manual trades) are never invisible
        # for longer than ~3 check cycles.
        self._position_cache: list[Any] = []
        self._cache_valid: bool = False
        self._cache_loaded_at: float = 0.0

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

    # Cache is refreshed after this many seconds even without a close event,
    # so positions opened externally are never invisible for more than ~3 cycles.
    _CACHE_MAX_AGE_SECONDS: float = RISK_CHECK_INTERVAL_SECONDS * 3

    async def _check_positions(self) -> None:
        """Read all open positions; auto-close on stop-loss or take-profit breach.

        Cache strategy:
        - Reload from DB if cache is stale (event-invalidated or TTL exceeded).
        - Batch-fetch all distinct symbol prices before iterating to avoid
          redundant Redis calls when multiple strategies hold the same symbol.
        - Track already-closed symbols within the cycle to prevent duplicate
          close signals in case a fill hasn't been written back to Postgres yet.
        """
        age = time.monotonic() - self._cache_loaded_at
        if not self._cache_valid or age > self._CACHE_MAX_AGE_SECONDS:
            try:
                async with AsyncSessionFactory() as session:
                    result = await session.execute(
                        text("""
                            SELECT id, symbol, side, qty, avg_cost, strategy_id
                            FROM positions
                            WHERE side != 'flat' AND qty > 0
                        """)
                    )
                    self._position_cache = list(result.mappings().all())
                    self._cache_valid = True
                    self._cache_loaded_at = time.monotonic()
            except Exception:
                return  # DB not yet available — skip silently

        # Batch-fetch prices for all distinct symbols in one pass.
        symbols = {
            str(p[FieldName.SYMBOL])
            for p in self._position_cache
            if float(p[FieldName.AVG_COST] or 0) > 0
        }
        price_results = await asyncio.gather(*[self._get_price(s) for s in symbols])
        price_map: dict[str, float | None] = dict(zip(symbols, price_results, strict=False))

        # Track symbols already issued a close this cycle to avoid duplicates.
        already_closed: set[str] = set()

        for pos in self._position_cache:
            symbol = str(pos[FieldName.SYMBOL])
            if symbol in already_closed:
                continue

            try:
                side = PositionSide(str(pos[FieldName.SIDE]).lower())
            except ValueError:
                continue
            avg_cost = float(pos[FieldName.AVG_COST] or 0)
            qty = float(pos[FieldName.QTY] or 0)
            strategy_id = str(pos[FieldName.STRATEGY_ID])

            if avg_cost <= 0 or qty <= 0:
                continue

            current_price = price_map.get(symbol)
            if current_price is None or current_price <= 0:
                continue

            # Unrealized PnL % from entry
            if side == PositionSide.LONG:
                pnl_pct = (current_price - avg_cost) / avg_cost
                close_action = AgentAction.SELL
            else:  # short
                pnl_pct = (avg_cost - current_price) / avg_cost
                close_action = AgentAction.BUY

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
            already_closed.add(symbol)
            self._cache_valid = False  # Position state changed — reload on next cycle

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
                        FieldName.TYPE: EventType.DAILY_LOSS_LIMIT_BREACHED,
                        "daily_pnl": daily_pnl,
                        "threshold": loss_threshold,
                        "kill_switch_activated": True,
                        FieldName.SOURCE: self._SOURCE,
                        FieldName.TIMESTAMP: now,
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
                price = data.get(FieldName.PRICE) or data.get(FieldName.LAST_PRICE)
                if price:
                    return float(price)
        except Exception:
            pass
        return None

    async def _publish_close(
        self,
        symbol: str,
        action: AgentAction,
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
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.SOURCE: self._SOURCE,
                FieldName.STRATEGY_ID: strategy_id,
                FieldName.SYMBOL: symbol,
                FieldName.ACTION: action,
                # Max scores — risk closes must always execute
                FieldName.SIGNAL_CONFIDENCE: 1.0,
                FieldName.REASONING_SCORE: 1.0,
                FieldName.QTY: qty,
                FieldName.PRICE: price,
                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                FieldName.TRACE_ID: trace_id,
                FieldName.PRIMARY_EDGE: f"risk_guardian:{reason}",
                FieldName.RISK_FACTORS: [reason],
                FieldName.SIZE_PCT: 1.0,  # Close entire position
                FieldName.STOP_ATR_X: 0.0,
                FieldName.RR_RATIO: 0.0,
            },
        )
