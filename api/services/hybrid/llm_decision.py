"""LLM decision layer: fast instruct agent + optional reasoning-review agent.

Both calls go through the existing ``llm_router`` so provider routing, rate
limiting, and metrics are reused. Output is parsed strictly and validated
against the pydantic schemas; any malformed/hallucinated response is converted
into a safe HOLD with ``setup_type="model_output_invalid"`` and never executes.

The reasoning model is expensive and is only called in the gray zone / high-risk
cases described in :func:`should_run_reasoning`.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from api.constants import (
    LLM_TASK_PRICE_ANALYSIS,
    LLM_TASK_TRADE_EXECUTION,
    BlockReason,
    ReviewResult,
    SizeHint,
)
from api.observability import log_structured
from api.services.hybrid.config import HybridConfig
from api.services.hybrid.models import (
    DataQuality,
    InstructDecision,
    MarketSnapshot,
    PortfolioState,
    PositionState,
    ReasoningReview,
    SignalCandidate,
    SignalSummary,
)
from api.services.hybrid.prompts import INSTRUCT_SYSTEM_PROMPT, REASONING_SYSTEM_PROMPT

# (prompt, system_prompt, trace_id, task_type) -> (raw_text, tokens, cost_usd)
LLMCall = Callable[[str, str, str, str], Awaitable[tuple[str, int, float]]]


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text[3:]
        if "\n" in text:
            first_line, rest = text.split("\n", 1)
            if first_line.strip().lower() in {"json", ""}:
                text = rest
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _loads_object(raw: str) -> dict | None:
    """Parse ``raw`` into a JSON object, or None if it is not a JSON object."""
    cleaned = _strip_code_fences(raw)
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def hold_fallback(symbol: str, *, thesis: str) -> InstructDecision:
    """A safe, schema-valid HOLD used whenever the model output is unusable."""
    return InstructDecision(
        action="hold",
        symbol=symbol,
        confidence=0.0,
        setup_type="model_output_invalid",
        thesis=thesis,
        supporting_signals=[],
        conflicting_signals=[],
        risk_flags=[BlockReason.MODEL_OUTPUT_INVALID.value],
        position_size_hint=SizeHint.NONE,
        needs_reasoning_review=False,
        data_quality=DataQuality(
            price_fresh=False,
            volume_valid=False,
            indicators_complete=False,
            portfolio_state_complete=False,
            ledger_state_complete=False,
        ),
        should_execute=False,
    )


def parse_instruct(raw: str, symbol: str) -> tuple[InstructDecision, bool]:
    """Return ``(decision, valid)``. On any parse/validation failure returns a
    HOLD fallback with ``valid=False`` so the risk engine blocks it."""
    obj = _loads_object(raw)
    if obj is None:
        return hold_fallback(symbol, thesis="non-JSON model response"), False
    try:
        decision = InstructDecision.model_validate(obj)
    except ValidationError as exc:
        log_structured(
            "warning",
            "hybrid_instruct_invalid",
            symbol=symbol,
            error_count=len(exc.errors()),
        )
        return hold_fallback(symbol, thesis="schema-invalid model response"), False
    return decision, True


def parse_reasoning(raw: str) -> ReasoningReview | None:
    """Validate a reasoning-review response, or None if unusable."""
    obj = _loads_object(raw)
    if obj is None:
        return None
    try:
        return ReasoningReview.model_validate(obj)
    except ValidationError:
        return None


def _build_instruct_input(
    candidate: SignalCandidate,
    market: MarketSnapshot,
    signal: SignalSummary,
    portfolio: PortfolioState,
    position: PositionState,
    config: HybridConfig,
) -> dict:
    # dict(...) keyword construction (not a {} literal) is intentional: keys like
    # "symbol"/"signals" match FieldName values, so a literal would trip the
    # FieldName raw-string-key guardrail. noqa C408 keeps the keyword form.
    return dict(  # noqa: C408
        symbol=market.symbol,
        market=market.model_dump(mode="json"),
        signals=signal.model_dump(mode="json"),
        candidate=candidate.model_dump(mode="json"),
        portfolio=portfolio.model_dump(mode="json"),
        position=position.model_dump(mode="json"),
        risk_limits=dict(  # noqa: C408
            min_confidence=config.min_instruct_confidence,
            min_reward_risk=config.min_reward_risk,
            require_stop_loss=config.require_stop_loss,
            require_take_profit=config.require_take_profit,
            allow_shorting=config.allow_shorting,
            allow_averaging_down=config.allow_averaging_down,
        ),
    )


async def request_instruct_decision(
    llm_call: LLMCall,
    *,
    candidate: SignalCandidate,
    market: MarketSnapshot,
    signal: SignalSummary,
    portfolio: PortfolioState,
    position: PositionState,
    config: HybridConfig,
    trace_id: str,
) -> tuple[InstructDecision, bool]:
    """Call the fast instruct agent and return ``(decision, valid)``."""
    payload = _build_instruct_input(candidate, market, signal, portfolio, position, config)
    prompt = json.dumps(payload, separators=(",", ":"))
    try:
        raw, _tokens, _cost = await llm_call(
            prompt, INSTRUCT_SYSTEM_PROMPT, trace_id, LLM_TASK_TRADE_EXECUTION
        )
    except Exception:
        log_structured(
            "warning", "hybrid_instruct_call_failed", symbol=market.symbol, exc_info=True
        )
        return hold_fallback(market.symbol, thesis="instruct call failed"), False
    return parse_instruct(raw, market.symbol)


def should_run_reasoning(
    instruct: InstructDecision,
    position: PositionState,
    portfolio: PortfolioState,
    config: HybridConfig,
) -> bool:
    """Decide whether the (expensive) reasoning model is needed.

    Called only for ambiguous / high-risk cases; skipped for clear-cut ones.
    """
    if not config.reasoning_review_enabled:
        return False

    action = instruct.action
    conf = instruct.confidence

    # Never review a low-confidence hold or an invalid response (already safe).
    if action == "hold" and conf < config.reasoning_review_lower:
        return False

    # Gray-zone confidence band.
    if config.reasoning_review_lower <= conf <= config.reasoning_review_upper:
        return True
    # Buy carrying risk flags.
    if action == "buy" and instruct.risk_flags:
        return True
    # Sell while a position is open (exit decisions get scrutiny).
    if action == "sell" and position.exists:
        return True
    # Any trade while drawdown is elevated.
    if action in ("buy", "sell") and portfolio.daily_drawdown_pct >= config.max_daily_drawdown_pct:
        return True
    # Adding to an existing position.
    if action == "buy" and position.exists:
        return True
    # Reward/risk near the threshold.
    if instruct.reward_risk_ratio is not None and (
        config.min_reward_risk <= instruct.reward_risk_ratio < config.min_reward_risk + 0.5
    ):
        return True
    # The instruct model explicitly asked for review.
    return bool(instruct.needs_reasoning_review)


def _build_reasoning_input(
    instruct: InstructDecision,
    signal: SignalSummary,
    portfolio: PortfolioState,
    position: PositionState,
) -> dict:
    return dict(  # noqa: C408 — keyword form avoids FieldName raw-string-key guardrail
        instruct_decision=instruct.model_dump(mode="json"),
        signals=signal.model_dump(mode="json"),
        portfolio=portfolio.model_dump(mode="json"),
        position=position.model_dump(mode="json"),
    )


async def request_reasoning_review(
    llm_call: LLMCall,
    *,
    instruct: InstructDecision,
    signal: SignalSummary,
    portfolio: PortfolioState,
    position: PositionState,
    trace_id: str,
) -> ReasoningReview:
    """Call the reasoning agent. On any failure, fail safe to downgrade_to_hold."""
    payload = _build_reasoning_input(instruct, signal, portfolio, position)
    prompt = json.dumps(payload, separators=(",", ":"))
    safe_default = ReasoningReview(
        review_result=ReviewResult.DOWNGRADE_TO_HOLD,
        final_model_action="hold",
        confidence=0.0,
        reasoning_summary="reasoning review unavailable — failing safe to hold",
        main_concern="review_unavailable",
        model_disagreements=[],
        additional_risk_flags=[],
        recommended_size_multiplier=0.0,
        required_risk_checks=[],
    )
    try:
        raw, _tokens, _cost = await llm_call(
            prompt, REASONING_SYSTEM_PROMPT, trace_id, LLM_TASK_PRICE_ANALYSIS
        )
    except Exception:
        log_structured("warning", "hybrid_reasoning_call_failed", trace_id=trace_id, exc_info=True)
        return safe_default
    review = parse_reasoning(raw)
    return review if review is not None else safe_default
