"""AGENT REGISTRY — central discovery. Agents never import one another.

Every cognitive agent registers here with its role and the event type it emits.
The orchestration loop and the UI discover agents THROUGH the registry rather
than hard-wiring imports, so adding an agent is a one-line registration and the
observability layer lists the roster automatically. Decoupling agents this way
also keeps the "no agent imports another agent directly" rule structural, not
just a convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cognitive.agents import MacroAgent, NewsAgent, ReasoningAgent, RiskAgent, TechnicalAgent
from cognitive.events import EventType
from cognitive.proposal import ProposalAgent

ROLE_SIGNAL = "signal"
ROLE_REASONING = "reasoning"
ROLE_PROPOSAL = "proposal"


@dataclass(frozen=True)
class AgentSpec:
    """Registry record describing one agent (for discovery / UI listing)."""

    name: str
    role: str
    emits: str
    description: str
    instance: Any

    def describe(self) -> dict[str, str]:
        return {
            "name": self.name,
            "role": self.role,
            "emits": self.emits,
            "description": self.description,
        }


class AgentRegistry:
    """Ordered, de-duplicated catalog of cognitive agents."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentSpec] = {}

    def register(self, instance: Any, *, role: str, emits: str, description: str) -> AgentSpec:
        """Register (or replace) an agent by its ``name`` attribute."""
        spec = AgentSpec(
            name=instance.name, role=role, emits=emits, description=description, instance=instance
        )
        self._agents[spec.name] = spec
        return spec

    def get(self, name: str) -> AgentSpec | None:
        return self._agents.get(name)

    def all(self) -> list[AgentSpec]:
        return list(self._agents.values())

    def by_role(self, role: str) -> list[AgentSpec]:
        return [spec for spec in self._agents.values() if spec.role == role]

    def names(self) -> list[str]:
        return list(self._agents.keys())

    def describe(self) -> list[dict[str, str]]:
        """UI-facing roster of every registered agent."""
        return [spec.describe() for spec in self._agents.values()]


def build_default_registry() -> AgentRegistry:
    """The standard five cognitive specialists plus the Proposal architect."""
    registry = AgentRegistry()
    registry.register(
        NewsAgent(),
        role=ROLE_SIGNAL,
        emits=EventType.NEWS_SIGNAL.value,
        description="Sentiment extraction from news -> sentiment in [-1, 1].",
    )
    registry.register(
        TechnicalAgent(),
        role=ROLE_SIGNAL,
        emits=EventType.TECH_SIGNAL.value,
        description="Trend / indicator interpretation -> trend in [-1, 1].",
    )
    registry.register(
        MacroAgent(),
        role=ROLE_SIGNAL,
        emits=EventType.MACRO_SIGNAL.value,
        description="Regime detection -> regime in [-1, 1].",
    )
    registry.register(
        RiskAgent(),
        role=ROLE_SIGNAL,
        emits=EventType.RISK_SIGNAL.value,
        description="Risk annotation only -> risk_flags + risk_score in [0, 1].",
    )
    registry.register(
        ReasoningAgent(),
        role=ROLE_REASONING,
        emits=EventType.REASONING.value,
        description="Human-readable explanation layer; makes no decision.",
    )
    registry.register(
        ProposalAgent(),
        role=ROLE_PROPOSAL,
        emits=EventType.PROPOSAL.value,
        description="System architect: turns observations into typed candidate changes.",
    )
    return registry
