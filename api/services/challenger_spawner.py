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

from api.constants import FieldName
from api.observability import log_structured


class ChallengerSpawner:
    """Starts ChallengerAgents at runtime and appends them to the live fleet."""

    def __init__(self, bus: Any, dlq: Any, agents: list[Any], agent_state: Any = None) -> None:
        self.bus = bus
        self.dlq = dlq
        self.agents = agents  # shared reference to app.state.agents
        self.agent_state = agent_state

    async def spawn(
        self, challenger_config: dict[str, Any] | None = None, max_fills: int | None = None
    ) -> dict[str, Any]:
        """Instantiate, start, and register a ChallengerAgent. Returns its descriptor."""
        from api.services.agents.pipeline_agents import ChallengerAgent  # noqa: PLC0415

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
