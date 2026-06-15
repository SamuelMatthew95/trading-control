"""Durable per-agent realized-PnL accumulator (Redis-backed).

The piece that lets the dashboard grade the *trading* agents on whether they
actually make money — not just whether they are alive and fast.

**Why Redis, not InMemoryStore or Postgres.** This state must survive process
restarts and redeploys (an agent's track record can't reset every cold start),
and this deployment has **no Postgres**. Redis is already a hard dependency and
persists across restarts/deploys, so it is the only correct home. InMemoryStore
is explicitly NOT used here — it is wiped on restart, which would silently reset
every agent's record (the "bad in-memory state" failure mode).

Each agent gets one small Redis hash ``agent:pnl:{name}``:

    trade_count   total closed trades attributed to this agent
    win_count     of those, how many closed in profit
    total_pnl     summed realized PnL (float)
    updated_at    ISO-8601 of the last attribution

Reads degrade to ``None`` (→ "no data", never a fabricated number) so the
grader treats an agent with no closed trades as UNRATED on PnL rather than 0%.
"""

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis

from api.constants import REDIS_KEY_AGENT_PNL, FieldName
from api.observability import log_structured
from api.utils import bytes_to_text, now_iso


def _win_rate(trade_count: int, win_count: int) -> float:
    return (win_count / trade_count) if trade_count > 0 else 0.0


class AgentPnLStore:
    """Redis hash per agent accumulating realized-PnL outcomes. Durable, bounded
    (one tiny hash per agent), and safe under concurrent writers (atomic HINCR*)."""

    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def record_trade(self, agent_name: str, pnl: float) -> None:
        """Attribute one closed trade's realized PnL to *agent_name*.

        Atomic increments so concurrent GradeAgent attributions can't race. Best-
        effort: a Redis hiccup is logged and swallowed — never break grading."""
        key = REDIS_KEY_AGENT_PNL.format(name=agent_name)
        try:
            pipe = self.redis.pipeline()
            pipe.hincrby(key, FieldName.TRADE_COUNT, 1)
            if pnl > 0:
                pipe.hincrby(key, FieldName.WIN_COUNT, 1)
            pipe.hincrbyfloat(key, FieldName.TOTAL_PNL, float(pnl))
            pipe.hset(key, FieldName.UPDATED_AT, now_iso())
            await pipe.execute()
        except Exception:
            log_structured("warning", "agent_pnl_record_failed", agent=agent_name, exc_info=True)

    async def get_stats(self, agent_name: str) -> dict[str, Any] | None:
        """Realized-PnL stats for one agent, or ``None`` when it has no trades."""
        key = REDIS_KEY_AGENT_PNL.format(name=agent_name)
        try:
            raw = await self.redis.hgetall(key)
        except Exception:
            log_structured("warning", "agent_pnl_read_failed", agent=agent_name, exc_info=True)
            return None
        return _coerce_stats(raw)

    async def get_all(self, agent_names: list[str]) -> dict[str, dict[str, Any]]:
        """Stats for each named agent that has any (absent agents are omitted)."""
        out: dict[str, dict[str, Any]] = {}
        for name in agent_names:
            stats = await self.get_stats(name)
            if stats is not None:
                out[name] = stats
        return out


def _coerce_stats(raw: Any) -> dict[str, Any] | None:
    """Turn a raw Redis hash into typed stats, or ``None`` when empty/invalid."""
    if not raw:
        return None
    # redis-py may return bytes keys/values depending on decode settings.
    decoded: dict[str, str] = {bytes_to_text(k): bytes_to_text(v) for k, v in raw.items()}
    try:
        trade_count = int(decoded.get(FieldName.TRADE_COUNT, 0) or 0)
        win_count = int(decoded.get(FieldName.WIN_COUNT, 0) or 0)
        total_pnl = float(decoded.get(FieldName.TOTAL_PNL, 0.0) or 0.0)
    except (TypeError, ValueError):
        return None
    if trade_count <= 0:
        return None
    return {
        FieldName.TRADE_COUNT: trade_count,
        FieldName.WIN_COUNT: win_count,
        FieldName.WIN_RATE: round(_win_rate(trade_count, win_count), 4),
        FieldName.TOTAL_PNL: round(total_pnl, 4),
        FieldName.UPDATED_AT: decoded.get(FieldName.UPDATED_AT),
    }


_agent_pnl_store: AgentPnLStore | None = None


def set_agent_pnl_store(store: AgentPnLStore | None) -> None:
    """Install (or clear) the process-wide PnL store. Called once at startup."""
    global _agent_pnl_store
    _agent_pnl_store = store


def get_agent_pnl_store() -> AgentPnLStore | None:
    """Return the process-wide PnL store, or ``None`` before it is installed.

    Callers MUST treat ``None`` as "no PnL data" and degrade — never raise."""
    return _agent_pnl_store
