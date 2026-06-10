"""Dynamic challenger spawning — one place that starts a shadow ChallengerAgent.

A challenger runs an EXISTING strategy (from ``backtest.strategies.STRATEGIES``)
in shadow on the live streams — pure config, no code, no deploy. Both the
dashboard ``/challengers/spawn`` route and the ProposalApplier (on an approved
``NEW_AGENT`` proposal) go through this single spawner so the spawn logic lives
in exactly one place.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from api.constants import MAX_CONCURRENT_CHALLENGERS, FieldName
from api.observability import log_structured


class ChallengerSpawner:
    """Starts ChallengerAgents at runtime and appends them to the live fleet.

    Guardrails (both enforced here so EVERY spawn path gets them):
      * one RUNNING challenger per strategy — an auto-applied promotion spawns
        a candidate of the winning strategy, and that candidate later proposes
        promotion again; without dedup each cycle appended another clone of
        the same strategy to the fleet, without bound;
      * a hard cap on concurrently running challengers
        (``MAX_CONCURRENT_CHALLENGERS``) so even distinct strategies cannot
        crowd the fleet.
    """

    def __init__(self, bus: Any, dlq: Any, agents: list[Any], agent_state: Any = None) -> None:
        self.bus = bus
        self.dlq = dlq
        self.agents = agents  # shared reference to app.state.agents
        self.agent_state = agent_state

    def _running_challengers(self) -> list[Any]:
        from api.services.agents.pipeline_agents import ChallengerAgent  # noqa: PLC0415

        return [a for a in self.agents if isinstance(a, ChallengerAgent) and a._running]

    @staticmethod
    def _strategy_of(challenger_config: dict[str, Any] | None) -> str:
        return str((challenger_config or {}).get(FieldName.STRATEGY) or "")

    async def spawn(
        self, challenger_config: dict[str, Any] | None = None, max_fills: int | None = None
    ) -> dict[str, Any]:
        """Instantiate, start, and register a ChallengerAgent. Returns its descriptor.

        Returns the EXISTING challenger's descriptor with ``status:
        "already_running"`` when one for the same strategy is live, and a
        ``status: "capacity"`` refusal when the concurrency cap is reached —
        callers treat both as a successful no-op, never an error.
        """
        from api.services.agents.pipeline_agents import ChallengerAgent  # noqa: PLC0415

        running = self._running_challengers()
        strategy = self._strategy_of(challenger_config)
        if strategy:
            for existing in running:
                if self._strategy_of(existing._config) == strategy:
                    log_structured(
                        "info",
                        "challenger_spawn_deduplicated",
                        strategy=strategy,
                        challenger_id=existing._challenger_id,
                    )
                    return {
                        FieldName.CHALLENGER_ID: existing._challenger_id,
                        FieldName.INSTANCE_ID: existing._instance_id,
                        FieldName.CONSUMER: existing.consumer,
                        FieldName.MAX_FILLS: existing._max_fills,
                        FieldName.STATUS: "already_running",
                        FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                    }
        if len(running) >= MAX_CONCURRENT_CHALLENGERS:
            log_structured(
                "warning",
                "challenger_spawn_refused_capacity",
                strategy=strategy,
                running=len(running),
                cap=MAX_CONCURRENT_CHALLENGERS,
            )
            return {
                FieldName.STATUS: "capacity",
                FieldName.REASON: (
                    f"{len(running)} challengers already running (cap {MAX_CONCURRENT_CHALLENGERS})"
                ),
                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            }

        resolved_fills = int(max_fills or ChallengerAgent.DEFAULT_MAX_FILLS)
        challenger = ChallengerAgent(
            self.bus,
            self.dlq,
            challenger_config=challenger_config or {},
            max_fills=resolved_fills,
            agent_state=self.agent_state,
        )
        await challenger.start()
        self.agents.append(challenger)
        log_structured(
            "info",
            "challenger_spawned",
            challenger_id=challenger._challenger_id,
            instance_id=challenger._instance_id,
            max_fills=resolved_fills,
        )
        return {
            FieldName.CHALLENGER_ID: challenger._challenger_id,
            FieldName.INSTANCE_ID: challenger._instance_id,
            FieldName.CONSUMER: challenger.consumer,
            FieldName.MAX_FILLS: resolved_fills,
            FieldName.STATUS: "spawned",
            FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
        }
