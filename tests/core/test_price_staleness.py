"""Regression tests for ``filter_fresh_prices`` — the price-freshness gate.

A cached price older than ``PRICE_STALE_SECONDS`` must never be served as a
live quote (poller stuck / Alpaca outage), so the dashboard shows "--" instead
of a frozen dead number. A price without a usable ``ts`` is kept (fail-open):
its age is already bounded by the cache TTL and dropping it would blank the
ticker on legacy writes.
"""

from __future__ import annotations

from api.constants import PRICE_STALE_SECONDS, FieldName
from api.services.metrics_aggregator import filter_fresh_prices

_NOW = 1_000_000.0


def test_drops_stale_keeps_fresh() -> None:
    prices = {
        "BTC/USD": {FieldName.PRICE: 64000, FieldName.TS: _NOW - 5},
        "ETH/USD": {FieldName.PRICE: 1600, FieldName.TS: _NOW - (PRICE_STALE_SECONDS + 10)},
    }
    fresh = filter_fresh_prices(prices, now_ts=_NOW)
    assert "BTC/USD" in fresh
    assert "ETH/USD" not in fresh


def test_threshold_boundary_is_inclusive() -> None:
    """A price exactly at the threshold age is still fresh (age <= bound)."""
    prices = {"BTC/USD": {FieldName.PRICE: 1, FieldName.TS: _NOW - PRICE_STALE_SECONDS}}
    assert "BTC/USD" in filter_fresh_prices(prices, now_ts=_NOW)


def test_missing_ts_is_kept_fail_open() -> None:
    prices = {"BTC/USD": {FieldName.PRICE: 64000}}
    assert "BTC/USD" in filter_fresh_prices(prices, now_ts=_NOW)


def test_unparseable_ts_is_kept_fail_open() -> None:
    prices = {"BTC/USD": {FieldName.PRICE: 1, FieldName.TS: "not-a-number"}}
    assert "BTC/USD" in filter_fresh_prices(prices, now_ts=_NOW)


def test_non_dict_payload_is_skipped() -> None:
    prices = {"BTC/USD": None, "ETH/USD": {FieldName.PRICE: 1, FieldName.TS: _NOW}}
    out = filter_fresh_prices(prices, now_ts=_NOW)
    assert "BTC/USD" not in out
    assert "ETH/USD" in out


def test_empty_input_returns_empty() -> None:
    assert filter_fresh_prices({}, now_ts=_NOW) == {}
