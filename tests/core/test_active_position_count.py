"""Invariant: the active-position COUNT always equals the open-positions LIST.

Before this, open_positions() required side in {long, short} while
normalized_open_positions() required only abs(qty) > 0, so a position with
qty > 0 but a missing/other side counted in one path and not the other. The
canonical rule is abs(qty) > 0 (a flat position has qty 0, so side is
irrelevant).
"""

from __future__ import annotations

from api.constants import FieldName
from api.runtime_state import get_runtime_store
from api.services.dashboard.pnl import _in_memory_pnl_payload


def _seed_positions() -> None:
    store = get_runtime_store()
    store.positions["BTC/USD"] = {
        FieldName.SYMBOL: "BTC/USD",
        FieldName.QTY: 0.5,
        FieldName.SIDE: "long",
    }
    # qty > 0 but NO side — the case open_positions() used to silently drop.
    store.positions["ETH/USD"] = {FieldName.SYMBOL: "ETH/USD", FieldName.QTY: 2.0}
    # short — active (abs(qty) > 0).
    store.positions["AAPL"] = {
        FieldName.SYMBOL: "AAPL",
        FieldName.QTY: -3.0,
        FieldName.SIDE: "short",
    }
    # flat — qty 0, never active regardless of side.
    store.positions["SOL/USD"] = {
        FieldName.SYMBOL: "SOL/USD",
        FieldName.QTY: 0.0,
        FieldName.SIDE: "long",
    }


def test_count_equals_list_length_across_all_read_paths():
    _seed_positions()
    store = get_runtime_store()
    count = store.get_active_position_count()
    assert count == 3  # BTC, ETH (no side), AAPL — SOL is flat
    assert len(store.open_positions()) == count
    assert len(store.normalized_open_positions()) == count


def test_dashboard_active_positions_matches_canonical_count():
    _seed_positions()
    store = get_runtime_store()
    payload = _in_memory_pnl_payload()
    assert payload[FieldName.ACTIVE_POSITIONS] == store.get_active_position_count() == 3


def test_qty_with_missing_side_is_active():
    """The exact divergence case: qty > 0 with no side is active everywhere now."""
    store = get_runtime_store()
    store.positions["ETH/USD"] = {FieldName.SYMBOL: "ETH/USD", FieldName.QTY: 2.0}
    assert store.has_active_position("ETH/USD")
    assert len(store.open_positions()) == 1
    assert store.get_active_position_count() == 1


def test_flat_and_absent_are_not_active():
    store = get_runtime_store()
    store.positions["SOL/USD"] = {
        FieldName.SYMBOL: "SOL/USD",
        FieldName.QTY: 0.0,
        FieldName.SIDE: "long",
    }
    assert not store.has_active_position("SOL/USD")  # flat
    assert not store.has_active_position("DOGE/USD")  # absent
    assert store.get_active_position_count() == 0
