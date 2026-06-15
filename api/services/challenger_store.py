"""Durable per-challenger shadow track record (Redis-backed).

The piece that makes a challenger's performance *survive restarts*. Each shadow
``ChallengerAgent`` runs its strategy (and the baseline) on the live tick stream
and accumulates ``ShadowMetrics`` — trades, wins, realized PnL, Sharpe. Until
this store existed those metrics lived ONLY in process memory, so every Render
cold start reset them to zero and a challenger could never reach the
``CHALLENGER_MIN_SHADOW_TRADES`` it needs to earn a promotion proposal. The loop
looked dead because the evidence kept evaporating.

**Why Redis, not InMemoryStore or Postgres.** Same reasoning as
``agent_pnl_store``: a track record cannot reset on cold start, this deployment
has no Postgres, and InMemoryStore is wiped on restart. Redis (no TTL) is the
only durable home.

Keyed by **strategy name**, not challenger_id — challenger_ids are random per
process (``uuid4()[:8]``), and startup spawns exactly one challenger per
strategy, so the strategy is the stable identity of a track record across
restarts.

Each strategy gets one small Redis hash ``challenger:perf:{strategy}``:

    pnls            JSON list of recent own shadow per-trade PnLs (capped)
    baseline_pnls   JSON list of recent baseline per-trade PnLs (capped)
    proposal_emitted "1" once this challenger has fired its promotion proposal
    graduated        "1" once an approved promotion graduated the strategy
    graduated_at     ISO-8601 of graduation
    updated_at       ISO-8601 of the last write

Reconstructing the full ``ShadowMetrics`` from the persisted ``pnls`` list keeps
the hydrated metrics internally consistent (trades/wins/realized_pnl/Sharpe all
derive from the same list), so warm-start performance is exactly what it would
have been had the process never restarted.

Reads degrade to ``None`` (→ cold start / no record) so callers never raise.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from api.constants import CHALLENGER_PERF_PNL_CAP, REDIS_KEY_CHALLENGER_PERF, FieldName
from api.observability import log_structured


class ChallengerStore:
    """Redis hash per strategy holding a challenger's durable shadow record.

    Durable (no TTL), bounded (one tiny hash per strategy, the PnL lists capped
    at ``CHALLENGER_PERF_PNL_CAP``), and safe under the single writer per
    strategy (the one running challenger of that strategy)."""

    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def save_performance(
        self,
        strategy: str,
        *,
        own_pnls: list[float],
        baseline_pnls: list[float],
        proposal_emitted: bool,
    ) -> None:
        """Persist the rolling shadow PnL lists + the promotion latch.

        Writes only these fields, so a concurrent ``mark_graduated`` (set by the
        ProposalApplier on approval) is never clobbered. Best-effort: a Redis
        hiccup is logged and swallowed — never break the shadow loop."""
        if not strategy:
            return
        key = REDIS_KEY_CHALLENGER_PERF.format(strategy=strategy)
        try:
            await self.redis.hset(
                key,
                mapping={
                    FieldName.PNLS: json.dumps(own_pnls[-CHALLENGER_PERF_PNL_CAP:]),
                    FieldName.BASELINE_PNLS: json.dumps(baseline_pnls[-CHALLENGER_PERF_PNL_CAP:]),
                    FieldName.PROPOSAL_EMITTED: "1" if proposal_emitted else "0",
                    FieldName.UPDATED_AT: datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:
            log_structured(
                "warning", "challenger_perf_save_failed", strategy=strategy, exc_info=True
            )

    async def mark_graduated(self, strategy: str) -> None:
        """Stamp a strategy as graduated (an approved promotion advanced it).

        Idempotent and independent of ``save_performance`` so the agent's
        per-close writes and the applier's one-shot graduation never race."""
        if not strategy:
            return
        key = REDIS_KEY_CHALLENGER_PERF.format(strategy=strategy)
        try:
            await self.redis.hset(
                key,
                mapping={
                    FieldName.GRADUATED: "1",
                    FieldName.GRADUATED_AT: datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:
            log_structured(
                "warning", "challenger_perf_graduate_failed", strategy=strategy, exc_info=True
            )

    async def load(self, strategy: str) -> dict[str, Any] | None:
        """Durable record for one strategy, or ``None`` when none exists yet."""
        if not strategy:
            return None
        key = REDIS_KEY_CHALLENGER_PERF.format(strategy=strategy)
        try:
            raw = await self.redis.hgetall(key)
        except Exception:
            log_structured(
                "warning", "challenger_perf_read_failed", strategy=strategy, exc_info=True
            )
            return None
        return _coerce_record(raw)


def _coerce_record(raw: Any) -> dict[str, Any] | None:
    """Turn a raw Redis hash into a typed record, or ``None`` when empty."""
    if not raw:
        return None
    decoded: dict[str, str] = {}
    for k, v in raw.items():
        key = k.decode() if isinstance(k, bytes) else str(k)
        val = v.decode() if isinstance(v, bytes) else str(v)
        decoded[key] = val
    return {
        FieldName.PNLS: _parse_floats(decoded.get(FieldName.PNLS)),
        FieldName.BASELINE_PNLS: _parse_floats(decoded.get(FieldName.BASELINE_PNLS)),
        FieldName.PROPOSAL_EMITTED: decoded.get(FieldName.PROPOSAL_EMITTED) == "1",
        FieldName.GRADUATED: decoded.get(FieldName.GRADUATED) == "1",
        FieldName.GRADUATED_AT: decoded.get(FieldName.GRADUATED_AT) or None,
        FieldName.UPDATED_AT: decoded.get(FieldName.UPDATED_AT) or None,
    }


def _parse_floats(raw: str | None) -> list[float]:
    """Decode a JSON float list, tolerating absence / corruption → []."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    out: list[float] = []
    for item in parsed:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out


_challenger_store: ChallengerStore | None = None


def set_challenger_store(store: ChallengerStore | None) -> None:
    """Install (or clear) the process-wide challenger store. Called at startup."""
    global _challenger_store
    _challenger_store = store


def get_challenger_store() -> ChallengerStore | None:
    """Return the process-wide challenger store, or ``None`` before install.

    Callers MUST treat ``None`` as "no durable record" and degrade — never raise."""
    return _challenger_store
