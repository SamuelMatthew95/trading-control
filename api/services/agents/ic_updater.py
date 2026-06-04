"""ICUpdater — Spearman-based alpha factor reweighting from realized performance."""

from __future__ import annotations

import json
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from api.config import settings
from api.constants import (
    AGENT_IC_UPDATER,
    REDIS_IC_WEIGHTS_TTL_SECONDS,
    REDIS_KEY_IC_WEIGHTS,
    SOURCE_IC_UPDATER,
    STREAM_FACTOR_IC_HISTORY,
    STREAM_NOTIFICATIONS,
    STREAM_TRADE_COMPLETED,
    STREAM_TRADE_PERFORMANCE,
    FieldName,
    Severity,
)
from api.database import AsyncSessionFactory
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.runtime_state import is_db_available
from api.services.agent_heartbeat import write_heartbeat as _write_heartbeat
from api.services.agent_state import AgentStateRegistry
from api.services.agents.base import MultiStreamAgent
from api.services.agents.db_helpers import (
    persist_factor_ic,
)
from api.services.agents.scoring import (
    spearman_correlation,
)

# ---------------------------------------------------------------------------
# ICUpdater — Spearman-based alpha factor reweighting
# ---------------------------------------------------------------------------


class ICUpdater(MultiStreamAgent):
    """Reweights alpha factors using Spearman IC against realized returns.

    Zeros factors below IC_ZERO_THRESHOLD, then normalizes remaining weights to 1.0.
    Writes updated weights to Redis key ``alpha:ic_weights``.
    """

    _state_name = AGENT_IC_UPDATER

    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        redis_client: Redis,
        *,
        agent_state: AgentStateRegistry | None = None,
    ) -> None:
        super().__init__(
            bus,
            dlq,
            streams=[STREAM_TRADE_PERFORMANCE, STREAM_TRADE_COMPLETED],
            consumer="ic-updater",
            agent_state=agent_state,
        )
        self.redis = redis_client
        self._fills = 0
        self._score_pnl_buffer: deque[tuple[float, float]] = deque(maxlen=200)

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        self._fills += 1
        pnl = float(data.get(FieldName.PNL) or 0.0)
        composite_score = await self._fetch_composite_score(data.get(FieldName.TRACE_ID))
        self._score_pnl_buffer.append((composite_score, pnl))

        trigger = max(int(settings.IC_UPDATE_EVERY_N_FILLS), 1)
        if self._fills % trigger != 0:
            try:
                await _write_heartbeat(
                    self.redis,
                    self._state_name,
                    f"fill_buffered:{self._fills}/{trigger}",
                    self._fills,
                    extra={FieldName.EXEC_STATUS: "idle:buffering"},
                )
            except Exception:
                log_structured("warning", "ic_updater_idle_heartbeat_failed", exc_info=True)
            return

        await self._recompute_and_publish()

    async def _fetch_composite_score(self, trace_id: str | None) -> float:
        """Look up the composite_score from agent_runs for this trace_id."""
        if not trace_id or not is_db_available():
            return 0.5
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("""
                        SELECT (signal_data::jsonb->>'composite_score')::float
                        FROM agent_runs WHERE trace_id = :trace_id LIMIT 1
                    """),
                    {"trace_id": trace_id},
                )
                val = result.scalar()
                return float(val) if val is not None else 0.5
        except Exception:
            return 0.5

    async def _recompute_and_publish(self) -> None:
        """Compute IC per factor, zero weak ones, normalize, write to Redis and DB."""
        lookback_n = min(len(self._score_pnl_buffer), 100)
        recent = list(self._score_pnl_buffer)[-lookback_n:]

        if len(recent) < 3:
            log_structured("info", "ic_updater_insufficient_data", fills=self._fills)
            return

        scores = [p[0] for p in recent]
        pnls = [p[1] for p in recent]

        composite_ic = spearman_correlation(scores, pnls)
        momentum_signals = [1.0 if s > 0.5 else -1.0 for s in scores]
        momentum_ic = spearman_correlation(momentum_signals, pnls)

        raw_factors: dict[str, float] = {
            "composite_score": composite_ic,
            FieldName.MOMENTUM: momentum_ic,
        }

        threshold = float(settings.IC_ZERO_THRESHOLD)
        active = {f: max(ic, 0.0) for f, ic in raw_factors.items() if abs(ic) > threshold}

        total = sum(active.values())
        weights: dict[str, float] = (
            {"composite_score": 1.0}
            if total <= 0
            else {k: round(v / total, 6) for k, v in active.items()}
        )

        await self.redis.set(
            REDIS_KEY_IC_WEIGHTS, json.dumps(weights), ex=REDIS_IC_WEIGHTS_TTL_SECONDS
        )

        log_structured(
            "info",
            "ic_weights_updated",
            weights=weights,
            composite_ic=composite_ic,
            momentum_ic=momentum_ic,
            fills=self._fills,
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        for factor, ic_val in raw_factors.items():
            await self.bus.publish(
                STREAM_FACTOR_IC_HISTORY,
                {
                    "msg_id": str(uuid.uuid4()),
                    "source": SOURCE_IC_UPDATER,
                    "type": "ic_update",
                    "factor_name": factor,
                    FieldName.IC_SCORE: round(ic_val, 6),
                    FieldName.WEIGHT: weights.get(factor, 0.0),
                    FieldName.FILLS: self._fills,
                    "timestamp": now_iso,
                },
            )
            await persist_factor_ic(factor, ic_val, now_iso)

        await self.bus.publish(
            STREAM_NOTIFICATIONS,
            {
                "msg_id": str(uuid.uuid4()),
                "source": SOURCE_IC_UPDATER,
                "type": "notification",
                "severity": Severity.INFO,
                "notification_type": "ic_update",
                "message": (
                    f"IC weights updated after {self._fills} fills — "
                    f"composite={composite_ic:+.3f} momentum={momentum_ic:+.3f}"
                ),
                FieldName.WEIGHTS: weights,
                "timestamp": now_iso,
            },
        )

        # Write heartbeat so dashboard shows IC_UPDATER as ACTIVE
        try:
            await _write_heartbeat(
                self.redis,
                self._state_name,
                f"ic_update fills={self._fills} composite_ic={composite_ic:+.3f}",
                self._fills,
                extra={FieldName.COMPOSITE_IC: round(composite_ic, 4), FieldName.WEIGHTS: weights},
            )
        except Exception:
            log_structured("warning", "ic_updater_heartbeat_failed", exc_info=True)
