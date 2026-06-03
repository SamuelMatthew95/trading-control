"""Regression: the dashboard snapshot exposes daily_change_pct / daily_pnl.

Without these the overview "Daily Change %" tile is permanently "--" — the
backend emits no equity-base system metric, so the snapshot now provides
realized PnL as a percentage of starting paper capital.
"""

from __future__ import annotations

from api.constants import DEFAULT_PAPER_CASH, FieldName
from api.runtime_state import get_runtime_store


def test_snapshot_exposes_daily_change_pct():
    store = get_runtime_store()
    store.add_order({FieldName.PNL: 250.0})
    store.add_order({FieldName.PNL: -50.0})
    store.add_order({FieldName.PNL: None})  # open fill — excluded from realized
    snap = store.dashboard_fallback_snapshot()
    # realized = 250 - 50 = 200; daily_change = 200 / 100_000 * 100 = 0.2%
    assert snap[FieldName.DAILY_PNL] == 200.0
    assert snap[FieldName.DAILY_CHANGE_PCT] == round(200.0 / DEFAULT_PAPER_CASH * 100.0, 4)


def test_snapshot_daily_change_zero_when_no_trades():
    snap = get_runtime_store().dashboard_fallback_snapshot()
    assert snap[FieldName.DAILY_CHANGE_PCT] == 0.0
    assert snap[FieldName.DAILY_PNL] == 0.0
