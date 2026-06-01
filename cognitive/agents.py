"""MULTI-AGENT AI LAYER — cognitive specialists, advisory only.

Five specialists each read the market / event stream and emit ONE structured
fact onto :class:`cognitive.events.EventStream`. They never decide trades — they
produce reasoning inputs that the deterministic decision engine later scores.
Output payloads match the system spec contracts exactly:

    News       -> {"type": "news_signal", "sentiment": float[-1,1], "confidence": float}
    Technical  -> {"type": "tech_signal", "trend":     float[-1,1], "confidence": float}
    Macro      -> {"type": "macro_signal","regime":    float[-1,1]}
    Risk       -> {"type": "risk_signal", "risk_flags": [...], "risk_score": float[0,1]}
    Reasoning  -> {"type": "reasoning",   "summary": str, "signals_summary": {...}}

Determinism vs. LLMs: the default scorers are pure functions of price history
(and an optional externally-supplied news sentiment), so the system stays
reproducible and testable. Each signal agent accepts an injectable ``scorer`` —
that is the seam where a production LLM-backed scorer plugs in WITHOUT changing
the deterministic decision/execution path downstream. The reproducibility
guarantee of the brain holds because the LLM output is just another structured
signal; nothing downstream branches on a model.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from cognitive.events import EventStream, EventType

# --- Agent identities (stable strings for the `source` field) -----------------
NEWS_AGENT = "news_agent"
TECH_AGENT = "technical_agent"
MACRO_AGENT = "macro_agent"
RISK_AGENT = "risk_agent"
REASONING_AGENT = "reasoning_agent"

# --- Deterministic scorer tuning (named, never bare magic numbers) ------------
TECH_WINDOW = 10  # bars of recent returns the technical trend reads
MACRO_WINDOW = 60  # bars of context the macro regime reads
RISK_WINDOW = 30  # bars the risk assessment reads
MACRO_DRIFT_SCALE = 10.0  # maps long-horizon drift into the tanh sweet spot
RISK_VOL_SCALE = 25.0  # maps per-bar return stdev into the [0,1] risk score
HIGH_VOL_THRESHOLD = 0.02  # per-bar stdev above this raises a high_volatility flag
DRAWDOWN_FLAG_THRESHOLD = 0.10  # window drawdown above this raises a drawdown flag

# Risk flag strings (the only allowed members of risk_signal.risk_flags).
FLAG_HIGH_VOLATILITY = "high_volatility"
FLAG_DRAWDOWN = "drawdown"


def clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    """Clamp into ``[lo, hi]`` (default the signed signal range)."""
    return max(lo, min(hi, value))


def clamp01(value: float) -> float:
    """Clamp into ``[0, 1]`` (the risk-score / probability range)."""
    return max(0.0, min(1.0, value))


@dataclass(frozen=True)
class MarketView:
    """One bar of market context handed to the agents.

    ``news_sentiment`` is an OPTIONAL externally-supplied signal in [-1, 1]
    (e.g. from a news feed or an LLM scorer); when ``None`` the News Agent stays
    neutral. Everything else is derived deterministically from ``history``.
    """

    symbol: str
    price: float
    history: Sequence[float]  # closes oldest -> newest, including the current bar
    news_sentiment: float | None = None
    news_confidence: float = 0.0
    ts: str = ""


def _returns(history: Sequence[float]) -> list[float]:
    """Bar-to-bar fractional returns, skipping any zero-priced prior bar."""
    out: list[float] = []
    for i in range(1, len(history)):
        prev = history[i - 1]
        if prev:
            out.append((history[i] - prev) / prev)
    return out


def technical_trend(history: Sequence[float], *, window: int = TECH_WINDOW) -> tuple[float, float]:
    """Volatility-normalized momentum over the recent window -> (trend, confidence).

    ``trend`` is ``tanh`` of the mean/stdev z-score so it saturates smoothly in
    [-1, 1]; ``confidence`` rises with both the trend magnitude and how
    one-directional the window was.
    """
    rets = _returns(history)[-window:]
    if not rets:
        return 0.0, 0.0
    mean = statistics.fmean(rets)
    sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    if sd > 1e-9:
        z = mean / sd
    elif mean:
        z = math.copysign(3.0, mean)
    else:
        z = 0.0
    trend = math.tanh(z)
    same_dir = (sum(1 for r in rets if (r > 0) == (mean > 0)) / len(rets)) if mean else 0.0
    return round(trend, 4), round(clamp01(abs(trend) * same_dir), 4)


def macro_regime(history: Sequence[float], *, window: int = MACRO_WINDOW) -> float:
    """Long-horizon drift squashed to a [-1, 1] regime score."""
    window_prices = history[-window:]
    if len(window_prices) < 2 or not window_prices[0]:
        return 0.0
    drift = (window_prices[-1] - window_prices[0]) / window_prices[0]
    return round(math.tanh(drift * MACRO_DRIFT_SCALE), 4)


def risk_assessment(
    history: Sequence[float], *, window: int = RISK_WINDOW
) -> tuple[float, list[str]]:
    """Window volatility + drawdown -> (risk_score in [0,1], risk_flags)."""
    rets = _returns(history)[-window:]
    window_prices = list(history[-window:])
    vol = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    peak = window_prices[0] if window_prices else 0.0
    max_drawdown = 0.0
    for price in window_prices:
        peak = max(peak, price)
        if peak:
            max_drawdown = max(max_drawdown, (peak - price) / peak)
    risk_score = clamp01(vol * RISK_VOL_SCALE + max_drawdown)
    flags: list[str] = []
    if vol > HIGH_VOL_THRESHOLD:
        flags.append(FLAG_HIGH_VOLATILITY)
    if max_drawdown > DRAWDOWN_FLAG_THRESHOLD:
        flags.append(FLAG_DRAWDOWN)
    return round(risk_score, 4), flags


def news_sentiment(market: MarketView) -> tuple[float, float]:
    """Pass-through of the externally-supplied sentiment; neutral if absent."""
    if market.news_sentiment is None:
        return 0.0, 0.0
    return round(clamp(market.news_sentiment), 4), round(clamp01(market.news_confidence), 4)


NewsScorer = Callable[[MarketView], tuple[float, float]]
TechScorer = Callable[[MarketView], tuple[float, float]]
MacroScorer = Callable[[MarketView], float]
RiskScorer = Callable[[MarketView], tuple[float, list[str]]]


class NewsAgent:
    """Sentiment specialist. Default scorer passes through external sentiment."""

    name = NEWS_AGENT

    def __init__(self, scorer: NewsScorer | None = None) -> None:
        self._scorer = scorer or news_sentiment

    def analyze(self, market: MarketView) -> dict[str, Any]:
        sentiment, confidence = self._scorer(market)
        return {
            "type": EventType.NEWS_SIGNAL.value,
            "sentiment": sentiment,
            "confidence": confidence,
        }

    def emit(
        self, stream: EventStream, market: MarketView, *, trace_id: str = ""
    ) -> dict[str, Any]:
        payload = self.analyze(market)
        stream.emit(
            EventType.NEWS_SIGNAL, payload, source=self.name, trace_id=trace_id, ts=market.ts
        )
        return payload


class TechnicalAgent:
    """Trend / indicator specialist."""

    name = TECH_AGENT

    def __init__(self, scorer: TechScorer | None = None) -> None:
        self._scorer = scorer or (lambda m: technical_trend(m.history))

    def analyze(self, market: MarketView) -> dict[str, Any]:
        trend, confidence = self._scorer(market)
        return {"type": EventType.TECH_SIGNAL.value, "trend": trend, "confidence": confidence}

    def emit(
        self, stream: EventStream, market: MarketView, *, trace_id: str = ""
    ) -> dict[str, Any]:
        payload = self.analyze(market)
        stream.emit(
            EventType.TECH_SIGNAL, payload, source=self.name, trace_id=trace_id, ts=market.ts
        )
        return payload


class MacroAgent:
    """Regime-detection specialist."""

    name = MACRO_AGENT

    def __init__(self, scorer: MacroScorer | None = None) -> None:
        self._scorer = scorer or (lambda m: macro_regime(m.history))

    def analyze(self, market: MarketView) -> dict[str, Any]:
        return {"type": EventType.MACRO_SIGNAL.value, "regime": self._scorer(market)}

    def emit(
        self, stream: EventStream, market: MarketView, *, trace_id: str = ""
    ) -> dict[str, Any]:
        payload = self.analyze(market)
        stream.emit(
            EventType.MACRO_SIGNAL, payload, source=self.name, trace_id=trace_id, ts=market.ts
        )
        return payload


class RiskAgent:
    """Risk-annotation specialist — annotates only, never gates (that is the
    deterministic risk engine's job)."""

    name = RISK_AGENT

    def __init__(self, scorer: RiskScorer | None = None) -> None:
        self._scorer = scorer or (lambda m: risk_assessment(m.history))

    def analyze(self, market: MarketView) -> dict[str, Any]:
        risk_score, flags = self._scorer(market)
        return {"type": EventType.RISK_SIGNAL.value, "risk_flags": flags, "risk_score": risk_score}

    def emit(
        self, stream: EventStream, market: MarketView, *, trace_id: str = ""
    ) -> dict[str, Any]:
        payload = self.analyze(market)
        stream.emit(
            EventType.RISK_SIGNAL, payload, source=self.name, trace_id=trace_id, ts=market.ts
        )
        return payload


class ReasoningAgent:
    """Human-readable explanation layer. Summarises the other signals; it makes
    NO decision and emits no number the decision engine reads."""

    name = REASONING_AGENT

    def analyze(self, signals: dict[str, float]) -> dict[str, Any]:
        summary = (
            f"news {signals.get('news', 0.0):+.2f}, tech {signals.get('tech', 0.0):+.2f}, "
            f"macro {signals.get('macro', 0.0):+.2f}; risk {signals.get('risk', 0.0):.2f}"
        )
        return {
            "type": EventType.REASONING.value,
            "summary": summary,
            "signals_summary": dict(signals),
        }

    def emit(
        self, stream: EventStream, signals: dict[str, float], *, trace_id: str = "", ts: str = ""
    ) -> dict[str, Any]:
        payload = self.analyze(signals)
        stream.emit(EventType.REASONING, payload, source=self.name, trace_id=trace_id, ts=ts)
        return payload
