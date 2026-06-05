"""Learning / performance service.

Backs ``api/routes/performance.py``. It derives a per-agent run rollup from the
authoritative ``agent_runs`` record — the in-memory runtime store in memory mode
— so the performance endpoints return real activity (run counts, last-seen,
latency where recorded) and never 500.

It holds no mutable state of its own: every read recomputes from the store, so
there is nothing to keep in sync and no stale rollup to drift. Fields that the
``agent_runs`` payload does not carry in a given mode (e.g. a success flag is not
written on every memory-mode run) are reported as ``None`` rather than a
fabricated zero, so the numbers are honest.
"""

from __future__ import annotations

from typing import Any

from api.constants import ALL_AGENT_NAMES, FieldName
from api.runtime_state import get_runtime_store


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class LearningService:
    """Stateless per-agent performance view computed from ``agent_runs``."""

    def _runs_for(self, agent_name: str) -> list[dict[str, Any]]:
        store = get_runtime_store()
        runs = getattr(store, "agent_runs", [])
        return [r for r in runs if r.get(FieldName.SOURCE) == agent_name]

    def _rollup(self, agent_name: str) -> dict[str, Any]:
        runs = self._runs_for(agent_name)
        latencies = [
            lat
            for r in runs
            if (lat := _safe_float(r.get(FieldName.EXECUTION_TIME_MS))) is not None
        ]
        created = [c for r in runs if (c := r.get(FieldName.CREATED_AT)) is not None]
        return {
            FieldName.AGENT_NAME: agent_name,
            FieldName.TOTAL_RUNS: len(runs),
            FieldName.AVG_LATENCY_MS: round(sum(latencies) / len(latencies), 2)
            if latencies
            else None,
            "last_run_at": max(created) if created else None,
        }

    @property
    def agent_performance(self) -> dict[str, dict[str, Any]]:
        """Live rollup for the full known-agent roster (recomputed on read)."""
        return {name: self._rollup(name) for name in ALL_AGENT_NAMES}

    async def get_agent_performance(
        self, agent_name: str, session: Any | None = None
    ) -> dict[str, Any]:
        """Return the live rollup for one agent (zeroed default for unknown agents)."""
        return self._rollup(agent_name)
