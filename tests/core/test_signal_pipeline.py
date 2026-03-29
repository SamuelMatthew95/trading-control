"""Tests for signal pipeline components."""

from unittest.mock import AsyncMock, patch

import pytest

from api.config import settings
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.services.llm_router import _get_provider_key, _parse_response, call_llm
from api.services.signal_generator import SignalGenerator


class TestSignalGenerator:
    @pytest.fixture
    def mock_bus(self):
        bus = AsyncMock(spec=EventBus)
        bus.publish = AsyncMock()
        return bus

    @pytest.fixture
    def mock_dlq(self):
        return AsyncMock(spec=DLQManager)

    @pytest.fixture
    def signal_generator(self, mock_bus, mock_dlq):
        return SignalGenerator(mock_bus, mock_dlq)

    @pytest.mark.asyncio
    async def test_signal_generator_fires_every_n_ticks(self, signal_generator, mock_bus):
        # Send 10 ticks for one symbol, should fire exactly 1 signal
        for i in range(10):
            await signal_generator.process({
                "symbol": "BTC/USD",
                "price": 50000.0 + i,
                "timestamp": "2024-01-01T00:00:00Z"
            })

        # Should have published exactly 1 signal
        assert mock_bus.publish.call_count == 1
        call_args = mock_bus.publish.call_args
        assert call_args[0][0] == "signals"
        signal = call_args[0][1]
        assert signal["symbol"] == "BTC/USD"
        assert signal["action"] == "hold"
        assert signal["signal_type"] == "periodic"

    @pytest.mark.asyncio
    async def test_signal_generator_tracks_per_symbol(self, signal_generator, mock_bus):
        # Send 10 ticks for symbol A and 5 for symbol B
        for i in range(10):
            await signal_generator.process({
                "symbol": "BTC/USD",
                "price": 50000.0 + i,
                "timestamp": "2024-01-01T00:00:00Z"
            })

        for i in range(5):
            await signal_generator.process({
                "symbol": "ETH/USD",
                "price": 3000.0 + i,
                "timestamp": "2024-01-01T00:00:00Z"
            })

        # Should have 1 signal for A, 0 for B
        assert mock_bus.publish.call_count == 1
        signal = mock_bus.publish.call_args[0][1]
        assert signal["symbol"] == "BTC/USD"

    @pytest.mark.asyncio
    async def test_signal_generator_ignores_invalid_ticks(self, signal_generator, mock_bus):
        # Send invalid tick with price=0
        await signal_generator.process({
            "symbol": "BTC/USD",
            "price": 0,
            "timestamp": "2024-01-01T00:00:00Z"
        })

        # Should not have published any signal
        assert mock_bus.publish.call_count == 0

    @pytest.mark.asyncio
    async def test_signal_generator_ignores_missing_symbol(self, signal_generator, mock_bus):
        # Send tick with no symbol
        await signal_generator.process({
            "price": 50000.0,
            "timestamp": "2024-01-01T00:00:00Z"
        })

        # Should not have published any signal
        assert mock_bus.publish.call_count == 0


class TestLLMRouter:
    def test_parse_response_strips_markdown(self):
        text = "```json\n{\"action\": \"buy\", \"confidence\": 0.8}\n```"
        trace_id = "test-123"

        result = _parse_response(text, trace_id)

        assert result["action"] == "buy"
        assert result["confidence"] == 0.8
        assert result["trace_id"] == trace_id
        assert result["fallback"] is False

    def test_parse_response_plain_json(self):
        text = "{\"action\": \"sell\", \"confidence\": 0.9}"
        trace_id = "test-456"

        result = _parse_response(text, trace_id, cost_usd=0.001)

        assert result["action"] == "sell"
        assert result["confidence"] == 0.9
        assert result["trace_id"] == trace_id
        assert result["cost_usd"] == 0.001

    def test_get_provider_key(self):
        # Test existing provider
        key = _get_provider_key("groq")
        assert key == settings.GROQ_API_KEY

        # Test non-existent provider
        key = _get_provider_key("nonexistent")
        assert key == ""

    @pytest.mark.asyncio
    async def test_llm_router_unknown_provider_raises(self):
        with patch.dict(settings.__dict__, {"LLM_PROVIDER": "invalid"}):
            with pytest.raises(RuntimeError) as exc_info:
                await call_llm("test prompt", "test-trace")

            assert "unknown_provider" in str(exc_info.value)
            assert "invalid" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_llm_router_missing_key_raises(self):
        with patch.dict(settings.__dict__, {
            "LLM_PROVIDER": "groq",
            "GROQ_API_KEY": ""
        }):
            with pytest.raises(RuntimeError) as exc_info:
                await call_llm("test prompt", "test-trace")

            assert "missing_api_key" in str(exc_info.value)
            assert "GROQ_API_KEY" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_llm_router_calls_correct_provider(self):
        mock_call_groq = AsyncMock(return_value=({"action": "buy"}, 100, 0.0))

        with patch.dict(settings.__dict__, {
            "LLM_PROVIDER": "groq",
            "GROQ_API_KEY": "test-key"
        }):
            # Patch the _PROVIDERS dict to avoid groq import
            with patch('api.services.llm_router._PROVIDERS', {'groq': mock_call_groq}):
                await call_llm("test prompt", "test-trace")

        mock_call_groq.assert_called_once_with("test prompt", "test-trace")


class TestMarketIngestor:
    def test_market_ingestor_uses_config_interval(self):
        from api.events.bus import EventBus
        from api.services.market_ingestor import MarketIngestor

        mock_bus = AsyncMock(spec=EventBus)
        ingestor = MarketIngestor(mock_bus)

        assert ingestor.interval == settings.MARKET_TICK_INTERVAL_SECONDS
