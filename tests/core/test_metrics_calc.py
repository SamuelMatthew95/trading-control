"""Invariants for the canonical win-rate / realized-PnL math (metrics_calc).

Locks in the single definition (win_rate = winning / (winning + losing), opens
and scratches excluded) and proves the three memory readers that used to
diverge — dashboard/pnl.py, MetricsAggregator._memory_pnl_metrics, and
InMemoryStore.paired_pnl_payload — now all agree on the same orders.
"""

from __future__ import annotations

from api.constants import FieldName
from api.runtime_state import get_runtime_store
from api.services.dashboard.pnl import _in_memory_pnl_payload
from api.services.metrics_aggregator import MetricsAggregator
from api.services.metrics_calc import (
    closed_trade_stats,
    realized_pnl_of,
    win_rate_from_counts,
)


def test_realized_pnl_of_treats_open_and_malformed_as_none():
    assert realized_pnl_of({FieldName.PNL: None}) is None
    assert realized_pnl_of({FieldName.PNL: ""}) is None  # EventBus serialises None -> ""
    assert realized_pnl_of({FieldName.PNL: "n/a"}) is None
    assert realized_pnl_of({}) is None
    assert realized_pnl_of({FieldName.PNL: 0}) == 0.0
    assert realized_pnl_of({FieldName.PNL: "12.5"}) == 12.5


def test_win_rate_from_counts_excludes_empty():
    assert win_rate_from_counts(0, 0) == 0.0
    assert win_rate_from_counts(2, 1) == 2 / 3
    assert win_rate_from_counts(3, 0) == 1.0


def test_closed_trade_stats_excludes_opens_and_scratches():
    orders = [
        {FieldName.PNL: 10.0},  # win
        {FieldName.PNL: 5.0},  # win
        {FieldName.PNL: -3.0},  # loss
        {FieldName.PNL: 0.0},  # scratch — excluded from denominator
        {FieldName.PNL: None},  # open — excluded from denominator
    ]
    stats = closed_trade_stats(orders)
    assert stats.winning == 2
    assert stats.losing == 1
    assert stats.closed == 3  # NOT 5 — opens and scratches excluded
    assert stats.win_rate == 2 / 3
    assert stats.realized_pnl == 12.0  # 10 + 5 - 3 + 0
    assert stats.best == 10.0
    assert stats.worst == -3.0


def test_empty_orders_give_zero_stats():
    stats = closed_trade_stats([])
    assert stats == (0.0, 0, 0, 0, 0.0, 0.0, 0.0)


def test_three_memory_readers_agree_on_win_rate():
    """The invariant: given identical orders, dashboard PnL, the metrics
    aggregator, and the paired-PnL payload report the SAME win rate — and it
    is the closed-only rate (2/3), never the diluted len(orders) rate (2/5)."""
    store = get_runtime_store()
    for pnl in (10.0, 5.0, -3.0, 0.0, None):
        store.add_order({FieldName.PNL: pnl})

    dashboard_ratio = _in_memory_pnl_payload()["win_rate"]
    metrics_pct = MetricsAggregator(None, use_memory_store=True)._memory_pnl_metrics()[
        FieldName.WIN_RATE_PERCENT
    ]
    paired_pct = store.paired_pnl_payload()[FieldName.SUMMARY][FieldName.WIN_RATE_PERCENT]

    # closed-only definition: 2 winners / (2 winners + 1 loser) = 0.6667
    assert dashboard_ratio == round(2 / 3, 4)
    assert dashboard_ratio != round(2 / 5, 4)  # the old diluted (len(orders)) value
    assert metrics_pct == round(2 / 3 * 100, 2)
    assert paired_pct == round(2 / 3 * 100, 2)
    assert dashboard_ratio * 100 == metrics_pct == paired_pct


def test_realized_pnl_agrees_across_readers():
    store = get_runtime_store()
    for pnl in (10.0, 5.0, -3.0, None):
        store.add_order({FieldName.PNL: pnl})
    dashboard_total = _in_memory_pnl_payload()[FieldName.TOTAL_PNL]
    metrics_total = MetricsAggregator(None, use_memory_store=True)._memory_pnl_metrics()[
        FieldName.TOTAL_PNL
    ]
    assert dashboard_total == metrics_total == 12.0
