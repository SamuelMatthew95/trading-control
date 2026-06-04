"""In-memory learning / performance service.

Backs ``api/routes/performance.py``. It exposes a per-agent performance view so
the performance endpoints stay importable, registered, and responsive even when
Postgres is unavailable (memory mode). When the DB is up the route layer still
queries the durable tables directly for statistics/runs; this service provides
the per-agent rollup and a stable, never-raising contract.
"""

from __future__ import annotations

from typing import Any

from api.constants import ALL_AGENT_NAMES, FieldName

# Internal rollup keys that are NOT FieldName payload contract keys.
_TOTAL_RUNS = "total_runs"
_SUCCESSFUL_RUNS = "successful_runs"
_FAILED_RUNS = "failed_runs"
_LAST_RUN_AT = "last_run_at"


def _empty_perf(agent_name: str) -> dict[str, Any]:
    return {
        FieldName.AGENT_NAME: agent_name,
        _TOTAL_RUNS: 0,
        _SUCCESSFUL_RUNS: 0,
        _FAILED_RUNS: 0,
        FieldName.SUCCESS_RATE: 0.0,
        FieldName.AVG_LATENCY_MS: 0.0,
        _LAST_RUN_AT: None,
    }


class LearningService:
    """Process-memory per-agent performance rollup. Never raises."""

    def __init__(self) -> None:
        # Seed every known agent so the dashboard always has the full roster
        # rather than only agents that happened to run this process.
        self.agent_performance: dict[str, dict[str, Any]] = {
            name: _empty_perf(name) for name in ALL_AGENT_NAMES
        }

    def record_run(
        self, agent_name: str, *, success: bool, latency_ms: float | None = None
    ) -> None:
        """Fold a single agent run into the rollup (best-effort, no raises)."""
        perf = self.agent_performance.setdefault(agent_name, _empty_perf(agent_name))
        perf[_TOTAL_RUNS] += 1
        if success:
            perf[_SUCCESSFUL_RUNS] += 1
        else:
            perf[_FAILED_RUNS] += 1
        total = perf[_TOTAL_RUNS]
        perf[FieldName.SUCCESS_RATE] = round(perf[_SUCCESSFUL_RUNS] / total, 4) if total else 0.0
        if latency_ms is not None:
            prev = perf[FieldName.AVG_LATENCY_MS] * (total - 1)
            perf[FieldName.AVG_LATENCY_MS] = round((prev + latency_ms) / total, 2)

    async def get_agent_performance(
        self, agent_name: str, session: Any | None = None
    ) -> dict[str, Any]:
        """Return the rollup for one agent (zeroed default for unknown agents)."""
        return self.agent_performance.get(agent_name, _empty_perf(agent_name))
