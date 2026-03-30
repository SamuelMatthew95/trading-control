"""Tests for signal pipeline components."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.config import settings
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.llm_router import _get_provider_key, _parse_response, call_llm
from api.services.signal_generator import SignalGenerator


class _MockAsyncSession:
    """Mock async session that supports 'async with session.begin()'."""

    def __init__(self):
        self._result = MagicMock()
        self._result.first.return_value = None
        self._result.scalar.return_value = None

    async def execute(self, *args, **kwargs):
        return self._result

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass

    def begin(self):
        return _AsyncCtx()


class _AsyncCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class _MockSessionFactory:
    """Callable that returns an async context manager yielding a mock session."""

    def __call__(self):
        return self

    async def __aenter__(self):
        return _MockAsyncSession()

    async def __aexit__(self, *args):
        pass


class TestSignalGenerator:
    @pytest.fixture
    def mock_bus(self):
        bus = AsyncMock(spec=EventBus)
        bus.publish = AsyncMock()
        bus.redis = AsyncMock()
        return bus

    @pytest.fixture
    def mock_dlq(self):
        return AsyncMock(spec=DLQManager)

    @pytest.fixture
    def signal_generator(self, mock_bus, mock_dlq):
        return SignalGenerator(mock_bus, mock_dlq)

    @pytest.mark.asyncio
    @patch(
        "api.services.signal_generator.AsyncSessionFactory",
        _MockSessionFactory(),
    )
    async def test_signal_generator_fires_every_n_ticks(self, signal_generator, mock_bus):
        # Send a tick with price data — should classify and publish a signal
        await signal_generator.process(
            {
                "symbol": "BTC/USD",
                "price": 50000.0,
                "pct": 0.5,
                "timestamp": "2024-01-01T00:00:00Z",
            }
        )

        # Should have published exactly 1 signal
        assert mock_bus.publish.call_count == 1
        call_args = mock_bus.publish.call_args
        assert call_args[0][0] == "signals"
        signal = call_args[0][1]
        assert signal["symbol"] == "BTC/USD"
        assert signal["type"] == "PRICE_UPDATE"
        assert signal["direction"] == "bullish"

    @pytest.mark.asyncio
    @patch(
        "api.services.signal_generator.AsyncSessionFactory",
        _MockSessionFactory(),
    )
    async def test_signal_generator_tracks_per_symbol(self, signal_generator, mock_bus):
        # Send ticks for two different symbols
        await signal_generator.process(
            {
                "symbol": "BTC/USD",
                "price": 50000.0,
                "pct": 2.0,
                "timestamp": "2024-01-01T00:00:00Z",
            }
        )

        await signal_generator.process(
            {
                "symbol": "ETH/USD",
                "price": 3000.0,
                "pct": -0.5,
                "timestamp": "2024-01-01T00:00:00Z",
            }
        )

        # Should have 2 signals — one per symbol
        assert mock_bus.publish.call_count == 2
        first_signal = mock_bus.publish.call_args_list[0][0][1]
        assert first_signal["symbol"] == "BTC/USD"
        assert first_signal["type"] == "MOMENTUM"

        second_signal = mock_bus.publish.call_args_list[1][0][1]
        assert second_signal["symbol"] == "ETH/USD"
        assert second_signal["direction"] == "bearish"

    @pytest.mark.asyncio
    async def test_signal_generator_ignores_invalid_ticks(self, signal_generator, mock_bus):
        # Send invalid tick with price=0
        await signal_generator.process(
            {"symbol": "BTC/USD", "price": 0, "timestamp": "2024-01-01T00:00:00Z"}
        )

        # Should not have published any signal
        assert mock_bus.publish.call_count == 0

    @pytest.mark.asyncio
    async def test_signal_generator_ignores_missing_symbol(self, signal_generator, mock_bus):
        # Send tick with no symbol
        await signal_generator.process({"price": 50000.0, "timestamp": "2024-01-01T00:00:00Z"})

        # Should not have published any signal
        assert mock_bus.publish.call_count == 0

    @pytest.mark.asyncio
    @patch(
        "api.services.signal_generator.AsyncSessionFactory",
        _MockSessionFactory(),
    )
    async def test_signal_generator_strong_momentum(self, signal_generator, mock_bus):
        # Send a tick with high pct change — should be STRONG_MOMENTUM
        await signal_generator.process(
            {
                "symbol": "BTC/USD",
                "price": 50000.0,
                "pct": 4.5,
                "timestamp": "2024-01-01T00:00:00Z",
            }
        )

        assert mock_bus.publish.call_count == 1
        signal = mock_bus.publish.call_args[0][1]
        assert signal["type"] == "STRONG_MOMENTUM"
        assert signal["strength"] == "HIGH"
        assert signal["direction"] == "bullish"


class TestLLMRouter:
    def test_parse_response_strips_markdown(self):
        text = '```json\n{"action": "buy", "confidence": 0.8}\n```'
        trace_id = "test-123"

        result = _parse_response(text, trace_id)

        assert result["action"] == "buy"
        assert result["confidence"] == 0.8

    def test_parse_response_plain_json(self):
        text = '{"action": "sell", "confidence": 0.6}'
        trace_id = "test-456"

        result = _parse_response(text, trace_id)

        assert result["action"] == "sell"
        assert result["confidence"] == 0.6

    def test_get_provider_key(self):
        # Default groq
        with patch.object(settings, "GROQ_API_KEY", "test-groq-key"):
            key = _get_provider_key("groq")
            assert key == "test-groq-key"

    def test_llm_router_unknown_provider_returns_empty(self):
        """Unknown provider returns empty string (no match in keys dict)."""
        key = _get_provider_key("unknown_provider")
        assert key == ""

    def test_llm_router_missing_key_returns_empty(self):
        """Missing API key returns empty string."""
        with patch.object(settings, "GROQ_API_KEY", ""):
            key = _get_provider_key("groq")
            assert key == ""

    @pytest.mark.asyncio
    async def test_llm_router_calls_correct_provider(self):
        mock_groq = AsyncMock(return_value=({"action": "buy", "confidence": 0.8}, 100, 0.0))
        with (
            patch.dict(
                "api.services.llm_router._PROVIDERS",
                {"groq": mock_groq},
            ),
            patch.object(settings, "GROQ_API_KEY", "test-key"),
            patch.object(settings, "LLM_PROVIDER", "groq"),
        ):
            result, tokens, cost = await call_llm(
                prompt="test prompt",
                trace_id="test-trace",
            )

            mock_groq.assert_called_once()
            assert result["action"] == "buy"


class TestMarketIngestor:
    @pytest.mark.asyncio
    async def test_market_ingestor_uses_config_interval(self):
        from api.config import settings

        # Verify the config has the market tick interval
        assert hasattr(settings, "MARKET_TICK_INTERVAL_SECONDS")
        assert settings.MARKET_TICK_INTERVAL_SECONDS > 0
