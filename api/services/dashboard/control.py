from typing import Any

from fastapi import HTTPException

from api.constants import (
    REDIS_KEY_KILL_SWITCH,
    REDIS_KEY_KILL_SWITCH_UPDATED_AT,
    FieldName,
)
from api.observability import log_structured
from api.redis_client import get_redis
from api.runtime_state import get_runtime_store, is_db_available
from api.services.challenger_spawner import ChallengerSpawner
from api.services.dashboard.state import hydrate_dashboard_state_from_redis
from api.utils import now_iso


async def spawn_challenger_payload(
    event_bus: Any,
    dlq_manager: Any,
    agents: list[Any],
    body: dict[str, Any],
) -> dict[str, Any]:
    """Spawn a new ChallengerAgent from an approved new_agent proposal."""
    spawner = ChallengerSpawner(event_bus, dlq_manager, agents)
    try:
        return await spawner.spawn(
            body.get(FieldName.CHALLENGER_CONFIG, {}), body.get(FieldName.MAX_FILLS)
        )
    except Exception:
        log_structured("error", "challenger_spawn_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


async def list_challengers_payload(agents: list[Any]) -> dict[str, Any]:
    """List all active challenger agent instances."""
    from api.services.agents.pipeline_agents import ChallengerAgent  # noqa: PLC0415

    try:
        challengers = [a for a in agents if isinstance(a, ChallengerAgent)]
        return {
            FieldName.CHALLENGERS: [
                {
                    FieldName.CHALLENGER_ID: c._challenger_id,
                    FieldName.INSTANCE_ID: c._instance_id,
                    FieldName.CONSUMER: c.consumer,
                    FieldName.FILLS: c._fills,
                    FieldName.MAX_FILLS: c._max_fills,
                    FieldName.CONFIG: c._config,
                    FieldName.STRATEGY: c._config.get(FieldName.STRATEGY) or "",
                    FieldName.RUNNING: c._running,
                    # Full connected challenger state: own-vs-baseline shadow
                    # evidence + liveness (last tick / last trade / ticks seen),
                    # promotion progress (min_shadow_trades threshold), recent
                    # shadow-trade flow, and the live self-grade if any. Lets the
                    # dashboard show what the CONFIG is doing and WHY — not just a
                    # fill counter and three frozen numbers.
                    **c.activity_snapshot(),
                }
                for c in challengers
            ],
            FieldName.COUNT: len(challengers),
            "timestamp": now_iso(),
        }
    except Exception:
        log_structured("error", "challengers_list_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


async def get_gitops_status_payload() -> dict[str, Any]:
    """Report whether auto-PR/issue creation is wired and the token actually
    reaches the repo — so an operator can confirm GitOps WITHOUT waiting for a
    trade→proposal→PR. Never raises."""
    from api.services.gitops_publisher import GitOpsPublisher  # noqa: PLC0415

    result = await GitOpsPublisher().verify_access()
    result[FieldName.TIMESTAMP] = now_iso()
    return result


async def get_kill_switch_payload() -> dict[str, Any]:
    """Get current kill switch state."""
    try:
        redis_client = await get_redis()
        value = await redis_client.get(REDIS_KEY_KILL_SWITCH)
        updated_at = await redis_client.get(REDIS_KEY_KILL_SWITCH_UPDATED_AT)
        return {
            FieldName.ACTIVE: value == "1",
            "updated_at": updated_at or now_iso(),
        }
    except Exception:
        log_structured("error", "kill_switch_read_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


async def toggle_kill_switch_payload(active: bool) -> dict[str, Any]:
    """Toggle the trading kill switch."""
    try:
        redis_client = await get_redis()
        await redis_client.set(REDIS_KEY_KILL_SWITCH, "1" if active else "0")
        await redis_client.set(REDIS_KEY_KILL_SWITCH_UPDATED_AT, now_iso())
        log_structured(
            "info",
            "kill_switch_toggled",
            active=active,
            timestamp=now_iso(),
        )
        return {
            FieldName.ACTIVE: active,
            "message": f"Kill switch {'activated' if active else 'deactivated'}",
            "timestamp": now_iso(),
        }
    except Exception:
        log_structured("error", "kill switch toggle failed", active=active, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


async def get_debug_state_payload() -> dict[str, Any]:
    """Debug snapshot from in-memory runtime store only."""
    store = get_runtime_store()
    diagnostics = await hydrate_dashboard_state_from_redis()
    snapshot = store.dashboard_fallback_snapshot()
    paired = store.paired_pnl_payload()
    paired_closed_trades = paired.get(FieldName.CLOSED_TRADES, [])
    paired_summary = paired.get(FieldName.SUMMARY, {})
    summary_closed_trades = int(paired_summary.get(FieldName.CLOSED_TRADES, 0) or 0)
    db_available = is_db_available()
    equity_curve = snapshot.get(FieldName.EQUITY_CURVE, [])
    open_positions_list = snapshot.get(FieldName.POSITIONS, [])
    decisions_list = snapshot.get(FieldName.DECISIONS, [])
    notifications_list = snapshot.get(FieldName.NOTIFICATIONS, [])
    has_data = bool(decisions_list or open_positions_list or snapshot.get(FieldName.ORDERS))
    return {
        FieldName.DB_AVAILABLE: db_available,
        FieldName.SOURCE: diagnostics[FieldName.SOURCE],
        FieldName.HAS_DATA: has_data,
        FieldName.LAST_ERROR: diagnostics[FieldName.LAST_ERROR],
        FieldName.LEDGER_SOURCE: diagnostics[FieldName.LEDGER_SOURCE],
        FieldName.PERSISTENCE_SOURCE: diagnostics[FieldName.PERSISTENCE_SOURCE],
        FieldName.SCOPE: "runtime_store",
        FieldName.RUNTIME_STORE: {
            FieldName.DECISIONS_COUNT: len(decisions_list),
            FieldName.NOTIFICATIONS_COUNT: len(notifications_list),
            FieldName.OPEN_POSITIONS: len(open_positions_list),
            FieldName.CLOSED_TRADES: summary_closed_trades,
            FieldName.EQUITY_POINTS: len(equity_curve),
        },
        "pnl": {
            FieldName.TOTAL_PNL: paired_summary.get(FieldName.TOTAL_PNL, 0.0),
            FieldName.REALIZED_PNL: paired_summary.get(FieldName.REALIZED_PNL, 0.0),
            "unrealized_pnl": paired_summary.get(FieldName.UNREALIZED_PNL, 0.0),
            "win_rate": round(paired_summary.get(FieldName.WIN_RATE_PERCENT, 0.0) / 100.0, 4),
            FieldName.ACTIVE_POSITIONS: paired_summary.get(FieldName.OPEN_POSITIONS, 0),
            FieldName.EQUITY_CURVE_POINTS: len(equity_curve),
        },
        FieldName.COUNTS: {
            FieldName.REDIS_HYDRATION_STATUS: diagnostics[FieldName.HYDRATION_STATUS],
            FieldName.REDIS_DECISIONS_SEEN: diagnostics[FieldName.REDIS_DECISIONS_SEEN],
            FieldName.REDIS_DECISIONS_APPLIED: diagnostics[FieldName.REDIS_DECISIONS_APPLIED],
            FieldName.REDIS_NOTIFICATIONS_SEEN: diagnostics[FieldName.REDIS_NOTIFICATIONS_SEEN],
            FieldName.REDIS_NOTIFICATIONS_APPLIED: diagnostics[
                FieldName.REDIS_NOTIFICATIONS_APPLIED
            ],
            FieldName.APPLIED_DECISION_KEYS: diagnostics[FieldName.APPLIED_DECISION_KEYS],
            FieldName.DECISIONS: len(decisions_list),
            FieldName.NOTIFICATIONS: len(notifications_list),
            FieldName.OPEN_POSITIONS: len(open_positions_list),
            FieldName.CLOSED_TRADES: summary_closed_trades,
            FieldName.EQUITY_POINTS: len(equity_curve),
        },
        FieldName.LATEST_DECISION: (decisions_list or [None])[0],
        FieldName.LATEST_NOTIFICATION: (notifications_list or [None])[0],
        FieldName.LATEST_OPEN_POSITION: (open_positions_list or [None])[0],
        FieldName.LATEST_CLOSED_TRADE: (paired_closed_trades or [None])[-1],
        "summary": paired_summary,
    }
