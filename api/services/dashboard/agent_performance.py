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

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from api.config import settings
from api.constants import (
    AGENT_GRADE_HISTORY_DISPLAY,
    AGENT_GRADE_HISTORY_MAX,
    AGENT_GRADE_SNAPSHOT_INTERVAL_SECONDS,
    AGENT_PERF_LIVENESS_ACTIVE,
    AGENT_PERF_LIVENESS_STALE,
    AGENT_PERF_THROUGHPUT_SATURATION,
    AGENT_PERF_W_LATENCY,
    AGENT_PERF_W_LIVENESS,
    AGENT_PERF_W_SUCCESS,
    AGENT_PERF_W_THROUGHPUT,
    AGENT_PROMOTION_STREAK,
    AGENT_TRUST_DEFAULT,
    AGENT_TRUST_MAX,
    AGENT_TRUST_MIN,
    ALL_AGENT_NAMES,
    CIRCUIT_BREAKER_MAX_LATENCY_MS,
    GRADE_TO_TIER,
    LEARNING_CONTROL_TTL_SECONDS,
    REDIS_KEY_AGENT_TRUST,
    SOURCE_TO_AGENT,
    TIER_PROMOTED,
    TIER_TO_TRUST,
    TIER_TRUSTED,
    TIER_UNRATED,
    FieldName,
    StatusValue,
)
from api.observability import log_structured
from api.redis_client import get_redis
from api.runtime_state import is_db_available
from api.services.agents.scoring import score_to_grade
from api.services.dashboard.agents import (
    get_agent_metrics_payload,
    get_agents_status_payload,
)
from api.services.redis_store import get_redis_store

# Letter grades that count toward a promotion streak.
_PROMOTION_GRADES = {"A", "A+"}

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
        # Base tier from the current window; _finalize_promotion may downgrade a
        # not-yet-sustained A/A+ to TRUSTED and set PROMOTED + GRADE_STREAK.
        FieldName.TIER: tier,
        FieldName.PROMOTED: False,
        FieldName.GRADE_STREAK: 0,
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


def _age_seconds(ts_iso: Any) -> float | None:
    """Seconds since an ISO-8601 timestamp; ``None`` if unparseable."""
    if ts_iso is None:
        return None
    try:
        ts = datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()


def _streak_from_history(history: list[dict[str, Any]]) -> int:
    """Consecutive A/A+ snapshots from newest backwards (history is newest-first)."""
    streak = 0
    for snapshot in history:
        if snapshot.get(FieldName.GRADE) in _PROMOTION_GRADES:
            streak += 1
        else:
            break
    return streak


def _should_record(history: list[dict[str, Any]], grade: str) -> bool:
    """Throttle snapshots — record on a grade change or once per interval."""
    if not history:
        return True
    latest = history[0]
    if latest.get(FieldName.GRADE) != grade:
        return True
    age = _age_seconds(latest.get(FieldName.TIMESTAMP))
    return age is None or age >= AGENT_GRADE_SNAPSHOT_INTERVAL_SECONDS


async def _read_trust(agent_name: str) -> float:
    """Current per-agent trust weight from the control plane (bounded)."""
    try:
        redis_client = await get_redis()
        raw = await redis_client.get(REDIS_KEY_AGENT_TRUST.format(name=agent_name))
        if raw is None:
            return AGENT_TRUST_DEFAULT
        return min(max(float(raw), AGENT_TRUST_MIN), AGENT_TRUST_MAX)
    except (TypeError, ValueError):
        return AGENT_TRUST_DEFAULT
    except Exception:
        log_structured("warning", "agent_trust_read_failed", exc_info=True)
        return AGENT_TRUST_DEFAULT


async def _finalize_promotion(
    store: Any,
    agent: dict[str, Any],
    *,
    include_history: bool,
) -> dict[str, Any]:
    """Refine an agent's tier using its durable grade streak (sustained → PROMOTED).

    READ-ONLY: it never writes history — the streak is built by the periodic
    ``record_grade_snapshots`` background task (single writer), so this read path
    (a dashboard GET) has no side effects and no writer race. A single A/A+
    window shows TRUSTED; only AGENT_PROMOTION_STREAK consecutive A/A+ snapshots
    earn PROMOTED. With no RedisStore installed it degrades to the current window.
    """
    name = agent[FieldName.NAME]
    grade = agent[FieldName.GRADE]
    base_tier = agent[FieldName.TIER]
    history: list[dict[str, Any]] = []

    if store is None:
        streak = 1 if grade in _PROMOTION_GRADES else 0
    else:
        history = await store.list_agent_grades(name, AGENT_GRADE_HISTORY_MAX)
        streak = _streak_from_history(history)

    promoted = grade in _PROMOTION_GRADES and streak >= AGENT_PROMOTION_STREAK
    if promoted:
        final_tier = TIER_PROMOTED
    elif grade in _PROMOTION_GRADES:
        # Earned an A/A+ but not yet sustained — pending promotion.
        final_tier = TIER_TRUSTED
    else:
        final_tier = base_tier

    agent[FieldName.TIER] = final_tier
    agent[FieldName.PROMOTED] = promoted
    agent[FieldName.GRADE_STREAK] = streak

    if include_history:
        agent[FieldName.HISTORY] = history[:AGENT_GRADE_HISTORY_DISPLAY]
        agent[FieldName.TRUST] = await _read_trust(name)
        agent[FieldName.TARGET_TRUST] = TIER_TO_TRUST.get(final_tier, AGENT_TRUST_DEFAULT)
    return agent


async def get_agent_performance_payload() -> dict[str, Any]:
    """Grade every pipeline agent — the overview the dashboard table renders."""
    heartbeats, runs_by_agent = await _collect()
    store = get_redis_store()
    agents: list[dict[str, Any]] = []
    for name in ALL_AGENT_NAMES:
        graded = _grade_agent(name, heartbeats.get(name, {}), runs_by_agent.get(name, []))
        agents.append(await _finalize_promotion(store, graded, include_history=False))
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
    detail = await _finalize_promotion(get_redis_store(), detail, include_history=True)
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


async def apply_agent_promotions_payload() -> dict[str, Any]:
    """Behavioral promotion (explicit operator action): write each agent's trust
    weight to the control plane from its current tier.

    The weight only changes live trading when AGENT_TRUST_WEIGHTING_ENABLED is
    on (ReasoningAgent reads it then); otherwise it is set but inert, so the UI
    can preview the effect safely. Writing is gated to this explicit POST — it is
    never a side effect of a dashboard GET.
    """
    perf = await get_agent_performance_payload()
    applied: list[dict[str, Any]] = []
    try:
        redis_client = await get_redis()
        for agent in perf[FieldName.AGENTS]:
            tier = agent[FieldName.TIER]
            trust = TIER_TO_TRUST.get(tier, AGENT_TRUST_DEFAULT)
            await redis_client.set(
                REDIS_KEY_AGENT_TRUST.format(name=agent[FieldName.NAME]),
                f"{trust:.4f}",
                ex=LEARNING_CONTROL_TTL_SECONDS,
            )
            applied.append(
                {
                    FieldName.NAME: agent[FieldName.NAME],
                    FieldName.TIER: tier,
                    FieldName.TRUST: trust,
                }
            )
    except Exception:
        log_structured("warning", "agent_promotion_apply_failed", exc_info=True)
        return {
            FieldName.APPLIED: [],
            FieldName.ENABLED: settings.AGENT_TRUST_WEIGHTING_ENABLED,
            FieldName.ERROR: "redis_unavailable",
            FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
        }

    return {
        FieldName.APPLIED: applied,
        FieldName.ENABLED: settings.AGENT_TRUST_WEIGHTING_ENABLED,
        FieldName.MODE: _mode(),
        FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
    }


async def record_grade_snapshots() -> int:
    """Append a throttled grade snapshot per agent — the SOLE writer of history.

    Run periodically by a background task so promotion streaks build over time
    regardless of whether anyone is viewing the dashboard. Throttled per agent
    (a snapshot is written on a grade change or once per
    AGENT_GRADE_SNAPSHOT_INTERVAL_SECONDS); ungraded/dormant agents are skipped.
    Returns the number of snapshots written.
    """
    store = get_redis_store()
    if store is None:
        return 0
    heartbeats, runs_by_agent = await _collect()
    recorded = 0
    for name in ALL_AGENT_NAMES:
        graded = _grade_agent(name, heartbeats.get(name, {}), runs_by_agent.get(name, []))
        grade = graded[FieldName.GRADE]
        if grade is None:
            continue
        history = await store.list_agent_grades(name, AGENT_GRADE_HISTORY_MAX)
        if not _should_record(history, grade):
            continue
        await store.record_agent_grade(
            name,
            {
                FieldName.GRADE: grade,
                FieldName.SCORE_PCT: graded[FieldName.SCORE_PCT],
                FieldName.TIER: graded[FieldName.TIER],
                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            },
        )
        recorded += 1
    return recorded


async def agent_grade_snapshot_loop() -> None:
    """Periodically record per-agent grade snapshots so streaks build autonomously."""
    while True:
        await asyncio.sleep(AGENT_GRADE_SNAPSHOT_INTERVAL_SECONDS)
        try:
            await record_grade_snapshots()
        except Exception:
            log_structured("warning", "agent_grade_snapshot_loop_failed", exc_info=True)
