"""Centralized market-status service: the single source of truth for whether a
US equity session (NYSE / NASDAQ) is currently open.

Why this exists
---------------
Crypto trades 24/7, but equities only move during the regular cash session
(09:30-16:00 ET, Mon-Fri) outside of exchange holidays, with a 13:00 ET early
close on a handful of half-days. Before this service the platform polled,
bootstrapped, broadcast, and graded stock symbols around the clock — burning
Alpaca quota, Redis connections, CPU, and log volume on data that cannot change
until the next session, and generating SIP-entitlement 403s overnight.

Every stock subsystem (price poller, signal generator, execution engine,
broadcaster) consumes this one service so the gate is consistent everywhere.

Design
------
Pure-Python and dependency-free. Holiday dates are derived from the published
NYSE rules — fixed-date holidays (observed-shifted off weekends), nth-weekday
holidays, and Good Friday via the Computus algorithm — so there is no network
call and no heavy calendar dependency. Every decision is a deterministic
function of an injectable ``now`` (which MUST be timezone-aware), so the whole
thing is unit-testable without freezing the system clock.

The live result is cached for a short window so repeated calls within a single
polling cycle reuse one computation (architectural requirement: "market status
is determined once and reused").
"""

from __future__ import annotations

import time as _time
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from api.constants import MarketState

_ET = ZoneInfo("America/New_York")

# Regular cash-session boundaries, in Eastern Time.
_REGULAR_OPEN = time(9, 30)
_REGULAR_CLOSE = time(16, 0)
_EARLY_CLOSE = time(13, 0)
# Extended-hours boundaries used only to label PREMARKET / AFTER_HOURS so callers
# can distinguish "closed but session-adjacent" from "fully dark".
_PREMARKET_OPEN = time(4, 0)
_AFTER_HOURS_END = time(20, 0)

# Reuse one computed state for this long on the live path (now is None).
_CACHE_TTL_SECONDS = 30.0

# Juneteenth became an NYSE holiday in 2022.
_JUNETEENTH_FIRST_YEAR = 2022


def _easter(year: int) -> date:
    """Gregorian Easter Sunday via the Anonymous/Meeus Computus. Pure arithmetic."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    lp = (32 + 2 * e + 2 * i - h - k) % 7
    mp = (a + 11 * h + 22 * lp) // 451
    month = (h + lp - 7 * mp + 114) // 31
    day = ((h + lp - 7 * mp + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The nth (1-based) ``weekday`` (Mon=0 … Sun=6) of ``month``."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """The last ``weekday`` (Mon=0 … Sun=6) of ``month``."""
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(holiday: date) -> date:
    """NYSE observation rule: Saturday → preceding Friday, Sunday → following Monday."""
    if holiday.weekday() == 5:  # Saturday
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:  # Sunday
        return holiday + timedelta(days=1)
    return holiday


def _parse_hhmm(value: str | None) -> time | None:
    """Parse a 24-hour ``"HH:MM"`` string into a :class:`datetime.time`.

    Returns ``None`` for empty / malformed input so a typo in operator config is
    treated as "no window" rather than raising on the hot path.
    """
    if not value:
        return None
    parts = str(value).strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


@lru_cache(maxsize=16)
def market_holidays(year: int) -> frozenset[date]:
    """Full-day NYSE/NASDAQ closures for ``year`` as observed dates."""
    days = {
        _observed(date(year, 1, 1)),  # New Year's Day
        _nth_weekday(year, 1, 0, 3),  # MLK Jr. Day — 3rd Mon Jan
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday — 3rd Mon Feb
        _easter(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day — last Mon May
        _nth_weekday(year, 9, 0, 1),  # Labor Day — 1st Mon Sep
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving — 4th Thu Nov
        _observed(date(year, 7, 4)),  # Independence Day
        _observed(date(year, 12, 25)),  # Christmas
    }
    if year >= _JUNETEENTH_FIRST_YEAR:
        days.add(_observed(date(year, 6, 19)))  # Juneteenth
    return frozenset(days)


@lru_cache(maxsize=16)
def early_close_days(year: int) -> frozenset[date]:
    """Half-days that close at 13:00 ET — the recurring NYSE set, best-effort.

    Getting an early close slightly wrong only over-permits the 13:00-16:00
    window on at most a few days a year; full-day holidays (the load win) are
    computed exactly.
    """
    holidays = market_holidays(year)
    days: set[date] = set()
    # Day after Thanksgiving (4th Thu Nov + 1 = Friday).
    days.add(_nth_weekday(year, 11, 3, 4) + timedelta(days=1))
    # Christmas Eve, when it is a weekday and not itself a full holiday.
    eve = date(year, 12, 24)
    if eve.weekday() < 5 and eve not in holidays:
        days.add(eve)
    # July 3, when it is a weekday and not itself the observed Independence Day.
    july3 = date(year, 7, 3)
    if july3.weekday() < 5 and july3 not in holidays:
        days.add(july3)
    return frozenset(days)


class MarketStatusService:
    """Stateless market clock with a short result cache. Safe as a singleton."""

    def __init__(self) -> None:
        self._cached_state: MarketState | None = None
        self._cached_at: float = 0.0

    def _compute(self, now_et: datetime) -> MarketState:
        """Pure mapping from an ET ``datetime`` to a :class:`MarketState`."""
        if now_et.weekday() >= 5:  # Saturday / Sunday
            return MarketState.CLOSED
        if now_et.date() in market_holidays(now_et.year):
            return MarketState.HOLIDAY
        close = _EARLY_CLOSE if now_et.date() in early_close_days(now_et.year) else _REGULAR_CLOSE
        t = now_et.time()
        if _REGULAR_OPEN <= t < close:
            return MarketState.OPEN
        if _PREMARKET_OPEN <= t < _REGULAR_OPEN:
            return MarketState.PREMARKET
        if close <= t < _AFTER_HOURS_END:
            return MarketState.AFTER_HOURS
        return MarketState.CLOSED

    def state(self, now: datetime | None = None) -> MarketState:
        """Current equity-market state.

        Pass a timezone-aware ``now`` to compute deterministically and bypass the
        cache (used by tests); omit it on the live path to reuse a cached result
        for up to ``_CACHE_TTL_SECONDS``.
        """
        if now is not None:
            return self._compute(now.astimezone(_ET))
        mono = _time.monotonic()
        if self._cached_state is None or (mono - self._cached_at) >= _CACHE_TTL_SECONDS:
            self._cached_state = self._compute(datetime.now(_ET))
            self._cached_at = mono
        return self._cached_state

    def is_open(self, now: datetime | None = None) -> bool:
        """True iff the regular equity cash session is open right now."""
        return self.state(now) is MarketState.OPEN

    def is_symbol_open(self, symbol: str, now: datetime | None = None) -> bool:
        """Whether trading is allowed for ``symbol``: crypto 24/7, equities by session."""
        if "/" in (symbol or ""):  # crypto pairs are written BASE/QUOTE
            return True
        return self.is_open(now)

    def is_within_window(self, start_hhmm: str, end_hhmm: str, now: datetime | None = None) -> bool:
        """True iff the current ET wall-clock time falls within ``[start, end)``.

        Bounds are 24-hour ``"HH:MM"`` strings interpreted in Eastern Time. A
        window whose start is later than its end wraps past midnight (e.g.
        ``"23:00"``–``"02:00"``). A malformed bound or ``start == end`` means "no
        window" → ``False``. Pass a timezone-aware ``now`` for deterministic
        tests; omit it to use the live clock. This is a pure wall-clock check —
        independent of session / holiday state — so it composes with (does not
        replace) :meth:`is_symbol_open`.
        """
        start = _parse_hhmm(start_hhmm)
        end = _parse_hhmm(end_hhmm)
        if start is None or end is None or start == end:
            return False
        now_et = (now.astimezone(_ET) if now is not None else datetime.now(_ET)).time()
        if start < end:
            return start <= now_et < end
        # Wrap past midnight: inside if at/after start OR before end.
        return now_et >= start or now_et < end


_service: MarketStatusService | None = None


def get_market_status() -> MarketStatusService:
    """Return the process-wide :class:`MarketStatusService` singleton."""
    global _service
    if _service is None:
        _service = MarketStatusService()
    return _service
