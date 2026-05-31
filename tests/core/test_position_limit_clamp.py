"""Pre-trade BUY position-cap clamp (Gap A).

A BUY can never push the resulting long position past the per-symbol exposure
cap, no matter how large the (possibly hallucinated) order qty is. This mirrors
the oversell clamp for SELL.

Regression for: normal Kelly-sized BUYs had no pre-trade size bound — only
*fallback* signals were capped — so a runaway/oversized SIZE_PCT could open an
unbounded long position straight at the broker.
"""

from __future__ import annotations

from api.constants import FieldName, PositionSide
from api.services.execution.position_math import (
    clamp_buy_to_position_limit,
    signed_position_qty,
)

MAX = 1.0


def _long(qty: float) -> dict:
    return {FieldName.SIDE: PositionSide.LONG, FieldName.QTY: qty}


def _short(qty: float) -> dict:
    return {FieldName.SIDE: PositionSide.SHORT, FieldName.QTY: qty}


def test_huge_buy_from_flat_is_clamped_to_cap():
    # The headline case: a hallucinated/oversized qty is bounded to the cap.
    assert clamp_buy_to_position_limit(None, 999.0, MAX) == MAX


def test_buy_within_cap_passes_through_unchanged():
    assert clamp_buy_to_position_limit(None, 0.4, MAX) == 0.4


def test_buy_clamped_to_remaining_room_on_existing_long():
    # Already long 0.6; only 0.4 of room remains under a 1.0 cap.
    assert clamp_buy_to_position_limit(_long(0.6), 5.0, MAX) == 0.4


def test_buy_rejected_when_position_already_at_cap():
    # room == 0 → 0.0 signals the caller to reject the order.
    assert clamp_buy_to_position_limit(_long(MAX), 1.0, MAX) == 0.0


def test_buy_rejected_when_position_over_cap():
    assert clamp_buy_to_position_limit(_long(1.5), 1.0, MAX) == 0.0


def test_short_cover_then_flip_is_bounded_to_cap():
    # Short 0.5: a buy may cover the short AND open a long up to the cap,
    # i.e. up to 0.5 (cover) + 1.0 (max long) = 1.5 total.
    assert clamp_buy_to_position_limit(_short(0.5), 999.0, MAX) == 1.5


def test_signed_position_qty_sign_and_flat():
    assert signed_position_qty(_long(0.3)) == 0.3
    assert signed_position_qty(_short(0.3)) == -0.3
    assert signed_position_qty(None) == 0.0
    assert signed_position_qty({}) == 0.0
