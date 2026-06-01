"""DRIFT DETECTION — know when the system's assumptions are going stale.

Markets change; a config that was good can quietly stop working. The drift
monitor watches rolling metric streams (trade-grade quality, decision regret,
direction hit-rate, …) and raises a typed alert when the RECENT window degrades
materially versus the PRIOR window — so degradation is surfaced, not discovered
by an operator weeks later.

Each metric is registered with its polarity (is higher better?) and an absolute
degradation threshold. Pure, deterministic, bounded-memory.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import fmean
from typing import Any

from cognitive.events import EventType


@dataclass(frozen=True)
class DriftAlert:
    """A metric whose recent window has degraded past its threshold."""

    metric: str
    direction: str  # "down" = a higher-is-better metric fell; "up" = a lower-is-better metric rose
    recent: float
    baseline: float
    delta: float  # magnitude of degradation

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": EventType.DRIFT.value,
            "metric": self.metric,
            "direction": self.direction,
            "recent": self.recent,
            "baseline": self.baseline,
            "delta": self.delta,
        }


@dataclass
class _Spec:
    higher_is_better: bool
    threshold: float


class DriftMonitor:
    """Rolling recent-vs-prior comparison per registered metric."""

    def __init__(self, *, window: int = 20, min_samples: int = 10) -> None:
        self.window = window
        self.min_samples = min_samples
        self._series: dict[str, deque[float]] = {}
        self._specs: dict[str, _Spec] = {}

    def register(self, metric: str, *, higher_is_better: bool, threshold: float) -> None:
        self._specs[metric] = _Spec(higher_is_better, threshold)
        self._series[metric] = deque(maxlen=self.window * 2)

    def observe(self, metric: str, value: float) -> None:
        """Record a sample; unknown metrics are ignored (must be registered first)."""
        series = self._series.get(metric)
        if series is not None:
            series.append(float(value))

    def assess(self) -> list[DriftAlert]:
        """Compare each metric's recent half against its prior half."""
        alerts: list[DriftAlert] = []
        for metric, series in self._series.items():
            if len(series) < 2 * self.min_samples:
                continue
            values = list(series)
            half = len(values) // 2
            baseline = fmean(values[:half])
            recent = fmean(values[half:])
            spec = self._specs[metric]
            degradation = (baseline - recent) if spec.higher_is_better else (recent - baseline)
            if degradation > spec.threshold:
                alerts.append(
                    DriftAlert(
                        metric=metric,
                        direction="down" if spec.higher_is_better else "up",
                        recent=round(recent, 4),
                        baseline=round(baseline, 4),
                        delta=round(degradation, 4),
                    )
                )
        return alerts

    def snapshot(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "min_samples": self.min_samples,
            "metrics": {
                metric: {"samples": len(series), "latest": series[-1] if series else None}
                for metric, series in self._series.items()
            },
        }
