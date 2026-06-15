"""RiskGuardian: periodic position monitor that enforces stop-loss, take-profit,
trailing-stop, stale-position, and daily loss limits by publishing auto-close
decisions to STREAM_DECISIONS.

Architecture:
  - Runs as a background asyncio task (NOT a Redis stream consumer).
  - Every RISK_CHECK_INTERVAL_SECONDS it scans open positions — from Postgres
    when the DB is available, otherwise from the PaperBroker's Redis keys
    (paper:positions:{symbol}), which are the position source of truth in
    memory mode — fetches current prices from Redis, and computes unrealized
    PnL %.
  - Exit checks per position, in order: hard STOP_LOSS_PCT, hard
    TAKE_PROFIT_PCT, trailing-stop ratchet (peak-PnL high-water mark armed at
    TRAILING_STOP_ARM_PCT, closed when giveback from peak exceeds
    TRAILING_STOP_GIVEBACK_FRAC), stale-position reaper (older than
    STALE_POSITION_MAX_AGE_SECONDS with PnL inside the dead band).
  - A breach publishes a sell/buy decision with signal_confidence=1.0 +
    reasoning_score=1.0 so the ExecutionEngine's weighted gate always clears
    (1.0*0.5 + 1.0*0.3 + 0.5*0.2 = 0.9).
  - Separately checks today's realized PnL (Postgres trade_performance, or the
    Redis closed-trades mirror in memory mode); if it falls below
    -(portfolio_value * DAILY_LOSS_LIMIT_PCT) it activates the kill switch and
    publishes a STREAM_RISK_ALERTS event.
"""

from __future__ import annotations

import asyncio
import json
import math
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
    REDIS_KEY_PAPER_POSITION,
    REDIS_KEY_PRICES,
    REDIS_KEY_RISK_PEAK_PNL,
    REDIS_RISK_PEAK_TTL_SECONDS,
    RISK_CHECK_INTERVAL_SECONDS,
    SOURCE_RISK_GUARDIAN,
    STALE_POSITION_MAX_AGE_SECONDS,
    STALE_POSITION_PNL_BAND_PCT,
    STOP_LOSS_PCT,
    STREAM_DECISIONS,
    STREAM_RISK_ALERTS,
    TAKE_PROFIT_PCT,
    TRAILING_STOP_ARM_PCT,
    TRAILING_STOP_GIVEBACK_FRAC,
    AgentAction,
    EventType,
    FieldName,
    PositionSide,
    get_min_size,
)
from api.database import AsyncSessionFactory
from api.events.bus import EventBus
from api.observability import log_structured
from api.runtime_state import is_db_available
from api.services.circuit_breaker import BreakerInputs, CircuitBreaker
from api.services.redis_store import get_redis_store


class RiskGuardian:
    """Background task that enforces position-level and portfolio-level risk limits.

    Start/stop interface mirrors the agent API so main.py can manage it uniformly.
    """

    _SOURCE = SOURCE_RISK_GUARDIAN

    def __init__(self, bus: EventBus, redis_client: Any) -> None:
        self.bus = bus
        self.redis = redis_client
        # Hard backstop: a severe-drawdown circuit breaker that fails closed
        # (kill switch + strategy rollback). Looser than the daily-loss limit.
        self._breaker = CircuitBreaker(redis_client)
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
    # Public introspection — used by AgentSupervisor to monitor uniformly
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Agent identity string — matches the source tag on published decisions."""
        return self._SOURCE

    @property
    def has_crashed(self) -> bool:
        """True if the background task finished with an unhandled exception (not cancelled).

        The _run() loop swallows per-cycle exceptions so the task rarely dies,
        but AgentSupervisor uses this to monitor RiskGuardian uniformly alongside
        the stream-consumer agents.
        """
        return (
            self._task is not None
            and self._task.done()
            and not self._task.cancelled()
            and self._task.exception() is not None
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        while self._running:
            try:
                await self._check_positions()
                await self._check_daily_loss()
                await self._check_circuit_breaker()
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
        """Read all open positions; auto-close on stop-loss, take-profit,
        trailing-stop, or stale-position breach.

        Scan strategy:
        - Load positions from Postgres when the DB is available, otherwise from
          the PaperBroker's Redis keys (see :meth:`_load_open_positions`).
        - Batch-fetch all distinct symbol prices before iterating to avoid
          redundant Redis calls when multiple strategies hold the same symbol.
        - Track already-closed symbols within the cycle to prevent duplicate
          close signals in case a fill hasn't been written back yet.
        """
        positions = await self._load_open_positions()

        # Batch-fetch prices for all distinct symbols in one pass.
        symbols = {
            str(p[FieldName.SYMBOL]) for p in positions if float(p[FieldName.AVG_COST] or 0) > 0
        }
        price_results = await asyncio.gather(*[self._get_price(s) for s in symbols])
        price_map: dict[str, float | None] = dict(zip(symbols, price_results, strict=False))

        # Track symbols already issued a close this cycle to avoid duplicates.
        already_closed: set[str] = set()

        for pos in positions:
            symbol = str(pos[FieldName.SYMBOL])
            if symbol in already_closed:
                continue

            try:
                side = PositionSide(str(pos[FieldName.SIDE]).lower())
            except ValueError:
                log_structured(
                    "warning",
                    "risk_guardian_invalid_position_side",
                    symbol=symbol,
                    side=str(pos[FieldName.SIDE]),
                )
                continue
            if side is PositionSide.FLAT:
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
            if side is PositionSide.LONG:
                pnl_pct = (current_price - avg_cost) / avg_cost
                close_action = AgentAction.SELL
            else:  # PositionSide.SHORT
                pnl_pct = (avg_cost - current_price) / avg_cost
                close_action = AgentAction.BUY

            # Dust sweep: a holding below the symbol's minimum tradeable size is
            # untradeable noise — it can't be scaled and (on a live broker) can't
            # even be sold, so it would sit frozen at a stale cost basis forever.
            # Flush it regardless of PnL; the close SELL is a full exit, which the
            # ExecutionEngine min-size rule always permits.
            min_size = get_min_size(symbol)
            if 0 < qty < min_size:
                reason = f"dust_below_min({qty}<{min_size})"
            elif pnl_pct <= -STOP_LOSS_PCT:
                reason = f"stop_loss({pnl_pct:.2%})"
            elif pnl_pct >= TAKE_PROFIT_PCT:
                reason = f"take_profit({pnl_pct:.2%})"
            else:
                reason = await self._check_trailing_stop(symbol, avg_cost, pnl_pct)
                if reason is None:
                    reason = self._check_stale_position(pos, pnl_pct)
                if reason is None:
                    continue  # Within acceptable range

            log_structured(
                "info",
                "risk_guardian_auto_close",
                symbol=symbol,
                side=side.value,
                qty=qty,
                current_price=current_price,
                avg_cost=avg_cost,
                pnl_pct=round(pnl_pct, 4),
                reason=reason,
            )
            await self._publish_close(symbol, close_action, qty, current_price, strategy_id, reason)
            await self._clear_trailing_state(symbol)
            already_closed.add(symbol)
            self._cache_valid = False  # Position state changed — reload on next cycle

    # ------------------------------------------------------------------
    # Position sources — Postgres when available, PaperBroker Redis otherwise
    # ------------------------------------------------------------------

    async def _load_open_positions(self) -> list[Any]:
        """Open positions from Postgres, or the PaperBroker's Redis keys.

        In a no-Postgres (memory mode) deployment the broker's
        ``paper:positions:{symbol}`` keys are the ONLY record of open
        positions — without this fallback no stop-loss or take-profit ever
        fires there. A DB read failure also falls through to the Redis scan:
        the broker state is the position source of truth, so real-but-mirrored
        beats no exits at all.
        """
        if is_db_available():
            rows = await self._load_db_positions()
            if rows is not None:
                return rows
        return await self._load_paper_positions()

    async def _load_db_positions(self) -> list[Any] | None:
        """Cached Postgres position rows, or None when the DB read fails.

        Cache strategy: reload from DB if cache is stale (event-invalidated or
        TTL exceeded); otherwise serve the cached rows to avoid a full table
        scan on every check interval.
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
                return None  # DB flagged available but unreadable
        return self._position_cache

    async def _load_paper_positions(self) -> list[dict[str, Any]]:
        """Open positions scanned from the PaperBroker's Redis keys.

        Normalized to the same shape as the Postgres rows (entry_price →
        avg_cost; qty unsigned; side from the payload). The broker payload has
        no strategy_id — the close decision's parser generates one downstream.
        Always re-read fresh: exits must act on current state, and the keyspace
        is tiny (one key per traded symbol).
        """
        positions: list[dict[str, Any]] = []
        pattern = REDIS_KEY_PAPER_POSITION.format(symbol="*")
        try:
            async for key in self.redis.scan_iter(match=pattern):
                raw = await self.redis.get(key)
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                qty = float(payload.get(FieldName.QTY) or 0.0)
                side = str(payload.get(FieldName.SIDE) or "").lower()
                if abs(qty) < 1e-9 or side == PositionSide.FLAT:
                    continue
                positions.append(
                    {
                        FieldName.SYMBOL: str(payload.get(FieldName.SYMBOL) or ""),
                        FieldName.SIDE: side,
                        FieldName.QTY: abs(qty),
                        FieldName.AVG_COST: float(payload.get(FieldName.ENTRY_PRICE) or 0.0),
                        FieldName.STRATEGY_ID: "",
                        FieldName.OPENED_AT: payload.get(FieldName.OPENED_AT),
                    }
                )
        except Exception:
            log_structured("warning", "risk_guardian_paper_scan_failed", exc_info=True)
        return positions

    # ------------------------------------------------------------------
    # Trailing-stop ratchet + stale-position reaper
    # ------------------------------------------------------------------

    async def _check_trailing_stop(
        self, symbol: str, avg_cost: float, pnl_pct: float
    ) -> str | None:
        """Profit ratchet: track the position's peak unrealized PnL in Redis;
        once armed (peak >= TRAILING_STOP_ARM_PCT) return a close reason when
        the giveback from peak exceeds TRAILING_STOP_GIVEBACK_FRAC of the peak.

        The stored avg_cost identifies the position: a basis change (fresh
        entry or an add) resets the ratchet rather than trailing against a
        stale peak. State errors fail open to the hard SL/TP bounds — a Redis
        hiccup must never crash the scan or force an exit.
        """
        key = REDIS_KEY_RISK_PEAK_PNL.format(symbol=symbol)
        peak = pnl_pct
        try:
            raw = await self.redis.get(key)
            if raw:
                state = json.loads(raw)
                stored_cost = float(state.get(FieldName.AVG_COST) or 0.0)
                if math.isclose(stored_cost, avg_cost, rel_tol=1e-9):
                    peak = max(peak, float(state.get(FieldName.PEAK_PNL_PCT) or pnl_pct))
            await self.redis.set(
                key,
                json.dumps({FieldName.PEAK_PNL_PCT: peak, FieldName.AVG_COST: avg_cost}),
                ex=REDIS_RISK_PEAK_TTL_SECONDS,
            )
        except Exception:
            log_structured(
                "warning", "risk_guardian_trailing_state_failed", symbol=symbol, exc_info=True
            )
            return None
        if peak < TRAILING_STOP_ARM_PCT:
            return None
        floor = peak * (1.0 - TRAILING_STOP_GIVEBACK_FRAC)
        if pnl_pct <= floor:
            return f"trailing_stop(peak={peak:.2%},now={pnl_pct:.2%})"
        return None

    @staticmethod
    def _check_stale_position(pos: Any, pnl_pct: float) -> str | None:
        """Reap positions going nowhere: older than STALE_POSITION_MAX_AGE_SECONDS
        with PnL still inside the dead band. Momentum that hasn't resolved in
        hours has decayed — free the capital instead of letting chop bleed the
        position into the hard stop. Only positions whose payload carries
        opened_at (the PaperBroker path) are eligible; DB rows are skipped.
        """
        if abs(pnl_pct) >= STALE_POSITION_PNL_BAND_PCT:
            return None
        opened_raw = pos.get(FieldName.OPENED_AT) if hasattr(pos, "get") else None
        opened = RiskGuardian._parse_utc_datetime(opened_raw)
        if opened is None:
            return None
        age_seconds = (datetime.now(timezone.utc) - opened).total_seconds()
        if age_seconds < STALE_POSITION_MAX_AGE_SECONDS:
            return None
        return f"stale_position(age={age_seconds / 3600:.1f}h,pnl={pnl_pct:.2%})"

    async def _clear_trailing_state(self, symbol: str) -> None:
        """Drop the peak-PnL key after issuing a close so a re-entry starts fresh."""
        try:
            await self.redis.delete(REDIS_KEY_RISK_PEAK_PNL.format(symbol=symbol))
        except Exception:
            log_structured(
                "warning", "risk_guardian_trailing_clear_failed", symbol=symbol, exc_info=True
            )

    # ------------------------------------------------------------------
    # Portfolio-level daily loss check
    # ------------------------------------------------------------------

    async def _check_daily_loss(self) -> None:
        """Activate kill switch if today's realized PnL breaches DAILY_LOSS_LIMIT_PCT."""
        daily_pnl = await self._today_realized_pnl()
        if daily_pnl is None:
            return  # no readable PnL source — nothing to enforce against

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
                        FieldName.DAILY_PNL: daily_pnl,
                        FieldName.THRESHOLD: loss_threshold,
                        FieldName.KILL_SWITCH_ACTIVATED: True,
                        FieldName.SOURCE: self._SOURCE,
                        FieldName.TIMESTAMP: now,
                    },
                )
            except Exception:
                log_structured("error", "risk_guardian_kill_switch_failed", exc_info=True)

    async def _today_realized_pnl(self) -> float | None:
        """Sum of today's realized PnL, or None when no source is readable.

        Postgres ``trade_performance`` when the DB is available; otherwise the
        Redis closed-trades mirror (the same list the dashboard hydrates from).
        The mirror caps at the most recent 100 closes, so on an extremely
        active day the memory-mode sum is a conservative floor — it can only
        under-count, never over-trip the kill switch.
        """
        if is_db_available():
            try:
                async with AsyncSessionFactory() as session:
                    result = await session.execute(
                        text("""
                            SELECT COALESCE(SUM(pnl), 0) AS daily_pnl
                            FROM trade_performance
                            WHERE created_at >= :today
                        """),
                        # UTC calendar day — must match the memory-mode mirror
                        # filter below, or the kill switch trips on different
                        # trade sets depending on the server's local timezone.
                        {FieldName.TODAY: datetime.now(timezone.utc).date().isoformat()},
                    )
                    return float(result.scalar() or 0)
            except Exception:
                return None  # DB flagged available but unreadable

        store = get_redis_store()
        if store is None:
            return None
        try:
            trades = await store.list_closed_trades()
        except Exception:
            log_structured("warning", "risk_guardian_closed_trades_read_failed", exc_info=True)
            return None
        today_utc = datetime.now(timezone.utc).date()
        total = 0.0
        for trade in trades:
            closed_at = self._parse_utc_date(
                trade.get(FieldName.FILLED_AT) or trade.get(FieldName.TIMESTAMP)
            )
            if closed_at != today_utc:
                continue
            try:
                total += float(trade.get(FieldName.PNL) or 0.0)
            except (TypeError, ValueError):
                continue
        return total

    @staticmethod
    def _parse_utc_datetime(value: Any) -> datetime | None:
        """Timezone-aware UTC datetime of an ISO timestamp string, or None.

        Accepts a trailing ``Z`` suffix; naive timestamps are assumed UTC.
        Single parser for every timestamp the guardian reads (position
        ``opened_at``, closed-trade ``filled_at``) so the two paths can
        never drift in format handling.
        """
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _parse_utc_date(value: Any) -> date | None:
        """UTC calendar date of an ISO timestamp string, or None if unparseable."""
        parsed = RiskGuardian._parse_utc_datetime(value)
        return parsed.date() if parsed else None

    async def _portfolio_drawdown_pct(self) -> float:
        """Today's realized loss as a fraction of paper capital (0.0 if flat/up)."""
        daily_pnl = await self._today_realized_pnl()
        if daily_pnl is None or daily_pnl >= 0 or DEFAULT_PAPER_CASH <= 0:
            return 0.0
        return -daily_pnl / DEFAULT_PAPER_CASH

    async def _check_circuit_breaker(self) -> None:
        """Severe-drawdown backstop: trips the breaker (kill switch + strategy
        rollback) past CIRCUIT_BREAKER_MAX_DRAWDOWN_PCT. This is a last line of
        defense well below the daily-loss limit, and unlike the daily-loss check
        it also rolls the live strategy back to its previous version.
        """
        await self._breaker.check(BreakerInputs(drawdown_pct=await self._portfolio_drawdown_pct()))

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
