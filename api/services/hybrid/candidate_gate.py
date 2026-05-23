"""Deterministic signal-candidate gate — the second pre-LLM gate.

Turns a :class:`SignalSummary` into a :class:`SignalCandidate` and decides
whether the (paid) LLM should be called at all. Weak signals, incomplete
indicators, or a neutral direction never reach the model — the pipeline holds.
"""

from __future__ import annotations

from api.constants import BlockReason, MarketDirection
from api.services.hybrid.config import HybridConfig
from api.services.hybrid.models import SignalCandidate, SignalSummary


def build_candidate(summary: SignalSummary, config: HybridConfig) -> SignalCandidate:
    """Build the candidate gate decision for ``summary``."""
    why: list[str] = []
    why_not: list[str] = []

    if not summary.indicators_complete:
        why_not.append(f"indicators_incomplete:{','.join(summary.missing_indicators)}")
        return SignalCandidate(
            symbol=summary.symbol,
            candidate=False,
            candidate_type="none",
            direction="none",
            strength=0.0,
            why=why,
            why_not=why_not,
            send_to_model=False,
            block_reason=BlockReason.INDICATORS_INCOMPLETE,
        )

    direction = _candidate_direction(summary.raw_direction)
    if direction == "none":
        why_not.append("no_directional_bias")
        return SignalCandidate(
            symbol=summary.symbol,
            candidate=False,
            candidate_type="none",
            direction="none",
            strength=summary.confidence_seed,
            why=why,
            why_not=why_not,
            send_to_model=False,
            block_reason=BlockReason.NO_DIRECTION,
        )

    # Collect supporting / detracting evidence (deterministic, explainable).
    if summary.price_above_vwap:
        why.append("price_above_vwap")
    if summary.ema_9_above_ema_20:
        why.append("ema_alignment_bullish")
    if summary.macd_bias is MarketDirection.BULLISH:
        why.append("macd_bullish")
    if summary.volume_valid:
        why.append("relative_volume_valid")
    if summary.near_resistance:
        why_not.append("near_resistance")
    if summary.near_support and direction == "short":
        why_not.append("near_support")
    if summary.volatility_risk >= 0.7:
        why_not.append("high_volatility")

    strength = summary.confidence_seed
    if strength < config.min_signal_score:
        why_not.append(f"strength_below_min:{strength:.2f}<{config.min_signal_score:.2f}")
        return SignalCandidate(
            symbol=summary.symbol,
            candidate=False,
            candidate_type=summary.setup_type,
            direction=direction,
            strength=strength,
            why=why,
            why_not=why_not,
            send_to_model=False,
            block_reason=BlockReason.WEAK_SIGNAL,
        )

    return SignalCandidate(
        symbol=summary.symbol,
        candidate=True,
        candidate_type=f"{direction}_{summary.setup_type}",
        direction=direction,
        strength=strength,
        why=why,
        why_not=why_not,
        send_to_model=True,
        block_reason=None,
    )


def _candidate_direction(direction: MarketDirection) -> str:
    if direction is MarketDirection.BULLISH:
        return "long"
    if direction is MarketDirection.BEARISH:
        return "short"
    return "none"
