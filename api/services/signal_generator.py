"""SIGNAL_AGENT — bridges market_events → signals stream.

Reads price ticks from market_events, classifies signal type based on
percentage change, and writes classified signals to the signals stream.

DB routing:
  - is_db_available() is set once at startup.
  - Every code path checks it upfront and routes deterministically.
  - No "try DB, catch, fall back" — the mode is known and explicit.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from api.config import settings
from api.constants import (
    AGENT_SIGNAL,
    REGIME_ATR_AVG_PERIOD,
    REGIME_ATR_PERIOD,
    SOURCE_SIGNAL,
    STREAM_MARKET_EVENTS,
    STREAM_SIGNALS,
    AgentLogType,
    EntityType,
    EventType,
    FieldName,
    GradeType,
    LogType,
    MarketDirection,
    SignalStrength,
    SignalType,
    StatusValue,
)
from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
from api.schema_version import DB_SCHEMA_VERSION
from api.services.agent_heartbeat import write_heartbeat
from api.services.agent_state import AgentStateRegistry
from api.services.market_status import get_market_status
from api.services.risk_filters import compute_atr_from_prices, compute_rsi

AGENT_NAME = AGENT_SIGNAL

# Signal classification thresholds — absolute single-bar percentage move.
# These two numbers ARE the entire buy/sell/hold decision today, and they are
# the primary knob the backtest harness exists to measure and tune. Promoted
# out of process() so the live agent and backtest/ share one source of truth.
STRONG_MOMENTUM_PCT = 3.0
MOMENTUM_PCT = 1.5


def classify_signal(
    pct: float,
) -> tuple[SignalType, SignalStrength, float, MarketDirection, str]:
    """Classify a percentage price move into the full trading decision.

    PURE — no IO, no state. Returns ``(signal_type, strength, score, direction,
    action)``. This is the single source of truth for the buy/sell/hold call,
    shared by the live ``SignalGenerator`` and the ``backtest`` harness so the
    two can never silently diverge.

    ``pct`` is the bar-to-bar percent change, exactly as PricePoller computes it
    ((price - prev_price) / prev_price * 100).
    """
    abs_pct = abs(pct)
    direction = (
        MarketDirection.BULLISH
        if pct > 0
        else (MarketDirection.BEARISH if pct < 0 else MarketDirection.NEUTRAL)
    )
    if abs_pct >= STRONG_MOMENTUM_PCT:
        signal_type, strength, score = SignalType.STRONG_MOMENTUM, SignalStrength.HIGH, 80.0
    elif abs_pct >= MOMENTUM_PCT:
        signal_type, strength, score = SignalType.MOMENTUM, SignalStrength.NORMAL, 55.0
    else:
        signal_type, strength, score = SignalType.PRICE_UPDATE, SignalStrength.LOW, 30.0

    # LOW strength == noise. Never trade direction off a sub-1.5% move — the
    # score (0.30) is below the execution gate anyway, and emitting buy/sell
    # here pollutes downstream agent logs and lets a generous LLM re-confidence
    # the trade past the gate.
    if strength == SignalStrength.LOW or direction == MarketDirection.NEUTRAL:
        action = "hold"
    elif direction == MarketDirection.BULLISH:
        action = "buy"
    else:
        action = "sell"
    return signal_type, strength, score, direction, action


class SignalGenerator(BaseStreamConsumer):
    _heartbeat_agent_name = AGENT_SIGNAL

    def __init__(
        self, bus: EventBus, dlq: DLQManager, *, agent_state: AgentStateRegistry | None = None
    ):
        super().__init__(
            bus,
            dlq,
            stream=STREAM_MARKET_EVENTS,
            group=DEFAULT_GROUP,
            consumer="signal-agent",
            agent_state=agent_state,
        )
        self.total_events = 0
        self._agent_pool_id: str | None = None
        # Rolling price history per symbol for technical indicators (RSI, ATR, regime)
        self._price_history: dict[str, deque[float]] = {}
        self._atr_history: dict[str, deque[float]] = {}
        # Per-symbol counter of consecutive sub-threshold ("noise") ticks since
        # the last published signal — drives the publish throttle (see
        # _should_publish). Seeded lazily so the first tick of any symbol always
        # publishes.
        self._ticks_since_signal: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    async def _bootstrap_price_history(self, symbol: str) -> None:
        """Pre-warm the price history buffer with 50 historical 1-min bars.

        Called once per symbol on first tick. Runs in an executor so the
        Alpaca SDK's synchronous HTTP call does not block the event loop.
        Failures are silent — warmup is best-effort; live ticks fill the
        buffer organically if Alpaca is unavailable.
        """
        if not (settings.ALPACA_API_KEY and settings.ALPACA_SECRET_KEY):
            return
        # Equities only have fetchable recent bars during a live session; calling
        # the historical bars endpoint overnight just burns an Alpaca request and
        # (for SIP-gated data) returns a 403. Crypto is 24/7 so always allowed.
        if "/" not in symbol and not get_market_status().is_open():
            log_structured(
                "debug",
                "signal_generator_bootstrap_skipped_market_closed",
                symbol=symbol,
            )
            return
        try:
            import asyncio  # noqa: PLC0415
            from datetime import timedelta  # noqa: PLC0415
            from functools import partial  # noqa: PLC0415

            from alpaca.data.historical.crypto import CryptoHistoricalDataClient  # noqa: PLC0415
            from alpaca.data.historical.stock import StockHistoricalDataClient  # noqa: PLC0415
            from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest  # noqa: PLC0415
            from alpaca.data.timeframe import TimeFrame  # noqa: PLC0415

            end = datetime.now(timezone.utc)
            start = end - timedelta(hours=2)

            is_crypto = "/" in symbol

            def _fetch() -> list[float]:
                if is_crypto:
                    client = CryptoHistoricalDataClient(
                        settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY
                    )
                    req = CryptoBarsRequest(
                        symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start, end=end
                    )
                    bars = client.get_crypto_bars(req)
                else:
                    client = StockHistoricalDataClient(
                        settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY
                    )
                    req = StockBarsRequest(
                        symbol_or_symbols=symbol,
                        timeframe=TimeFrame.Minute,
                        start=start,
                        end=end,
                    )
                    bars = client.get_stock_bars(req)
                rows = bars[symbol] if hasattr(bars, "__getitem__") else []
                return [float(b.close) for b in rows][-50:]

            loop = asyncio.get_running_loop()
            close_prices = await asyncio.wait_for(
                loop.run_in_executor(None, partial(_fetch)), timeout=10
            )
            for p in close_prices:
                if p > 0:
                    self._price_history[symbol].append(p)
            if close_prices:
                log_structured(
                    "info",
                    "signal_generator_price_history_bootstrapped",
                    symbol=symbol,
                    bars_loaded=len(close_prices),
                )
        except Exception:
            log_structured(
                "warning",
                "signal_generator_price_history_bootstrap_failed",
                symbol=symbol,
                exc_info=True,
            )

    async def _resolve_agent_pool_id(self) -> str | None:
        """Fetch agent_pool UUID once and cache it. Returns None in memory mode."""
        if self._agent_pool_id is not None:
            return self._agent_pool_id
        if not is_db_available():
            return None
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("SELECT id FROM agent_pool WHERE name = :name"),
                    {FieldName.NAME: AGENT_NAME},
                )
                row = result.first()
                if row:
                    self._agent_pool_id = str(row[0])
        except Exception:
            log_structured("warning", f"[{AGENT_NAME}] agent_pool_lookup_failed", exc_info=True)
        return self._agent_pool_id

    def _should_publish(self, symbol: str, strength: SignalStrength) -> bool:
        """Decide whether this tick emits a downstream signal (throttle).

        Every tick used to publish a signal AND write events/grades/runs/logs
        AND wake the reasoning→LLM cascade — ~one full cascade per symbol per
        poll, around the clock. Indicator history is still updated on every tick
        (callers do that before calling this), but a signal is only published
        when it carries a tradeable move (strength != LOW) or, for the
        sub-threshold "noise floor", once every ``SIGNAL_EVERY_N_TICKS`` ticks
        as a liveness heartbeat. This drops noise-signal volume ~Nx without ever
        suppressing a momentum signal.

        The first tick of any symbol always publishes (the counter seeds at the
        threshold) so warmup and downstream wiring see data immediately.
        """
        every_n = max(1, settings.SIGNAL_EVERY_N_TICKS)
        if strength != SignalStrength.LOW:
            self._ticks_since_signal[symbol] = 0
            return True
        # Absent symbol seeds at every_n so its first tick is immediately "due".
        count = self._ticks_since_signal.get(symbol, every_n) + 1
        if count >= every_n:
            self._ticks_since_signal[symbol] = 0
            return True
        self._ticks_since_signal[symbol] = count
        return False

    # ------------------------------------------------------------------
    # Main processing loop
    # ------------------------------------------------------------------

    async def process(self, data: dict[str, Any]) -> None:
        # --- Parse incoming tick -----------------------------------------
        raw = data.get(FieldName.PAYLOAD)
        if isinstance(raw, str):
            payload = json.loads(raw)
        elif isinstance(raw, dict):
            payload = raw
        else:
            payload = data

        symbol = payload.get(FieldName.SYMBOL)
        price = float(payload.get(FieldName.PRICE, 0))
        pct = float(payload.get(FieldName.PCT, 0))
        trace_id = payload.get(FieldName.TRACE_ID) or str(uuid.uuid4())
        msg_id = data.get(FieldName.MSG_ID) or str(uuid.uuid4())

        if not symbol or price <= 0:
            return

        # --- Update rolling price history and compute technical features -
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=50)
            self._atr_history[symbol] = deque(maxlen=25)
            # Warm up buffer with historical bars so RSI/ATR are ready from tick 1
            await self._bootstrap_price_history(symbol)
        self._price_history[symbol].append(price)

        prices_list = list(self._price_history[symbol])
        rsi = compute_rsi(prices_list, period=REGIME_ATR_PERIOD)
        atr = compute_atr_from_prices(prices_list, period=REGIME_ATR_PERIOD)

        if atr is not None:
            self._atr_history[symbol].append(atr)

        atr_regime_ratio: float | None = None
        atr_hist = list(self._atr_history[symbol])
        if atr is not None and len(atr_hist) >= REGIME_ATR_AVG_PERIOD:
            avg_atr = sum(atr_hist[-REGIME_ATR_AVG_PERIOD:]) / REGIME_ATR_AVG_PERIOD
            if avg_atr > 0:
                atr_regime_ratio = round(atr / avg_atr, 4)

        # Time-of-day encoding.
        # Equities: US market hours only (14:30–21:00 UTC = 9:30–16:00 ET).
        # Crypto:   24/7 — classify by session proximity (Asia/Europe/US).
        hour_utc = datetime.now(timezone.utc).hour
        is_crypto = "/" in (symbol or "")
        if is_crypto:
            # Crypto session windows (UTC)
            if 14 <= hour_utc < 17:
                time_of_day = "us_open"  # 9:30–12:00 ET (high US volume)
            elif 17 <= hour_utc < 21:
                time_of_day = "us_afternoon"  # 12:00–16:00+ ET
            elif 0 <= hour_utc < 8:
                time_of_day = "asia_session"  # Asia markets active
            elif 8 <= hour_utc < 14:
                time_of_day = "europe_session"  # European markets active
            else:
                time_of_day = "overnight"
        else:
            # Equity time-of-day based on US market structure
            if 14 <= hour_utc < 16:
                time_of_day = "market_open"  # 9:30–11:00 ET — volatile open
            elif 16 <= hour_utc < 19:
                time_of_day = "midday"  # 11:00–14:00 ET — lower volume
            elif 19 <= hour_utc < 21:
                time_of_day = "market_close"  # 14:00–16:00 ET — late session
            else:
                time_of_day = "after_hours"

        # --- Classify signal ---------------------------------------------
        # Pure decision, shared with the backtest harness (see classify_signal).
        signal_type, strength, score, direction, action = classify_signal(pct)

        # --- Throttle the sub-threshold noise floor ----------------------
        # Indicator history is already warm (updated above); only the expensive
        # downstream work (publish + events/grades/runs/logs + reasoning→LLM)
        # is gated. A throttled tick still heartbeats so the dashboard keeps the
        # agent ACTIVE rather than aging it to STALE during a flat market.
        if not self._should_publish(symbol, strength):
            await write_heartbeat(
                self.bus.redis,
                AGENT_NAME,
                f"throttled {symbol} {pct:+.2f}%",
                event_count=self.total_events,
            )
            return

        signal_payload: dict[str, Any] = {
            FieldName.TYPE: signal_type.value,
            FieldName.SYMBOL: symbol,
            FieldName.PRICE: price,
            FieldName.PCT: pct,
            FieldName.DIRECTION: direction.value,
            FieldName.STRENGTH: strength.value,
            FieldName.COMPOSITE_SCORE: round(score / 100.0, 4),
            FieldName.CONFIDENCE: round(score / 100.0, 4),
            FieldName.ACTION: action,
            FieldName.TRACE_ID: trace_id,
            FieldName.TS: int(time.time()),
            FieldName.SOURCE: AGENT_NAME,
            FieldName.MSG_ID: str(uuid.uuid4()),
            FieldName.RSI: rsi,
            FieldName.ATR: atr,
            FieldName.ATR_REGIME_RATIO: atr_regime_ratio,
            FieldName.TIME_OF_DAY: time_of_day,
        }

        # --- Begin run (dedup check + run start write) -------------------
        run_id = str(uuid.uuid4())
        agent_pool_id = await self._resolve_agent_pool_id()
        start_time = time.perf_counter()

        should_proceed, db_run_id = await self._begin_run(
            run_id, trace_id, payload, agent_pool_id, msg_id
        )
        if not should_proceed:
            return

        # --- Publish signal to downstream agents -------------------------
        await self.bus.publish(STREAM_SIGNALS, signal_payload)

        # --- Persist signal data and complete the run --------------------
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        self.total_events += 1
        await self._persist_signal_complete(
            run_id, db_run_id, trace_id, signal_payload, agent_pool_id, msg_id, score, elapsed_ms
        )

        # --- Heartbeat ---------------------------------------------------
        await write_heartbeat(
            self.bus.redis,
            AGENT_NAME,
            f"{signal_type} {symbol} {pct:+.2f}%",
            event_count=self.total_events,
        )

        log_structured(
            "info",
            f"[{AGENT_NAME}] signal_published",
            signal_type=signal_type,
            symbol=symbol,
            price=price,
            direction=direction,
            trace_id=trace_id,
        )

    # ------------------------------------------------------------------
    # Unified persistence — single routing point per operation
    # ------------------------------------------------------------------

    async def _begin_run(
        self,
        run_id: str,
        trace_id: str,
        payload: dict,
        agent_pool_id: str | None,
        msg_id: str,
    ) -> tuple[bool, int | None]:
        """Dedup check (DB only) then write run start. Returns (should_proceed, db_run_id)."""
        if is_db_available():
            if await self._is_duplicate(msg_id):
                return False, None
            db_run_id = await self._db_write_run_start(run_id, trace_id, payload, agent_pool_id)
            return True, db_run_id
        get_runtime_store().add_agent_run(
            {
                FieldName.RUN_ID: run_id,
                FieldName.TRACE_ID: trace_id,
                FieldName.INPUT_DATA: payload,
                FieldName.SCHEMA_VERSION: DB_SCHEMA_VERSION,
                FieldName.SOURCE: SOURCE_SIGNAL,
                FieldName.STATUS: StatusValue.RUNNING,
                FieldName.CREATED_AT: time.time(),
            }
        )
        return True, None

    async def _persist_signal_complete(
        self,
        run_id: str,
        db_run_id: int | None,
        trace_id: str,
        signal_payload: dict,
        agent_pool_id: str | None,
        msg_id: str,
        score: float,
        elapsed_ms: int,
    ) -> None:
        """Persist signal event, grade, and run completion — routes DB vs memory."""
        if is_db_available():
            await self._db_write_signal(
                trace_id, msg_id, signal_payload, score, agent_pool_id, run_id
            )
            await self._db_write_run_complete(
                db_run_id, run_id, trace_id, signal_payload, elapsed_ms
            )
            return
        symbol = signal_payload[FieldName.SYMBOL]
        store = get_runtime_store()
        store.add_event(
            {
                FieldName.EVENT_TYPE: EventType.SIGNAL_GENERATED,
                FieldName.ENTITY_TYPE: EntityType.SIGNAL,
                FieldName.ENTITY_ID: trace_id,
                FieldName.DATA: signal_payload,
                FieldName.IDEMPOTENCY_KEY: f"signal-{symbol}-{trace_id}",
                FieldName.SCHEMA_VERSION: DB_SCHEMA_VERSION,
                FieldName.SOURCE: SOURCE_SIGNAL,
            }
        )
        store.add_grade(
            {
                FieldName.TRACE_ID: trace_id,
                FieldName.GRADE_TYPE: GradeType.ACCURACY,
                FieldName.SCORE: score,
                FieldName.METRICS: {
                    "signal_type": signal_payload[FieldName.TYPE],
                    "symbol": symbol,
                },
                FieldName.SOURCE: SOURCE_SIGNAL,
                FieldName.SCHEMA_VERSION: DB_SCHEMA_VERSION,
            }
        )
        for run in store.agent_runs:
            if run.get(FieldName.RUN_ID) == run_id:
                run.update(
                    {
                        FieldName.STATUS: StatusValue.COMPLETED,
                        FieldName.OUTPUT_DATA: signal_payload,
                        FieldName.EXECUTION_TIME_MS: elapsed_ms,
                    }
                )
                break
        store.add_event(
            {
                FieldName.AGENT_RUN_ID: run_id,
                FieldName.TRACE_ID: trace_id,
                FieldName.LOG_TYPE: AgentLogType.SIGNAL_GENERATED,
                FieldName.PAYLOAD: signal_payload,
                FieldName.SCHEMA_VERSION: DB_SCHEMA_VERSION,
                FieldName.SOURCE: AGENT_NAME,
                FieldName.TIMESTAMP: time.time(),
            }
        )

    # ------------------------------------------------------------------
    # DB write helpers — only called when is_db_available() is True
    # ------------------------------------------------------------------

    async def _is_duplicate(self, msg_id: str) -> bool:
        """Return True if this msg_id has already been processed (DB mode only)."""
        try:
            async with AsyncSessionFactory() as session:
                row = await session.execute(
                    text("SELECT 1 FROM processed_events WHERE msg_id = :msg_id"),
                    {"msg_id": msg_id},
                )
                if row.first():
                    log_structured("debug", f"[{AGENT_NAME}] duplicate_skipped", msg_id=msg_id)
                    return True
        except Exception:
            # Dedup failure → allow through; duplicates are preferable to missed signals
            log_structured("warning", f"[{AGENT_NAME}] dedup_check_failed", exc_info=True)
        return False

    async def _db_write_run_start(
        self,
        run_id: str,
        trace_id: str,
        payload: dict,
        agent_pool_id: str | None,
    ) -> int | None:
        """INSERT agent_runs row. Returns the integer PK (RETURNING id)."""
        try:
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    result = await session.execute(
                        text("""
                            INSERT INTO agent_runs
                                (strategy_id, trace_id, input_data,
                                 schema_version, source, status,
                                 created_at, updated_at)
                            VALUES
                                (:strategy_id, :trace_id, :input_data,
                                 :schema_version, :source, 'running',
                                 NOW(), NOW())
                            RETURNING id
                        """),
                        {
                            "strategy_id": agent_pool_id or None,
                            "trace_id": trace_id,
                            "input_data": json.dumps(payload),
                            "schema_version": DB_SCHEMA_VERSION,
                            "source": SOURCE_SIGNAL,
                        },
                    )
                    row = result.first()
                    return row[0] if row else None
        except Exception:
            log_structured(
                "error", f"[{AGENT_NAME}] agent_run_insert_failed", trace_id=trace_id, exc_info=True
            )
            return None

    async def _db_write_signal(
        self,
        trace_id: str,
        msg_id: str,
        signal_payload: dict,
        score: float,
        agent_pool_id: str | None,
        run_id: str,
    ) -> None:
        """Write event, grade, and processed-events marker in one transaction."""
        try:
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            INSERT INTO events
                                (event_type, entity_type, entity_id, data,
                                 idempotency_key, schema_version, source)
                            VALUES
                                ('signal.generated', 'signal', :entity_id, :data,
                                 :idem_key, :schema_version, :source)
                            ON CONFLICT (idempotency_key) DO NOTHING
                        """),
                        {
                            "entity_id": trace_id,
                            "data": json.dumps(signal_payload),
                            FieldName.IDEM_KEY: f"signal-{signal_payload[FieldName.SYMBOL]}-{trace_id}",
                            "schema_version": DB_SCHEMA_VERSION,
                            "source": SOURCE_SIGNAL,
                        },
                    )
                    await session.execute(
                        text("""
                            INSERT INTO agent_grades
                                (agent_id, agent_run_id, grade_type, score, metrics,
                                 source, trace_id, schema_version)
                            VALUES
                                (:strategy_id, :agent_run_id, :grade_type, :score,
                                 CAST(:metrics AS JSONB), :source, :trace_id, :schema_version)
                        """),
                        {
                            "strategy_id": agent_pool_id or None,
                            "agent_run_id": run_id,
                            "grade_type": GradeType.ACCURACY,
                            "score": score,
                            "metrics": json.dumps(
                                {
                                    "signal_type": signal_payload[FieldName.TYPE],
                                    "symbol": signal_payload[FieldName.SYMBOL],
                                }
                            ),
                            "source": SOURCE_SIGNAL,
                            "trace_id": trace_id,
                            "schema_version": DB_SCHEMA_VERSION,
                        },
                    )
                    await session.execute(
                        text("""
                            INSERT INTO processed_events (msg_id, stream)
                            VALUES (:msg_id, :stream)
                            ON CONFLICT DO NOTHING
                        """),
                        {"msg_id": msg_id, "stream": STREAM_MARKET_EVENTS},
                    )
        except Exception:
            log_structured(
                "error", f"[{AGENT_NAME}] signal_db_write_failed", trace_id=trace_id, exc_info=True
            )

    async def _db_write_run_complete(
        self,
        db_run_id: int | None,
        run_id: str,
        trace_id: str,
        signal_payload: dict,
        elapsed_ms: int,
    ) -> None:
        """UPDATE agent_runs status and INSERT agent_log entry."""
        try:
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    if db_run_id is not None:
                        await session.execute(
                            text("""
                                UPDATE agent_runs
                                SET status='completed',
                                    output_data=:output,
                                    execution_time_ms=:elapsed,
                                    updated_at=NOW()
                                WHERE id=:id
                            """),
                            {
                                FieldName.OUTPUT: json.dumps(signal_payload),
                                FieldName.ELAPSED: elapsed_ms,
                                FieldName.ID: db_run_id,
                            },
                        )
                    await session.execute(
                        text("""
                            INSERT INTO agent_logs
                                (agent_run_id, trace_id, log_type,
                                 payload, schema_version, source)
                            VALUES
                                (:agent_run_id, :trace_id, :log_type,
                                 CAST(:payload AS JSONB), :schema_version, :source)
                        """),
                        {
                            "agent_run_id": run_id,
                            "trace_id": trace_id,
                            "log_type": LogType.SIGNAL_GENERATED,
                            "payload": json.dumps(signal_payload),
                            "schema_version": DB_SCHEMA_VERSION,
                            "source": AGENT_NAME,
                        },
                    )
        except Exception:
            log_structured(
                "warning",
                f"[{AGENT_NAME}] run_complete_write_failed",
                trace_id=trace_id,
                exc_info=True,
            )
