"""Deterministic risk engine — the final authority before execution.

No LLM. Takes the instruct decision, the optional reasoning review, and the
full deterministic state, then approves or blocks. Defaults fail safe:
unknown state, missing critical field, ledger/broker uncertainty → reject.

A model can recommend; only this engine (and the sizing engine after it) can
clear a trade for execution.
"""

from __future__ import annotations

from api.constants import BlockReason, PositionSide, ReviewResult
from api.services.hybrid.config import HybridConfig
from api.services.hybrid.models import (
    BrokerState,
    InstructDecision,
    PortfolioState,
    PositionState,
    ReasoningReview,
    RiskDecision,
    TradeAction,
)


def _is_risk_reducing(action: TradeAction, position: PositionState) -> bool:
    """True when the action closes/reduces existing exposure."""
    if action == "sell" and position.side is PositionSide.LONG and position.qty > 0:
        return True
    if action == "buy" and position.side is PositionSide.SHORT and position.qty > 0:
        return True
    return False


def _hold(symbol: str, reason: BlockReason | None, note: str) -> RiskDecision:
    return RiskDecision(
        approved=False,
        decision="hold",
        symbol=symbol,
        block_reason=reason,
        notes=[note],
    )


def evaluate_risk(
    *,
    instruct: InstructDecision,
    review: ReasoningReview | None,
    portfolio: PortfolioState,
    position: PositionState,
    broker: BrokerState,
    config: HybridConfig,
    current_price: float,
    instruct_valid: bool = True,
    duplicate_signal: bool = False,
    idempotency_reused: bool = False,
) -> RiskDecision:
    """Return the deterministic :class:`RiskDecision`."""
    symbol = instruct.symbol

    # Invalid model output never trades.
    if not instruct_valid:
        return _hold(symbol, BlockReason.MODEL_OUTPUT_INVALID, "model output invalid")

    # ----- Apply reasoning-review override (it can only restrict) -----
    action: TradeAction = instruct.action
    size_multiplier = 1.0
    notes: list[str] = []
    effective_confidence = instruct.confidence

    if review is not None:
        effective_confidence = min(effective_confidence, review.confidence)
        if review.review_result is ReviewResult.DOWNGRADE_TO_HOLD:
            return _hold(symbol, BlockReason.REASONING_DOWNGRADE, "reasoning downgraded to hold")
        if review.review_result is ReviewResult.EXIT_POSITION:
            if position.side is PositionSide.LONG and position.qty > 0:
                action = "sell"
            elif position.side is PositionSide.SHORT and position.qty > 0:
                action = "buy"
            else:
                return _hold(symbol, None, "exit recommended but no open position")
            notes.append("reasoning_exit_position")
        else:
            action = review.final_model_action
            if review.review_result is ReviewResult.REDUCE_ONLY:
                size_multiplier = min(1.0, review.recommended_size_multiplier)
                notes.append("reasoning_reduce_only")
            else:
                size_multiplier = max(0.0, review.recommended_size_multiplier or 1.0)

    # Hold is a valid no-trade outcome, not a block.
    if action == "hold":
        return RiskDecision(
            approved=False, decision="hold", symbol=symbol, size_multiplier=0.0, notes=notes
        )

    risk_reducing = _is_risk_reducing(action, position)

    # ----- Hard availability / integrity blocks (apply to every trade) -----
    if portfolio.kill_switch_active:
        return _hold(symbol, BlockReason.KILL_SWITCH_ACTIVE, "kill switch active")
    if not broker.available:
        return _hold(symbol, BlockReason.BROKER_UNAVAILABLE, "broker unavailable")
    if not portfolio.complete:
        return _hold(symbol, BlockReason.PORTFOLIO_INCOMPLETE, "portfolio state incomplete")
    if not portfolio.ledger_complete:
        return _hold(symbol, BlockReason.LEDGER_UNCERTAIN, "ledger state uncertain")
    if idempotency_reused:
        return _hold(symbol, BlockReason.IDEMPOTENCY_REUSED, "idempotency key already used")
    if duplicate_signal:
        return _hold(symbol, BlockReason.DUPLICATE_SIGNAL, "duplicate signal")
    if broker.open_order_exists:
        return _hold(symbol, BlockReason.OPEN_ORDER_EXISTS, "open order already exists")

    # ----- Confidence (risk-reducing exits are exempt) -----
    if not risk_reducing and effective_confidence < config.min_instruct_confidence:
        return _hold(
            symbol,
            BlockReason.LOW_CONFIDENCE,
            f"confidence {effective_confidence:.2f} < {config.min_instruct_confidence:.2f}",
        )

    # ----- Drawdown halts new risk -----
    if not risk_reducing and portfolio.daily_drawdown_pct >= config.max_daily_drawdown_pct:
        return _hold(symbol, BlockReason.DAILY_LOSS_LIMIT, "daily drawdown limit reached")

    # ----- Position / direction rules -----
    opening_short = action == "sell" and not (
        position.side is PositionSide.LONG and position.qty > 0
    )
    if opening_short and not config.allow_shorting:
        return _hold(symbol, BlockReason.SHORTING_DISALLOWED, "shorting disabled")

    adding_to_long = action == "buy" and position.side is PositionSide.LONG and position.qty > 0
    if adding_to_long and not config.allow_averaging_down:
        return _hold(symbol, BlockReason.AVERAGING_DOWN_DISALLOWED, "averaging down disabled")
    if adding_to_long and config.one_open_position_per_symbol:
        return _hold(symbol, BlockReason.AVERAGING_DOWN_DISALLOWED, "one position per symbol")

    opening_new = not risk_reducing and not adding_to_long
    if (
        opening_new
        and not position.exists
        and portfolio.open_positions_count >= config.max_open_positions
    ):
        return _hold(symbol, BlockReason.MAX_OPEN_POSITIONS, "max open positions reached")

    # ----- Stop / take-profit / reward-risk for new entries -----
    entry = instruct.suggested_entry if instruct.suggested_entry else current_price
    stop = instruct.suggested_stop_loss
    take = instruct.suggested_take_profit

    if opening_new:
        if config.require_stop_loss and (stop is None or stop <= 0):
            return _hold(symbol, BlockReason.MISSING_STOP_LOSS, "missing stop loss for entry")
        if config.require_take_profit and (take is None or take <= 0):
            return _hold(symbol, BlockReason.MISSING_TAKE_PROFIT, "missing take profit for entry")

        rr = _reward_risk(entry, stop, take, instruct.reward_risk_ratio, action)
        if rr is not None and rr < config.min_reward_risk:
            return _hold(
                symbol,
                BlockReason.REWARD_RISK_TOO_LOW,
                f"reward/risk {rr:.2f} < {config.min_reward_risk:.2f}",
            )

        # Symbol-exposure: an entry must not push exposure past the cap.
        if portfolio.equity > 0:
            existing_notional = position.qty * (position.entry_price or current_price)
            cap = config.max_symbol_exposure_pct * portfolio.equity
            if existing_notional >= cap:
                return _hold(symbol, BlockReason.MAX_SYMBOL_EXPOSURE, "symbol exposure cap reached")

    return RiskDecision(
        approved=True,
        decision=action,
        symbol=symbol,
        block_reason=None,
        approved_entry=entry,
        approved_stop_loss=stop,
        approved_take_profit=take,
        size_multiplier=size_multiplier,
        required_execution_checks=[
            "recheck_idempotency",
            "recheck_broker",
            "recheck_buying_power",
            "recheck_open_orders",
            "recheck_price",
            "recheck_market_state",
        ],
        notes=notes,
    )


def _reward_risk(
    entry: float | None,
    stop: float | None,
    take: float | None,
    fallback: float | None,
    action: TradeAction,
) -> float | None:
    """Compute reward/risk from levels; fall back to the model's own number."""
    if entry and stop and take and entry > 0:
        if action == "buy":
            risk = entry - stop
            reward = take - entry
        else:  # short entry
            risk = stop - entry
            reward = entry - take
        if risk > 0:
            return reward / risk
    return fallback
