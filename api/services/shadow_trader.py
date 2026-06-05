"""Shadow paper-trading engine — runs a backtest ``Strategy`` on the LIVE tick
stream without touching real capital.

This is the missing link between the strategy *configs* (``backtest/strategies.py``)
and the live *agents*. Today every ``ChallengerAgent`` is spawned with a strategy
name but never calls the strategy function — it just grades the baseline's fills,
so all challengers grade the identical stream and the "config" is decorative.

``ShadowTradeEngine`` fixes that: feed it the same prices the SignalGenerator sees
and it actually runs the strategy's buy/sell/hold decision, tracks a hypothetical
(shadow) position, and realizes PnL on every flip. The result is the strategy's
REAL performance on live data — the evidence a challenger needs to earn a
promotion proposal, measured the same way the backtest harness measures it.

Pure and deterministic: no IO, no Redis, no DB. Trivially unit-testable, and the
agent layer is responsible for publishing/persisting the metrics it exposes.

Position model (signal-following, one unit, long/short flip):
  buy  -> target LONG    sell -> target SHORT    hold -> keep current target
A flip closes the open position (realizing PnL) and opens the new one. PnL is in
price terms per unit: long close = exit - entry, short close = entry - exit.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backtest.strategies import Bar  # runtime use: Bar(...) constructor in observe()

if TYPE_CHECKING:
    from backtest.strategies import Strategy  # annotation-only

# Action constants mirror backtest.strategies (HOLD/BUY/SELL) without importing the
# private module-level names, so this engine has one obvious source of truth.
_BUY = "buy"
_SELL = "sell"

# Direction sentinels for the shadow position.
_FLAT = 0
_LONG = 1
_SHORT = -1


@dataclass(frozen=True)
class ShadowTrade:
    """A single closed shadow round-trip (realized when the position flips)."""

    symbol: str
    direction: str  # "long" or "short" — the side that was just CLOSED
    entry_price: float
    exit_price: float
    pnl: float  # price-terms PnL per unit (long: exit-entry, short: entry-exit)
    bars_held: int


@dataclass
class _OpenPosition:
    direction: int = _FLAT
    entry_price: float = 0.0
    entry_index: int = 0


@dataclass
class ShadowMetrics:
    """Aggregate performance of a strategy's shadow trades on live data."""

    trades: int = 0
    wins: int = 0
    realized_pnl: float = 0.0
    pnls: list[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.realized_pnl / self.trades if self.trades else 0.0

    @property
    def sharpe(self) -> float:
        """Trade-level Sharpe proxy: mean(pnl) / stdev(pnl). 0.0 below 2 trades.

        Population stdev, same convention the backtest comparison uses, so a
        challenger's live shadow Sharpe is comparable to its backtested Sharpe.
        """
        n = len(self.pnls)
        if n < 2:
            return 0.0
        mean = self.realized_pnl / n
        var = sum((p - mean) ** 2 for p in self.pnls) / n
        sd = var**0.5
        return mean / sd if sd > 0 else 0.0


class ShadowTradeEngine:
    """Runs one ``Strategy`` over a live per-symbol price stream as shadow trades."""

    def __init__(self, strategy_name: str, strategy: Strategy, *, history_maxlen: int = 50) -> None:
        self.strategy_name = strategy_name
        self._strategy = strategy
        self._history_maxlen = max(history_maxlen, 2)
        self._history: dict[str, deque[float]] = {}
        self._positions: dict[str, _OpenPosition] = {}
        self._index: int = 0
        self.metrics = ShadowMetrics()

    @property
    def open_position_count(self) -> int:
        """How many symbols currently hold an open (non-flat) shadow position."""
        return sum(1 for p in self._positions.values() if p.direction != _FLAT)

    def observe(self, symbol: str, price: float) -> ShadowTrade | None:
        """Feed one live price for ``symbol``; returns a ShadowTrade iff a position closed.

        Mirrors how SignalGenerator builds its decision context: a rolling price
        history per symbol, the bar-to-bar percent move, and the strategy's call.
        """
        if not symbol or price <= 0:
            return None

        hist = self._history.setdefault(symbol, deque(maxlen=self._history_maxlen))
        prev_price = hist[-1] if hist else price
        hist.append(price)
        self._index += 1

        pct = ((price - prev_price) / prev_price * 100.0) if prev_price else 0.0
        bar = Bar(
            index=self._index,
            price=price,
            prev_price=prev_price,
            pct=pct,
            history=list(hist),
        )

        action = str(self._strategy(bar)).lower()
        return self._apply_action(symbol, action, price)

    def _apply_action(self, symbol: str, action: str, price: float) -> ShadowTrade | None:
        pos = self._positions.setdefault(symbol, _OpenPosition())

        if action == _BUY:
            target = _LONG
        elif action == _SELL:
            target = _SHORT
        else:  # hold (or any non-trading action) — keep the current position
            return None

        if pos.direction == target:
            return None  # already in the desired direction; nothing to do

        closed = self._close(symbol, pos, price)
        # Open the new position at the current price.
        pos.direction = target
        pos.entry_price = price
        pos.entry_index = self._index
        return closed

    def _close(self, symbol: str, pos: _OpenPosition, price: float) -> ShadowTrade | None:
        """Realize PnL of the open position (if any) and record it. Returns the trade."""
        if pos.direction == _FLAT:
            return None
        if pos.direction == _LONG:
            pnl = price - pos.entry_price
            direction = "long"
        else:
            pnl = pos.entry_price - price
            direction = "short"

        self.metrics.trades += 1
        self.metrics.realized_pnl += pnl
        self.metrics.pnls.append(pnl)
        if pnl > 0:
            self.metrics.wins += 1

        return ShadowTrade(
            symbol=symbol,
            direction=direction,
            entry_price=pos.entry_price,
            exit_price=price,
            pnl=pnl,
            bars_held=self._index - pos.entry_index,
        )
