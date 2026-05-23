"""Tunable thresholds for the hybrid pipeline, bundled into one immutable object.

Defaults come from ``api.config.settings`` (env-overridable) and fail safe:
weak signals, low confidence, missing stops, thin reward/risk, and any
uncertainty all resolve to HOLD/BLOCK. This is a dedicated single-purpose
config module, so it owns these values rather than scattering them across the
pipeline stages.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.config import settings


@dataclass(frozen=True)
class HybridConfig:
    # Candidate gate
    min_signal_score: float = 0.65
    # Instruct confidence
    min_instruct_confidence: float = 0.70
    # Reasoning-review gray zone
    reasoning_review_lower: float = 0.55
    reasoning_review_upper: float = 0.80
    reasoning_review_enabled: bool = True
    # Reward / risk
    min_reward_risk: float = 2.0
    # Sizing / exposure
    max_risk_per_trade_pct: float = 0.005
    max_daily_drawdown_pct: float = 0.02
    max_symbol_exposure_pct: float = 0.10
    max_open_positions: int = 5
    # Market validation
    max_spread_bps: float = 50.0
    price_max_staleness_seconds: float = 30.0
    min_relative_volume: float = 0.5
    # Behavioural switches
    allow_shorting: bool = False
    allow_averaging_down: bool = False
    require_stop_loss: bool = True
    require_take_profit: bool = True
    one_open_position_per_symbol: bool = True

    @classmethod
    def from_settings(cls) -> HybridConfig:
        """Build a config from environment-backed settings."""
        return cls(
            min_signal_score=settings.HYBRID_MIN_SIGNAL_SCORE,
            min_instruct_confidence=settings.HYBRID_MIN_INSTRUCT_CONFIDENCE,
            reasoning_review_lower=settings.HYBRID_REASONING_REVIEW_LOWER,
            reasoning_review_upper=settings.HYBRID_REASONING_REVIEW_UPPER,
            reasoning_review_enabled=settings.HYBRID_REASONING_REVIEW_ENABLED,
            min_reward_risk=settings.HYBRID_MIN_REWARD_RISK,
            max_risk_per_trade_pct=settings.HYBRID_MAX_RISK_PER_TRADE_PCT,
            max_daily_drawdown_pct=settings.HYBRID_MAX_DAILY_DRAWDOWN_PCT,
            max_symbol_exposure_pct=settings.HYBRID_MAX_SYMBOL_EXPOSURE_PCT,
            max_open_positions=settings.HYBRID_MAX_OPEN_POSITIONS,
            max_spread_bps=settings.HYBRID_MAX_SPREAD_BPS,
            price_max_staleness_seconds=settings.HYBRID_PRICE_MAX_STALENESS_SECONDS,
            min_relative_volume=settings.HYBRID_MIN_RELATIVE_VOLUME,
            allow_shorting=settings.HYBRID_ALLOW_SHORTING,
            allow_averaging_down=settings.HYBRID_ALLOW_AVERAGING_DOWN,
            require_stop_loss=settings.HYBRID_REQUIRE_STOP_LOSS,
            require_take_profit=settings.HYBRID_REQUIRE_TAKE_PROFIT,
            one_open_position_per_symbol=settings.HYBRID_ONE_OPEN_POSITION_PER_SYMBOL,
        )
