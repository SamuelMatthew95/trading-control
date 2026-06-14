"""OpenTelemetry integration — traces, metrics, and log correlation.

Everything in this module is OPTIONAL and fails open:

* ``OTEL_ENABLED=false`` (the default) → every public function is a no-op
  with near-zero overhead; the SDK is never imported.
* SDK packages missing → ``init_telemetry()`` logs one warning and the app
  runs exactly as before.

Instrumentation map (kept deliberately thin so trading logic never changes):

* ``agent_process_span()`` — wraps every stream-event dispatch in
  ``BaseStreamConsumer`` / ``MultiStreamAgent``; one call site covers the
  whole 7-agent pipeline and records ``agent_process_duration``.
* ``traced_broker_call()`` — decorates broker methods; records
  ``broker_api_latency`` per operation plus the order counters
  (``trades_submitted_total`` / ``trades_completed_total`` /
  ``trades_failed_total``) and ``trade_execution_duration`` for fills.
* ``record_signal_generated()`` — one line in SignalGenerator.
* Business gauges (``daily_pnl`` / ``open_positions`` / ``win_rate`` /
  ``account_balance``) are fed by a read-only Redis poller task so the
  trading path is never touched.
* ``otel_log_processor`` — structlog processor that stamps
  ``otel_trace_id`` / ``otel_span_id`` onto every JSON log line for
  log↔trace correlation in SigNoz.
"""

from __future__ import annotations

import asyncio
import functools
import json
import time
from collections.abc import Awaitable, Callable
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from api.config import settings
from api.constants import (
    DRIFT_KIND_LABEL,
    PNL_GRADED_AGENTS,
    REDIS_KEY_AGENT_PNL,
    REDIS_KEY_CLOSED_TRADES_RECENT,
    REDIS_KEY_PAPER_CASH,
    REDIS_KEY_TELEMETRY_DRIFT_REPORTED,
    TELEMETRY_DRIFT_METRIC,
    FieldName,
    OrderStatus,
)
from api.observability import log_structured
from api.telemetry_drift import TelemetryDriftAuditor, fetch_signoz_observed_keys

_ATTR_PREFIX = "trading."

# Module state — populated by init_telemetry(), None while disabled.
_enabled: bool = False
_trace_api: Any = None
_tracer: Any = None
_instruments: dict[str, Any] = {}
_gauge_values: dict[str, float] = {}
_gauge_lock = Lock()
_gauge_task: asyncio.Task[None] | None = None
_drift_enabled: bool = False
_auditor: TelemetryDriftAuditor | None = None
_drift_task: asyncio.Task[None] | None = None
_last_action: dict[str, str] = {}
_decision_lock = Lock()


def is_enabled() -> bool:
    return _enabled


def _attrs(**kwargs: Any) -> dict[str, Any]:
    """Build OTel attribute dicts from kwargs (namespaced, None-stripped)."""
    attrs = {f"{_ATTR_PREFIX}{key}": value for key, value in kwargs.items() if value is not None}
    if _drift_enabled and _auditor is not None:
        for attr_key in attrs:
            _auditor.record_key(attr_key)
    return attrs


def parse_otlp_headers(raw: str) -> dict[str, str]:
    """Parse the standard OTLP headers format: ``key1=value1,key2=value2``.

    Used for managed-backend auth (e.g. ``signoz-ingestion-key=<token>``).
    Malformed entries are skipped rather than raising — a bad header must
    never prevent the app from starting.
    """
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        key, sep, value = pair.partition("=")
        if sep and key.strip():
            headers[key.strip()] = value.strip()
    return headers


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init_telemetry(app: Any = None) -> bool:
    """Configure tracer/meter providers and auto-instrumentation.

    Returns True when telemetry is live. Safe to call when disabled or when
    the SDK is not installed — both paths leave the app untouched.
    """
    global _enabled, _trace_api, _tracer, _drift_enabled, _auditor
    if not settings.OTEL_ENABLED:
        log_structured("info", "telemetry_disabled")
        return False
    if _enabled:
        return True

    try:
        # Optional dependency — only imported when OTEL_ENABLED=true.
        from opentelemetry import metrics, trace  # noqa: PLC0415
        from opentelemetry.sdk.metrics import MeterProvider  # noqa: PLC0415
        from opentelemetry.sdk.metrics.export import (  # noqa: PLC0415
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415

        span_exporter, metric_exporter = _build_exporters()
    except ImportError:
        log_structured("warning", "telemetry_sdk_missing_running_without_otel")
        return False

    # service.version etc. merge in from OTEL_RESOURCE_ATTRIBUTES automatically.
    resource = Resource.create({"service.name": settings.OTEL_SERVICE_NAME})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    reader = PeriodicExportingMetricReader(metric_exporter)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))

    _trace_api = trace
    _tracer = trace.get_tracer("trading-control")
    _create_instruments(metrics.get_meter("trading-control"))
    _instrument_libraries(app)

    _drift_enabled = settings.OTEL_DRIFT_AUDIT_ENABLED
    if _drift_enabled:
        _auditor = TelemetryDriftAuditor()

    _enabled = True
    log_structured(
        "info",
        "telemetry_initialized",
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        protocol=settings.OTEL_EXPORTER_OTLP_PROTOCOL,
        service_name=settings.OTEL_SERVICE_NAME,
    )
    return True


def build_http_endpoint(base: str, signal: str, *, insecure: bool) -> str:
    """Build the per-signal URL the OTLP/HTTP exporters require.

    The HTTP exporters take a FULL url including the signal path
    (``https://host:443/v1/traces``), unlike gRPC which takes ``host:port``.
    A missing scheme is filled in from the insecure flag.
    """
    base = base.rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = f"{'http' if insecure else 'https'}://{base}"
    return f"{base}/v1/{signal}"


def _build_exporters() -> tuple[Any, Any]:
    """Construct span+metric exporters for the configured OTLP protocol.

    ``grpc`` (default) suits local collectors on :4317; ``http/protobuf`` is
    what SigNoz Cloud's onboarding documents (TLS on :443). Raises
    ImportError when the relevant exporter package is missing — handled by
    the caller as "run without telemetry".
    """
    headers = parse_otlp_headers(settings.OTEL_EXPORTER_OTLP_HEADERS) or None
    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
    insecure = settings.OTEL_EXPORTER_OTLP_INSECURE

    if settings.OTEL_EXPORTER_OTLP_PROTOCOL.strip().lower() == "http/protobuf":
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # noqa: PLC0415
            OTLPMetricExporter as HTTPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: PLC0415
            OTLPSpanExporter as HTTPSpanExporter,
        )

        return (
            HTTPSpanExporter(
                endpoint=build_http_endpoint(endpoint, "traces", insecure=insecure),
                headers=headers,
            ),
            HTTPMetricExporter(
                endpoint=build_http_endpoint(endpoint, "metrics", insecure=insecure),
                headers=headers,
            ),
        )

    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (  # noqa: PLC0415
        OTLPMetricExporter as GRPCMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # noqa: PLC0415
        OTLPSpanExporter as GRPCSpanExporter,
    )

    return (
        GRPCSpanExporter(endpoint=endpoint, insecure=insecure, headers=headers),
        GRPCMetricExporter(endpoint=endpoint, insecure=insecure, headers=headers),
    )


def _create_instruments(meter: Any) -> None:
    _instruments.update(
        signals_generated=meter.create_counter(
            "signals_generated_total", description="Trading signals published"
        ),
        trades_submitted=meter.create_counter(
            "trades_submitted_total", description="Orders submitted to the broker"
        ),
        trades_completed=meter.create_counter(
            "trades_completed_total", description="Orders confirmed filled by the broker"
        ),
        trades_failed=meter.create_counter(
            "trades_failed_total", description="Orders rejected or errored at the broker"
        ),
        errors=meter.create_counter("error_count", description="Processing errors by component"),
        retries=meter.create_counter(
            "retry_count", description="Event processing retries by stream"
        ),
        trade_execution_duration=meter.create_histogram(
            "trade_execution_duration",
            unit="ms",
            description="Order submission → broker fill latency",
        ),
        broker_api_latency=meter.create_histogram(
            "broker_api_latency", unit="ms", description="Broker API call latency by operation"
        ),
        database_query_duration=meter.create_histogram(
            "database_query_duration", unit="ms", description="SQL statement execution time"
        ),
        agent_process_duration=meter.create_histogram(
            "agent_process_duration", unit="ms", description="Per-agent event processing time"
        ),
        telemetry_schema_drift=meter.create_counter(
            TELEMETRY_DRIFT_METRIC, description="Telemetry schema drift detections by kind"
        ),
        agent_decisions=meter.create_counter(
            "agent_decisions_total", description="Reasoning decisions by model and action"
        ),
        agent_decision_flips=meter.create_counter(
            "agent_decision_flips_total",
            description="Reasoning action changes vs the prior decision, per symbol",
        ),
    )

    def _gauge_callback(name: str) -> Callable[[Any], list[Any]]:
        def callback(_options: Any) -> list[Any]:
            from opentelemetry.metrics import Observation  # noqa: PLC0415

            with _gauge_lock:
                value = _gauge_values.get(name)
            return [] if value is None else [Observation(value)]

        return callback

    for gauge_name in (
        FieldName.DAILY_PNL,
        FieldName.OPEN_POSITIONS,
        FieldName.WIN_RATE,
        FieldName.ACCOUNT_BALANCE,
    ):
        meter.create_observable_gauge(str(gauge_name), callbacks=[_gauge_callback(gauge_name)])


def _instrument_libraries(app: Any) -> None:
    """Attach auto-instrumentation; each integration is independently optional."""
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import (  # noqa: PLC0415
                FastAPIInstrumentor,
            )

            FastAPIInstrumentor.instrument_app(app, excluded_urls="health,readiness")
        except Exception:
            log_structured("warning", "telemetry_fastapi_instrumentation_failed", exc_info=True)
    _instrument_redis()
    try:
        from opentelemetry.instrumentation.aiohttp_client import (  # noqa: PLC0415
            AioHttpClientInstrumentor,
        )

        AioHttpClientInstrumentor().instrument()
    except Exception:
        log_structured("warning", "telemetry_aiohttp_instrumentation_failed", exc_info=True)
    try:
        from opentelemetry.instrumentation.sqlalchemy import (  # noqa: PLC0415
            SQLAlchemyInstrumentor,
        )

        from api.database import engine  # noqa: PLC0415

        if engine is not None:
            SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
            _attach_query_duration_listener(engine.sync_engine)
    except Exception:
        log_structured("warning", "telemetry_sqlalchemy_instrumentation_failed", exc_info=True)


def _instrument_redis() -> None:
    """Auto-instrument Redis commands — gated OFF by default (OTEL_INSTRUMENT_REDIS).

    RedisInstrumentor wraps EVERY command on the single process-wide
    BlockingConnectionPool. The bulk of that traffic is the ~14 always-on
    XREADGROUP/XREAD BLOCK loops (one per pipeline agent / challenger + the
    EventPipeline + the WebSocket broadcaster), each firing ~10x/sec — so the
    instrumentation's dominant output is a "blocking read returned nothing"
    span per consumer per 100ms, the highest-volume / lowest-value span source
    in the system, layered onto the scarcest shared resource (the pooled
    connections whose exhaustion already wedged the dashboard — see
    docs/troubleshooting/system-routes.md).

    The trade lifecycle stays fully traced without it: agent_process_span,
    traced_broker_call, and the SQLAlchemy query listener already cover the
    meaningful latencies. Flip OTEL_INSTRUMENT_REDIS=true only to actively
    debug Redis itself.
    """
    if not settings.OTEL_INSTRUMENT_REDIS:
        log_structured("info", "telemetry_redis_instrumentation_skipped")
        return
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor  # noqa: PLC0415

        RedisInstrumentor().instrument()
    except Exception:
        log_structured("warning", "telemetry_redis_instrumentation_failed", exc_info=True)


def _attach_query_duration_listener(sync_engine: Any) -> None:
    """Feed the database_query_duration histogram from SQLAlchemy cursor events."""
    from sqlalchemy import event  # noqa: PLC0415

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before(conn, _cursor, _stmt, _params, _ctx, _executemany):  # noqa: ANN001
        conn.info.setdefault("otel_query_start", []).append(time.perf_counter())

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after(conn, _cursor, _stmt, _params, _ctx, _executemany):  # noqa: ANN001
        starts = conn.info.get("otel_query_start")
        if starts:
            elapsed_ms = (time.perf_counter() - starts.pop()) * 1000.0
            histogram = _instruments.get("database_query_duration")
            if histogram is not None:
                histogram.record(elapsed_ms)


# ---------------------------------------------------------------------------
# Spans
# ---------------------------------------------------------------------------


@contextmanager
def agent_process_span(agent: str, stream: str, trace_id: str | None = None):
    """Span + duration histogram around one agent event dispatch.

    The app-level trace_id rides along as an attribute so a SigNoz search for
    it surfaces every span of the trade lifecycle.
    """
    if not _enabled or _tracer is None:
        yield None
        return
    started = time.perf_counter()
    with _tracer.start_as_current_span(
        f"agent.process {agent}",
        attributes=_attrs(agent=agent, stream=stream, trace_id=trace_id),
    ) as span:
        try:
            yield span
        finally:
            histogram = _instruments.get("agent_process_duration")
            if histogram is not None:
                histogram.record(
                    (time.perf_counter() - started) * 1000.0, attributes=_attrs(agent=agent)
                )


def otel_log_processor(_logger: Any, _method_name: str, event_dict: dict[str, Any]):
    """structlog processor — stamp active trace/span ids onto each log line."""
    if _enabled and _trace_api is not None:
        span = _trace_api.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            event_dict[FieldName.OTEL_TRACE_ID] = format(ctx.trace_id, "032x")
            event_dict[FieldName.OTEL_SPAN_ID] = format(ctx.span_id, "016x")
    return event_dict


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------


def _add(instrument_key: str, amount: int = 1, **attributes: Any) -> None:
    if not _enabled:
        return
    counter = _instruments.get(instrument_key)
    if counter is not None:
        counter.add(amount, attributes=_attrs(**attributes))


def record_signal_generated(symbol: str, signal_type: str | None = None) -> None:
    _add("signals_generated", symbol=symbol, signal_type=signal_type)


def record_error(component: str) -> None:
    _add("errors", component=component)


def record_retry(stream: str) -> None:
    _add("retries", stream=stream)


def record_decision(symbol: str, action: str, model: str) -> None:
    """Record one finalized reasoning decision: model + action, plus per-symbol flips.

    Drives ``llm_fallback_ratio`` (the share of decisions whose model is a
    fallback/policy label) and the decision-flip rate. No-op when telemetry is
    disabled, so the reasoning hot path is untouched in the default build.
    """
    if not _enabled:
        return
    _add("agent_decisions", model=model, action=action)
    if not symbol:
        return
    with _decision_lock:
        prev = _last_action.get(symbol)
        _last_action[symbol] = action
    if prev is not None and prev != action:
        _add("agent_decision_flips", symbol=symbol)


# ---------------------------------------------------------------------------
# Broker instrumentation
# ---------------------------------------------------------------------------


def traced_broker_call(
    operation: str, broker: str, *, is_order: bool = False
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator for async broker methods.

    Records broker_api_latency for every call; for order placement
    (``is_order=True``) additionally drives the trades_* counters and the
    trade_execution_duration histogram. Exceptions always propagate.
    """

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _enabled:
                return await fn(*args, **kwargs)
            # place_order(self, symbol, side, qty, price) — best-effort labels.
            symbol = str(args[1]) if is_order and len(args) > 1 else None
            side = str(args[2]) if is_order and len(args) > 2 else None
            if is_order:
                _add("trades_submitted", symbol=symbol, side=side, broker=broker)
            started = time.perf_counter()
            span_cm = (
                _tracer.start_as_current_span(
                    f"broker.{operation}",
                    attributes=_attrs(broker=broker, operation=operation, symbol=symbol),
                )
                if _tracer is not None
                else nullcontext()
            )
            with span_cm:
                try:
                    result = await fn(*args, **kwargs)
                except Exception:
                    _record_broker_latency(operation, broker, started, success=False)
                    if is_order:
                        _add("trades_failed", symbol=symbol, side=side, broker=broker)
                    record_error(f"broker.{broker}")
                    raise
            elapsed_ms = _record_broker_latency(operation, broker, started, success=True)
            if is_order:
                status = result.get(FieldName.STATUS) if isinstance(result, dict) else None
                if status == OrderStatus.REJECTED:
                    _add("trades_failed", symbol=symbol, side=side, broker=broker)
                else:
                    _add("trades_completed", symbol=symbol, side=side, broker=broker)
                    histogram = _instruments.get("trade_execution_duration")
                    if histogram is not None:
                        histogram.record(elapsed_ms, attributes=_attrs(symbol=symbol, side=side))
            return result

        return wrapper

    return decorator


def _record_broker_latency(operation: str, broker: str, started: float, *, success: bool) -> float:
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    histogram = _instruments.get("broker_api_latency")
    if histogram is not None:
        histogram.record(
            elapsed_ms, attributes=_attrs(operation=operation, broker=broker, success=success)
        )
    return elapsed_ms


# ---------------------------------------------------------------------------
# Business gauges — read-only Redis poller (never touches the trading path)
# ---------------------------------------------------------------------------


def set_business_gauge(name: str, value: float) -> None:
    with _gauge_lock:
        _gauge_values[str(name)] = float(value)


async def _refresh_business_gauges(redis: Any) -> None:
    cash_raw = await redis.get(REDIS_KEY_PAPER_CASH)
    if cash_raw is not None:
        set_business_gauge(FieldName.ACCOUNT_BALANCE, float(cash_raw))

    open_count = 0
    async for key in redis.scan_iter(match="paper:positions:*"):
        raw = await redis.get(key)
        if raw:
            position = json.loads(raw)
            if abs(float(position.get(FieldName.QTY) or 0.0)) > 1e-9:
                open_count += 1
    set_business_gauge(FieldName.OPEN_POSITIONS, float(open_count))

    today = datetime.now(timezone.utc).date().isoformat()
    daily_pnl = 0.0
    for raw in await redis.lrange(REDIS_KEY_CLOSED_TRADES_RECENT, 0, -1):
        trade = json.loads(raw)
        closed_at = str(trade.get(FieldName.FILLED_AT) or trade.get(FieldName.TIMESTAMP) or "")
        if closed_at.startswith(today):
            daily_pnl += float(trade.get(FieldName.PNL) or 0.0)
    set_business_gauge(FieldName.DAILY_PNL, daily_pnl)

    trades = wins = 0
    for agent_name in PNL_GRADED_AGENTS:
        stats = await redis.hgetall(REDIS_KEY_AGENT_PNL.format(name=agent_name))
        if stats:
            trades += int(stats.get(FieldName.TRADE_COUNT) or 0)
            wins += int(stats.get(FieldName.WIN_COUNT) or 0)
    if trades:
        set_business_gauge(FieldName.WIN_RATE, wins / trades)


async def _gauge_poll_loop(redis: Any) -> None:
    while True:
        try:
            await _refresh_business_gauges(redis)
        except asyncio.CancelledError:
            raise
        except Exception:
            log_structured("warning", "telemetry_gauge_refresh_failed", exc_info=True)
        await asyncio.sleep(settings.OTEL_GAUGE_POLL_SECONDS)


def start_gauge_poller(redis: Any) -> None:
    """Launch the periodic business-gauge refresh. No-op when telemetry is off."""
    global _gauge_task
    if not _enabled or _gauge_task is not None:
        return
    _gauge_task = asyncio.create_task(_gauge_poll_loop(redis), name="telemetry:gauges")


async def stop_gauge_poller() -> None:
    global _gauge_task
    if _gauge_task is not None:
        _gauge_task.cancel()
        try:
            await _gauge_task
        except asyncio.CancelledError:
            pass
        _gauge_task = None


# ---------------------------------------------------------------------------
# Runtime schema-drift auditor (governance Layer B) — see api/telemetry_drift.py
# ---------------------------------------------------------------------------


def _emit_drift(kind: str) -> None:
    counter = _instruments.get("telemetry_schema_drift")
    if counter is not None:
        counter.add(1, attributes={DRIFT_KIND_LABEL: kind})


async def _drift_audit_loop(redis: Any) -> None:
    if _auditor is None:
        return
    # Hydrate the dedup set so a standing violation pages once across restarts.
    try:
        tags = await redis.smembers(REDIS_KEY_TELEMETRY_DRIFT_REPORTED)
        _auditor.seed_reported([t.decode() if isinstance(t, bytes) else t for t in tags])
    except Exception:
        log_structured("warning", "telemetry_drift_reported_hydrate_failed", exc_info=True)
    while True:
        try:
            counts = _auditor.observed_snapshot()
            b2_counts, cardinalities = await fetch_signoz_observed_keys(settings)
            counts.update(b2_counts)
            fresh = _auditor.unreported(_auditor.detect(counts, cardinalities))
            for finding in fresh:
                _emit_drift(finding.kind)
                log_structured(
                    "warning",
                    "telemetry_schema_drift",
                    kind=finding.kind,
                    attribute=finding.attribute,
                    occurrences=finding.occurrences,
                )
            if fresh:
                await redis.sadd(
                    REDIS_KEY_TELEMETRY_DRIFT_REPORTED,
                    *[f"{f.kind}:{f.attribute}" for f in fresh],
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log_structured("warning", "telemetry_drift_audit_failed", exc_info=True)
        await asyncio.sleep(settings.OTEL_DRIFT_AUDIT_INTERVAL_SECONDS)


def start_drift_auditor(redis: Any) -> None:
    """Launch the periodic schema-drift audit. No-op unless OTEL_DRIFT_AUDIT_ENABLED."""
    global _drift_task
    if not _enabled or not _drift_enabled or _drift_task is not None:
        return
    _drift_task = asyncio.create_task(_drift_audit_loop(redis), name="telemetry:drift")


async def stop_drift_auditor() -> None:
    global _drift_task
    if _drift_task is not None:
        _drift_task.cancel()
        try:
            await _drift_task
        except asyncio.CancelledError:
            pass
        _drift_task = None
