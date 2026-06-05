"""Per-agent performance grading for the dashboard drill-in.

The GradeAgent emits ONE system-wide grade for the whole trading loop. This
module grades each pipeline agent on ITS OWN telemetry instead, so an operator
can click into an agent and see what it actually did, the grade it earned, the
learnings derived from its behaviour, and whether sustained good work has
promoted it.

Inputs come from the same mode-agnostic payload builders the dashboard already
uses, so this works identically with Postgres or the InMemoryStore:

* heartbeat status / event_count / last_event  → ``get_agents_status_payload``
* recent ``agent_runs`` (status, latency, source) → ``get_agent_metrics_payload``

The overall score is a weighted blend of whichever dimensions have data
(liveness, success rate, throughput, latency). Dimensions without data are
flagged ``data_available=False`` and dropped from the weighting rather than
silently scored as zero, and an agent with no heartbeat, no events, and no runs
is ``UNRATED`` — dormant is not the same as failing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from api.constants import (
    AGENT_PERF_LIVENESS_ACTIVE,
    AGENT_PERF_LIVENESS_STALE,
    AGENT_PERF_THROUGHPUT_SATURATION,
    AGENT_PERF_W_LATENCY,
    AGENT_PERF_W_LIVENESS,
    AGENT_PERF_W_SUCCESS,
    AGENT_PERF_W_THROUGHPUT,
    ALL_AGENT_NAMES,
    CIRCUIT_BREAKER_MAX_LATENCY_MS,
    GRADE_TO_TIER,
    SOURCE_TO_AGENT,
    TIER_PROMOTED,
    TIER_UNRATED,
    FieldName,
    StatusValue,
)
from api.runtime_state import is_db_available
from api.services.agents.scoring import score_to_grade
from api.services.dashboard.agents import (
    get_agent_metrics_payload,
    get_agents_status_payload,
)

# Dimension identifiers (StrEnum members reused so no raw-string keys leak in).
_DIM_WEIGHTS: dict[str, float] = {
    FieldName.LIVENESS: AGENT_PERF_W_LIVENESS,
    FieldName.SUCCESS_RATE: AGENT_PERF_W_SUCCESS,
    FieldName.THROUGHPUT: AGENT_PERF_W_THROUGHPUT,
    FieldName.LATENCY: AGENT_PERF_W_LATENCY,
}
_DIM_LABELS: dict[str, str] = {
    FieldName.LIVENESS: "Liveness",
    FieldName.SUCCESS_RATE: "Success rate",
    FieldName.THROUGHPUT: "Throughput",
    FieldName.LATENCY: "Latency",
}

# Heartbeat status buckets (compared case-insensitively).
_ACTIVE_STATES = {"active", "live", "running"}
_RESTING_STATES = {"stale", "idle"}

# Number of recent runs surfaced in the drill-in activity feed.
_ACTIVITY_LIMIT = 12

# Tones map to the frontend's semantic Tone tokens.
_TONE_SUCCESS = "success"
_TONE_WARNING = "warning"
_TONE_DANGER = "danger"
_TONE_NEUTRAL = "neutral"


@dataclass
class _Dimension:
    key: str
    value: float
    available: bool


def _display_name(agent_name: str) -> str:
    return agent_name.replace("_", " ").title()


def _iso(value: Any) -> str | None:
    """Normalize a created_at that may be an epoch float or an ISO string."""
    if value is None:
        return None
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return None
    return str(value)


def _liveness_dimension(heartbeat: dict[str, Any]) -> _Dimension:
    status = str(heartbeat.get(FieldName.STATUS) or "").strip().lower()
    if status in _ACTIVE_STATES:
        return _Dimension(FieldName.LIVENESS, AGENT_PERF_LIVENESS_ACTIVE, True)
    if status in _RESTING_STATES:
        return _Dimension(FieldName.LIVENESS, AGENT_PERF_LIVENESS_STALE, True)
    # WAITING / OFFLINE / unknown → no heartbeat has been recorded yet.
    return _Dimension(FieldName.LIVENESS, 0.0, False)


def _run_tallies(runs: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Return (completed, failed, total_terminal) over an agent's runs."""
    completed = 0
    failed = 0
    for run in runs:
        status = str(run.get(FieldName.STATUS) or "").strip().lower()
        if status == StatusValue.COMPLETED:
            completed += 1
        elif status in (StatusValue.FAILED, "error"):
            failed += 1
    return completed, failed, completed + failed


def _success_dimension(completed: int, terminal: int) -> _Dimension:
    if terminal <= 0:
        return _Dimension(FieldName.SUCCESS_RATE, 0.0, False)
    return _Dimension(FieldName.SUCCESS_RATE, completed / terminal, True)


def _throughput_dimension(heartbeat: dict[str, Any], live_available: bool) -> _Dimension:
    try:
        events = int(heartbeat.get(FieldName.EVENT_COUNT) or 0)
    except (TypeError, ValueError):
        events = 0
    # Absent a heartbeat, an event_count of 0 is missing data, not zero work.
    if not live_available and events == 0:
        return _Dimension(FieldName.THROUGHPUT, 0.0, False)
    value = min(events / AGENT_PERF_THROUGHPUT_SATURATION, 1.0)
    return _Dimension(FieldName.THROUGHPUT, value, True)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[idx]


def _latency_dimension(runs: list[dict[str, Any]]) -> tuple[_Dimension, float | None]:
    latencies: list[float] = []
    for run in runs:
        raw = run.get(FieldName.LATENCY_MS)
        if raw is None:
            continue
        try:
            latencies.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not latencies:
        return _Dimension(FieldName.LATENCY, 0.0, False), None
    p95 = _p95(latencies)
    value = 1.0 - min(p95 / CIRCUIT_BREAKER_MAX_LATENCY_MS, 1.0)
    return _Dimension(FieldName.LATENCY, value, True), p95


def _build_learnings(
    heartbeat: dict[str, Any],
    dims: dict[str, _Dimension],
    completed: int,
    failed: int,
    terminal: int,
    p95_latency: float | None,
    graded: bool,
) -> list[dict[str, str]]:
    """Deterministic, evidence-backed insights — no LLM, no fabrication."""
    learnings: list[dict[str, str]] = []
    if not graded:
        learnings.append(
            {
                FieldName.TEXT: "Dormant — no heartbeat, events, or runs recorded yet; not graded.",
                FieldName.TONE: _TONE_NEUTRAL,
            }
        )
        return learnings

    last_event = str(heartbeat.get(FieldName.LAST_EVENT) or "").strip() or "n/a"
    live = dims[FieldName.LIVENESS]
    if not live.available:
        learnings.append(
            {FieldName.TEXT: "No heartbeat recorded yet.", FieldName.TONE: _TONE_NEUTRAL}
        )
    elif live.value >= AGENT_PERF_LIVENESS_ACTIVE:
        learnings.append(
            {
                FieldName.TEXT: f"Live — heartbeat current; last event: {last_event}.",
                FieldName.TONE: _TONE_SUCCESS,
            }
        )
    else:
        seconds_ago = heartbeat.get(FieldName.SECONDS_AGO)
        ago = f"{int(seconds_ago)}s" if isinstance(seconds_ago, int | float) else "a while"
        learnings.append(
            {
                FieldName.TEXT: f"Resting/stale — no heartbeat for {ago}; last event: {last_event}.",
                FieldName.TONE: _TONE_WARNING,
            }
        )

    if terminal > 0:
        if failed == 0:
            learnings.append(
                {
                    FieldName.TEXT: f"All {completed} recent runs completed cleanly.",
                    FieldName.TONE: _TONE_SUCCESS,
                }
            )
        else:
            rate = failed / terminal
            learnings.append(
                {
                    FieldName.TEXT: (
                        f"{failed} of {terminal} recent runs failed ({rate * 100:.0f}%)."
                    ),
                    FieldName.TONE: _TONE_DANGER if rate > 0.2 else _TONE_WARNING,
                }
            )

    throughput = dims[FieldName.THROUGHPUT]
    if throughput.available:
        events = int(heartbeat.get(FieldName.EVENT_COUNT) or 0)
        if throughput.value >= 1.0:
            learnings.append(
                {
                    FieldName.TEXT: f"High throughput — {events} events processed.",
                    FieldName.TONE: _TONE_SUCCESS,
                }
            )
        elif throughput.value < 0.25:
            learnings.append(
                {
                    FieldName.TEXT: f"Low activity — only {events} events processed.",
                    FieldName.TONE: _TONE_WARNING,
                }
            )

    if p95_latency is not None:
        good = p95_latency <= CIRCUIT_BREAKER_MAX_LATENCY_MS * 0.5
        learnings.append(
            {
                FieldName.TEXT: (
                    f"p95 latency ~{p95_latency:.0f}ms "
                    f"(budget {CIRCUIT_BREAKER_MAX_LATENCY_MS:.0f}ms)."
                ),
                FieldName.TONE: _TONE_SUCCESS if good else _TONE_WARNING,
            }
        )
    return learnings


def _recent_activity(agent_name: str, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the agent actually did — its most recent runs, newest first."""
    activity: list[dict[str, Any]] = []
    for run in reversed(runs[-_ACTIVITY_LIMIT:]):
        payload = run.get(FieldName.INPUT_DATA)
        symbol = payload.get(FieldName.SYMBOL) if isinstance(payload, dict) else None
        activity.append(
            {
                FieldName.TRACE_ID: run.get(FieldName.TRACE_ID),
                FieldName.STATUS: run.get(FieldName.STATUS),
                FieldName.SYMBOL: symbol,
                FieldName.CREATED_AT: _iso(run.get(FieldName.CREATED_AT)),
            }
        )
    return activity


def _grade_agent(
    agent_name: str,
    heartbeat: dict[str, Any],
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    live = _liveness_dimension(heartbeat)
    completed, failed, terminal = _run_tallies(runs)
    success = _success_dimension(completed, terminal)
    throughput = _throughput_dimension(heartbeat, live.available)
    latency, p95_latency = _latency_dimension(runs)

    dims = {
        FieldName.LIVENESS: live,
        FieldName.SUCCESS_RATE: success,
        FieldName.THROUGHPUT: throughput,
        FieldName.LATENCY: latency,
    }
    available = [d for d in dims.values() if d.available]

    if available:
        total_weight = sum(_DIM_WEIGHTS[d.key] for d in available)
        raw = sum(d.value * _DIM_WEIGHTS[d.key] for d in available) / total_weight
        score: float | None = round(min(max(raw, 0.0), 1.0), 4)
        letter: str | None = score_to_grade(score)
        tier = GRADE_TO_TIER.get(letter, TIER_UNRATED)
        status = str(heartbeat.get(FieldName.STATUS) or "UNKNOWN")
    else:
        score = None
        letter = None
        tier = TIER_UNRATED
        status = "INSUFFICIENT_DATA"

    graded = score is not None
    return {
        FieldName.NAME: agent_name,
        FieldName.DISPLAY_NAME: _display_name(agent_name),
        FieldName.STATUS: status,
        FieldName.GRADE: letter,
        FieldName.SCORE: score,
        FieldName.SCORE_PCT: round(score * 100, 1) if score is not None else None,
        FieldName.TIER: tier,
        FieldName.PROMOTED: graded and tier == TIER_PROMOTED,
        FieldName.EVENT_COUNT: int(heartbeat.get(FieldName.EVENT_COUNT) or 0),
        FieldName.TOTAL_RUNS: len(runs),
        FieldName.COMPLETED_RUNS: completed,
        FieldName.FAILED_RUNS: failed,
        FieldName.DIMENSIONS: [
            {
                FieldName.KEY: d.key,
                FieldName.LABEL: _DIM_LABELS[d.key],
                FieldName.VALUE: round(d.value, 4),
                FieldName.WEIGHT: _DIM_WEIGHTS[d.key],
                FieldName.DATA_AVAILABLE: d.available,
            }
            for d in dims.values()
        ],
        FieldName.LEARNINGS: _build_learnings(
            heartbeat, dims, completed, failed, terminal, p95_latency, graded
        ),
    }


async def _collect() -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Gather heartbeat-by-agent and runs-by-agent, mode-agnostically."""
    status_payload = await get_agents_status_payload()
    heartbeats: dict[str, dict[str, Any]] = {
        str(hb.get(FieldName.NAME)): hb
        for hb in status_payload.get(FieldName.AGENTS, [])
        if hb.get(FieldName.NAME)
    }

    metrics_payload = await get_agent_metrics_payload()
    runs_by_agent: dict[str, list[dict[str, Any]]] = {name: [] for name in ALL_AGENT_NAMES}
    for run in metrics_payload.get(FieldName.RUNS, []):
        agent = SOURCE_TO_AGENT.get(str(run.get(FieldName.SOURCE) or ""))
        if agent is not None:
            runs_by_agent[agent].append(run)
    return heartbeats, runs_by_agent


def _mode() -> str:
    return "db" if is_db_available() else "memory"


async def get_agent_performance_payload() -> dict[str, Any]:
    """Grade every pipeline agent — the overview the dashboard table renders."""
    heartbeats, runs_by_agent = await _collect()
    agents = [
        _grade_agent(name, heartbeats.get(name, {}), runs_by_agent.get(name, []))
        for name in ALL_AGENT_NAMES
    ]
    promoted = sum(1 for a in agents if a[FieldName.PROMOTED])
    return {
        FieldName.AGENTS: agents,
        FieldName.PROMOTED: promoted,
        FieldName.MODE: _mode(),
        FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
    }


async def get_agent_detail_payload(agent_name: str) -> dict[str, Any]:
    """Full drill-in for one agent: grade, dimensions, learnings, recent activity.

    Returns ``{"error": ...}`` for an unknown agent so the route can 404.
    """
    if agent_name not in ALL_AGENT_NAMES:
        return {FieldName.ERROR: "unknown_agent", FieldName.NAME: agent_name}

    heartbeats, runs_by_agent = await _collect()
    heartbeat = heartbeats.get(agent_name, {})
    runs = runs_by_agent.get(agent_name, [])

    detail = _grade_agent(agent_name, heartbeat, runs)
    detail[FieldName.HEARTBEAT] = {
        FieldName.STATUS: heartbeat.get(FieldName.STATUS),
        FieldName.EVENT_COUNT: heartbeat.get(FieldName.EVENT_COUNT),
        FieldName.LAST_EVENT: heartbeat.get(FieldName.LAST_EVENT),
        FieldName.LAST_SEEN: heartbeat.get(FieldName.LAST_SEEN),
        FieldName.SECONDS_AGO: heartbeat.get(FieldName.SECONDS_AGO),
    }
    detail[FieldName.RECENT_ACTIVITY] = _recent_activity(agent_name, runs)
    detail[FieldName.MODE] = _mode()
    detail[FieldName.TIMESTAMP] = datetime.now(timezone.utc).isoformat()
    return detail
