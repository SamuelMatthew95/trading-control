"""Telemetry must be a perfect no-op while OTEL_ENABLED=false (the default).

The trading pipeline calls these hooks on every event, so the disabled path
is the one that runs in CI and in any deployment without a collector — it
must never raise, never import the SDK, and never change call results.
"""

import json

import pytest

from api import telemetry
from api.constants import (
    PNL_GRADED_AGENTS,
    REDIS_KEY_AGENT_PNL,
    REDIS_KEY_CLOSED_TRADES_RECENT,
    REDIS_KEY_PAPER_CASH,
    REDIS_KEY_PAPER_POSITION,
    FieldName,
)


class TestDisabledNoOps:
    def test_disabled_by_default(self):
        assert telemetry.is_enabled() is False

    def test_init_returns_false_when_disabled(self, monkeypatch):
        monkeypatch.setattr(telemetry.settings, "OTEL_ENABLED", False)
        assert telemetry.init_telemetry(app=None) is False
        assert telemetry.is_enabled() is False

    def test_agent_process_span_yields_none(self):
        with telemetry.agent_process_span("SIGNAL_AGENT", "signals", trace_id="t-1") as span:
            assert span is None

    def test_counters_are_safe(self):
        telemetry.record_signal_generated("BTC/USD", signal_type="momentum_buy")
        telemetry.record_error("execution-engine")
        telemetry.record_retry("decisions")

    def test_log_processor_passthrough(self):
        event = {"event": "hello"}
        assert telemetry.otel_log_processor(None, "info", event) is event
        assert FieldName.OTEL_TRACE_ID not in event


class TestRedisInstrumentationGating:
    """Redis command instrumentation must stay OFF unless explicitly opted in.

    Instrumenting every Redis command spans the always-on XREADGROUP/XREAD
    BLOCK loops (~14 consumers, ~10x/sec each) — pure overhead on the scarce
    shared BlockingConnectionPool whose exhaustion wedged the dashboard. The
    default-off contract guards against that regression silently returning.
    """

    def test_flag_defaults_off(self):
        assert telemetry.settings.OTEL_INSTRUMENT_REDIS is False

    def test_skips_instrumentation_when_flag_off(self, monkeypatch):
        redis_mod = pytest.importorskip("opentelemetry.instrumentation.redis")
        calls = []

        class _SpyInstrumentor:
            def instrument(self, *args, **kwargs):
                calls.append(True)

        monkeypatch.setattr(redis_mod, "RedisInstrumentor", _SpyInstrumentor)
        monkeypatch.setattr(telemetry.settings, "OTEL_INSTRUMENT_REDIS", False)

        telemetry._instrument_redis()

        assert calls == [], "Redis must NOT be instrumented while the flag is off"

    def test_instruments_when_flag_on(self, monkeypatch):
        redis_mod = pytest.importorskip("opentelemetry.instrumentation.redis")
        calls = []

        class _SpyInstrumentor:
            def instrument(self, *args, **kwargs):
                calls.append(True)

        monkeypatch.setattr(redis_mod, "RedisInstrumentor", _SpyInstrumentor)
        monkeypatch.setattr(telemetry.settings, "OTEL_INSTRUMENT_REDIS", True)

        telemetry._instrument_redis()

        assert calls == [True], "Redis SHOULD be instrumented when the flag is on"


class TestOtlpHeaderParsing:
    def test_standard_format(self):
        parsed = telemetry.parse_otlp_headers("signoz-ingestion-key=abc123,x-env=prod")
        assert parsed == {"signoz-ingestion-key": "abc123", "x-env": "prod"}

    def test_value_containing_equals(self):
        assert telemetry.parse_otlp_headers("authorization=Basic dXNlcg==") == {
            "authorization": "Basic dXNlcg=="
        }

    def test_malformed_entries_skipped_never_raise(self):
        assert telemetry.parse_otlp_headers("") == {}
        assert telemetry.parse_otlp_headers("no-equals-sign,=novalue,, ok=1") == {"ok": "1"}


class TestHttpEndpointBuilding:
    def test_signoz_cloud_form(self):
        assert (
            telemetry.build_http_endpoint(
                "https://ingest.us2.signoz.cloud:443", "traces", insecure=False
            )
            == "https://ingest.us2.signoz.cloud:443/v1/traces"
        )

    def test_scheme_added_from_insecure_flag(self):
        assert telemetry.build_http_endpoint(
            "ingest.eu.signoz.cloud:443", "metrics", insecure=False
        ) == ("https://ingest.eu.signoz.cloud:443/v1/metrics")
        assert telemetry.build_http_endpoint("localhost:4318", "traces", insecure=True) == (
            "http://localhost:4318/v1/traces"
        )

    def test_trailing_slash_normalized(self):
        assert telemetry.build_http_endpoint("https://host/", "traces", insecure=False) == (
            "https://host/v1/traces"
        )


class TestTracedBrokerCall:
    async def test_passthrough_result(self):
        @telemetry.traced_broker_call("place_order", "paper", is_order=True)
        async def place_order(self, symbol, side, qty, price):
            return {FieldName.STATUS: "filled", FieldName.SYMBOL: symbol}

        result = await place_order(object(), "BTC/USD", "buy", 0.1, 50000.0)
        assert result[FieldName.SYMBOL] == "BTC/USD"

    async def test_exceptions_propagate(self):
        @telemetry.traced_broker_call("place_order", "alpaca", is_order=True)
        async def place_order(self, symbol, side, qty, price):
            raise RuntimeError("broker down")

        with pytest.raises(RuntimeError, match="broker down"):
            await place_order(object(), "BTC/USD", "buy", 0.1, 50000.0)


class TestBusinessGauges:
    def test_set_business_gauge_coerces_to_float(self):
        telemetry.set_business_gauge(FieldName.WIN_RATE, 1)
        assert telemetry._gauge_values[str(FieldName.WIN_RATE)] == 1.0

    async def test_refresh_reads_redis_state(self, fake_redis):
        await fake_redis.set(REDIS_KEY_PAPER_CASH, "98765.43")
        await fake_redis.set(
            REDIS_KEY_PAPER_POSITION.format(symbol="BTC/USD"),
            json.dumps({FieldName.SYMBOL: "BTC/USD", FieldName.QTY: 0.5}),
        )
        await fake_redis.set(
            REDIS_KEY_PAPER_POSITION.format(symbol="ETH/USD"),
            json.dumps({FieldName.SYMBOL: "ETH/USD", FieldName.QTY: 0.0}),
        )
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        await fake_redis.lpush(
            REDIS_KEY_CLOSED_TRADES_RECENT,
            json.dumps({FieldName.PNL: 12.5, FieldName.FILLED_AT: now_iso}),
            json.dumps({FieldName.PNL: -2.5, FieldName.FILLED_AT: now_iso}),
            json.dumps({FieldName.PNL: 99.0, FieldName.FILLED_AT: "2020-01-01T00:00:00Z"}),
        )
        an_agent = next(iter(PNL_GRADED_AGENTS))
        await fake_redis.hset(
            REDIS_KEY_AGENT_PNL.format(name=an_agent),
            mapping={FieldName.TRADE_COUNT: "4", FieldName.WIN_COUNT: "3"},
        )

        await telemetry._refresh_business_gauges(fake_redis)

        values = telemetry._gauge_values
        assert values[str(FieldName.ACCOUNT_BALANCE)] == pytest.approx(98765.43)
        assert values[str(FieldName.OPEN_POSITIONS)] == 1.0  # ETH is flat
        assert values[str(FieldName.DAILY_PNL)] == pytest.approx(10.0)  # old trade excluded
        assert values[str(FieldName.WIN_RATE)] == pytest.approx(0.75)

    async def test_gauge_poller_noop_when_disabled(self, fake_redis):
        telemetry.start_gauge_poller(fake_redis)
        assert telemetry._gauge_task is None
        await telemetry.stop_gauge_poller()
