"""Deterministic market validation — the first hard gate.

Runs before any LLM call. If any check fails the pipeline emits a
HOLD/BLOCKED decision with a precise :class:`BlockReason` and the model is
never invoked. Fails safe: missing freshness, missing price, or an
incomplete/invalid quote all block.
"""

from __future__ import annotations

from api.constants import BlockReason
from api.services.hybrid.config import HybridConfig
from api.services.hybrid.models import MarketSnapshot, MarketValidation


def validate_market(snapshot: MarketSnapshot, config: HybridConfig) -> MarketValidation:
    """Return a :class:`MarketValidation`; ``passed=False`` carries the reason."""
    missing: list[str] = []
    reasons: list[str] = []

    def block(reason: BlockReason, detail: str) -> MarketValidation:
        reasons.append(detail)
        return MarketValidation(
            passed=False, block_reason=reason, missing_fields=missing, reasons=reasons
        )

    if not snapshot.broker_available:
        return block(BlockReason.BROKER_UNAVAILABLE, "broker/feed unavailable")

    if snapshot.data_error:
        return block(BlockReason.DATA_INCOMPLETE, f"market data error: {snapshot.data_error}")

    if not snapshot.tradable:
        return block(BlockReason.SYMBOL_NOT_TRADABLE, f"{snapshot.symbol} not tradable")

    if not snapshot.market_open:
        return block(BlockReason.MARKET_CLOSED, "market closed")

    if snapshot.last_price is None or snapshot.last_price <= 0:
        missing.append("last_price")
        return block(BlockReason.PRICE_MISSING, "last price missing or non-positive")

    # Freshness: unknown age is treated as stale (no cached price pretending live).
    if snapshot.price_age_seconds is None:
        missing.append("price_age_seconds")
        return block(BlockReason.PRICE_STALE, "price age unknown — treated as stale")
    if snapshot.price_age_seconds > config.price_max_staleness_seconds:
        return block(
            BlockReason.PRICE_STALE,
            f"price {snapshot.price_age_seconds:.1f}s old > {config.price_max_staleness_seconds:.1f}s",
        )

    # Quote validation only when a quote is expected (either side present).
    has_bid = snapshot.bid is not None
    has_ask = snapshot.ask is not None
    if has_bid != has_ask:
        return block(BlockReason.INVALID_QUOTE, "incomplete bid/ask quote")
    if has_bid and has_ask:
        spread = snapshot.spread_bps
        if spread is None:
            return block(BlockReason.INVALID_QUOTE, "invalid bid/ask quote")
        if spread > config.max_spread_bps:
            return block(
                BlockReason.SPREAD_TOO_WIDE,
                f"spread {spread:.1f}bps > {config.max_spread_bps:.1f}bps",
            )

    # Volume validation.
    if snapshot.relative_volume is not None:
        if snapshot.relative_volume < config.min_relative_volume:
            return block(
                BlockReason.VOLUME_TOO_LOW,
                f"rel-volume {snapshot.relative_volume:.2f} < {config.min_relative_volume:.2f}",
            )
    elif snapshot.volume is None:
        missing.append("volume")
        return block(BlockReason.DATA_INCOMPLETE, "no volume data")

    return MarketValidation(passed=True, missing_fields=missing, reasons=["all checks passed"])
