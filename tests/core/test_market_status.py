"""Tests for the centralized MarketStatusService (api/services/market_status.py).

Every case injects a timezone-aware ``now`` in US/Eastern so the market clock is
fully deterministic — no system-clock freezing, no network, no calendar lib.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from api.constants import MarketState
from api.services.market_status import (
    MarketStatusService,
    early_close_days,
    get_market_status,
    market_holidays,
)

ET = ZoneInfo("America/New_York")


def _et(year, month, day, hour, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ET)


@pytest.fixture
def svc() -> MarketStatusService:
    return MarketStatusService()


# ---------------------------------------------------------------------------
# Regular session boundaries
# ---------------------------------------------------------------------------


def test_regular_weekday_midday_is_open(svc):
    # Tuesday 2025-06-10, 10:00 ET
    assert svc.state(_et(2025, 6, 10, 10)) is MarketState.OPEN
    assert svc.is_open(_et(2025, 6, 10, 10)) is True


def test_premarket_is_not_open(svc):
    assert svc.state(_et(2025, 6, 10, 8)) is MarketState.PREMARKET
    assert svc.is_open(_et(2025, 6, 10, 8)) is False


def test_after_hours_is_not_open(svc):
    assert svc.state(_et(2025, 6, 10, 17)) is MarketState.AFTER_HOURS
    assert svc.is_open(_et(2025, 6, 10, 17)) is False


def test_overnight_is_closed(svc):
    assert svc.state(_et(2025, 6, 10, 2)) is MarketState.CLOSED


def test_open_boundary_inclusive_at_930(svc):
    assert svc.state(_et(2025, 6, 10, 9, 30)) is MarketState.OPEN


def test_open_boundary_exclusive_at_1600(svc):
    # 16:00 sharp is no longer OPEN — it's after-hours.
    assert svc.state(_et(2025, 6, 10, 16, 0)) is MarketState.AFTER_HOURS


def test_just_before_close_still_open(svc):
    assert svc.state(_et(2025, 6, 10, 15, 59)) is MarketState.OPEN


# ---------------------------------------------------------------------------
# Weekends
# ---------------------------------------------------------------------------


def test_saturday_is_closed(svc):
    # 2025-06-14 is a Saturday
    assert svc.state(_et(2025, 6, 14, 11)) is MarketState.CLOSED


def test_sunday_is_closed(svc):
    assert svc.state(_et(2025, 6, 15, 11)) is MarketState.CLOSED


# ---------------------------------------------------------------------------
# Holidays
# ---------------------------------------------------------------------------


def test_new_years_day_is_holiday(svc):
    # 2025-01-01 is a Wednesday
    assert svc.state(_et(2025, 1, 1, 11)) is MarketState.HOLIDAY


def test_good_friday_2024_is_holiday(svc):
    # Good Friday 2024 = 2024-03-29 (Easter Sunday was 2024-03-31)
    assert svc.state(_et(2024, 3, 29, 11)) is MarketState.HOLIDAY


def test_thanksgiving_2024_is_holiday(svc):
    # 4th Thursday of Nov 2024 = 2024-11-28
    assert svc.state(_et(2024, 11, 28, 11)) is MarketState.HOLIDAY


def test_christmas_observed_when_on_sunday(svc):
    # 2022-12-25 is a Sunday → observed Monday 2022-12-26
    assert _et(2022, 12, 26, 11).date() in market_holidays(2022)
    assert svc.state(_et(2022, 12, 26, 11)) is MarketState.HOLIDAY


def test_juneteenth_is_holiday_from_2022(svc):
    # 2025-06-19 is a Thursday
    assert svc.state(_et(2025, 6, 19, 11)) is MarketState.HOLIDAY


def test_juneteenth_absent_before_2022(svc):
    # 2021-06-18 (Fri) was a normal trading day — Juneteenth not yet an NYSE holiday
    assert svc.state(_et(2021, 6, 18, 11)) is MarketState.OPEN


# ---------------------------------------------------------------------------
# Early closes (13:00 ET half-days)
# ---------------------------------------------------------------------------


def test_day_after_thanksgiving_is_early_close(svc):
    # 2024-11-29 (Fri) — open before 13:00, after-hours past it
    assert svc.state(_et(2024, 11, 29, 12)) is MarketState.OPEN
    assert svc.state(_et(2024, 11, 29, 14)) is MarketState.AFTER_HOURS
    assert _et(2024, 11, 29, 12).date() in early_close_days(2024)


# ---------------------------------------------------------------------------
# Symbol-level gating — crypto is 24/7
# ---------------------------------------------------------------------------


def test_crypto_symbol_always_open_overnight(svc):
    assert svc.is_symbol_open("BTC/USD", _et(2025, 6, 10, 2)) is True


def test_crypto_symbol_open_on_holiday(svc):
    assert svc.is_symbol_open("ETH/USD", _et(2025, 1, 1, 11)) is True


def test_stock_symbol_follows_session(svc):
    assert svc.is_symbol_open("AAPL", _et(2025, 6, 10, 10)) is True
    assert svc.is_symbol_open("AAPL", _et(2025, 6, 10, 2)) is False
    assert svc.is_symbol_open("AAPL", _et(2025, 6, 14, 11)) is False  # Saturday


# ---------------------------------------------------------------------------
# No-trade time window (proposal #339 — "avoid trading in the morning")
# ---------------------------------------------------------------------------


def test_window_inside_returns_true(svc):
    # 09:45 ET is inside the 09:30-10:00 morning window.
    assert svc.is_within_window("09:30", "10:00", _et(2025, 6, 10, 9, 45)) is True


def test_window_start_is_inclusive(svc):
    assert svc.is_within_window("09:30", "10:00", _et(2025, 6, 10, 9, 30)) is True


def test_window_end_is_exclusive(svc):
    # 10:00 sharp is outside [09:30, 10:00).
    assert svc.is_within_window("09:30", "10:00", _et(2025, 6, 10, 10, 0)) is False


def test_window_before_start_is_outside(svc):
    assert svc.is_within_window("09:30", "10:00", _et(2025, 6, 10, 9, 0)) is False


def test_window_after_end_is_outside(svc):
    assert svc.is_within_window("09:30", "10:00", _et(2025, 6, 10, 11, 0)) is False


def test_window_is_evaluated_in_eastern_time(svc):
    # 13:45 UTC == 09:45 ET in summer (EDT, UTC-4) — must be inside the window.
    utc_now = datetime(2025, 6, 10, 13, 45, tzinfo=ZoneInfo("UTC"))
    assert svc.is_within_window("09:30", "10:00", utc_now) is True


def test_window_wraps_past_midnight(svc):
    # A 23:00-02:00 window spans midnight: 23:30 and 01:00 are inside, 12:00 is not.
    assert svc.is_within_window("23:00", "02:00", _et(2025, 6, 10, 23, 30)) is True
    assert svc.is_within_window("23:00", "02:00", _et(2025, 6, 10, 1, 0)) is True
    assert svc.is_within_window("23:00", "02:00", _et(2025, 6, 10, 12, 0)) is False


def test_window_equal_bounds_is_no_window(svc):
    assert svc.is_within_window("09:30", "09:30", _et(2025, 6, 10, 9, 30)) is False


def test_window_malformed_bound_is_no_window(svc):
    now = _et(2025, 6, 10, 9, 45)
    assert svc.is_within_window("not-a-time", "10:00", now) is False
    assert svc.is_within_window("09:30", "", now) is False
    assert svc.is_within_window("25:00", "10:00", now) is False  # out-of-range hour


# ---------------------------------------------------------------------------
# Singleton + cache
# ---------------------------------------------------------------------------


def test_get_market_status_is_singleton():
    assert get_market_status() is get_market_status()


def test_injected_now_bypasses_cache(svc):
    # Two different injected instants must each compute independently.
    assert svc.state(_et(2025, 6, 10, 10)) is MarketState.OPEN
    assert svc.state(_et(2025, 6, 10, 2)) is MarketState.CLOSED
