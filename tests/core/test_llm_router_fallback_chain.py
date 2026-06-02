"""Tests for cross-provider failover in api/services/llm_router.py.

Regression coverage for the bug where ``LLM_PROVIDER=groq`` would hard-fail
into ``reject_signal`` whenever Groq was throttled/erroring, even though a
healthy Gemini key was configured. The router now tries the configured
provider first and, on failure, fails over to any other keyed cloud provider
(``_cloud_fallback_chain``) so the reasoning brain stays online and the
learning loop keeps getting real decisions to grade.
"""

from __future__ import annotations

import pytest

import api.services.llm_router as router
from api.constants import FieldName


@pytest.fixture
def _two_cloud_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure groq as primary with both groq + gemini keys present."""
    monkeypatch.setattr(router.settings, "LLM_PROVIDER", "groq", raising=False)
    monkeypatch.setattr(router.settings, "LLM_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(router.settings, "LM_STUDIO_ENABLED", False, raising=False)
    monkeypatch.setattr(router.settings, "GROQ_API_KEY", "gsk_test", raising=False)
    monkeypatch.setattr(router.settings, "GEMINI_API_KEY", "gem_test", raising=False)
    monkeypatch.setattr(router.settings, "ANTHROPIC_API_KEY", "", raising=False)
    monkeypatch.setattr(router.settings, "OPENAI_API_KEY", "", raising=False)


# ---------------------------------------------------------------------------
# _cloud_fallback_chain
# ---------------------------------------------------------------------------


def test_chain_starts_with_primary(_two_cloud_keys: None) -> None:
    chain = router._cloud_fallback_chain("groq")
    assert chain[0] == "groq"


def test_chain_appends_other_keyed_providers(_two_cloud_keys: None) -> None:
    chain = router._cloud_fallback_chain("groq")
    assert chain == ["groq", "gemini"]


def test_chain_skips_providers_without_keys(_two_cloud_keys: None) -> None:
    chain = router._cloud_fallback_chain("groq")
    assert "anthropic" not in chain and "openai" not in chain


def test_chain_is_primary_only_when_fallback_disabled(
    _two_cloud_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(router.settings, "LLM_FALLBACK_ENABLED", False, raising=False)
    assert router._cloud_fallback_chain("groq") == ["groq"]


# ---------------------------------------------------------------------------
# call_llm failover
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_llm_fails_over_to_gemini_when_groq_throttled(
    _two_cloud_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def _groq(prompt: str, trace_id: str):
        calls.append("groq")
        raise RuntimeError("429 rate limit exceeded")

    async def _gemini(prompt: str, trace_id: str):
        calls.append("gemini")
        return ({FieldName.ACTION: "buy", FieldName.TRACE_ID: trace_id}, 10, 0.0)

    monkeypatch.setattr(router, "_PROVIDERS", {"groq": _groq, "gemini": _gemini})

    parsed, tokens, cost = await router.call_llm("prompt", "trace-1")

    assert calls == ["groq", "gemini"], "should try groq first, then fail over to gemini"
    assert parsed[FieldName.ACTION] == "buy"
    assert parsed[FieldName.PROVIDER] == "gemini", (
        "decision must be attributed to the real provider"
    )


@pytest.mark.asyncio
async def test_call_llm_raises_when_all_providers_fail(
    _two_cloud_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fail(prompt: str, trace_id: str):
        raise RuntimeError("provider down")

    monkeypatch.setattr(router, "_PROVIDERS", {"groq": _fail, "gemini": _fail})

    with pytest.raises(RuntimeError, match="provider down"):
        await router.call_llm("prompt", "trace-2")
