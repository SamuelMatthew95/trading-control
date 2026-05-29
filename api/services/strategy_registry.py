"""Versioned strategy registry + lifecycle state machine.

The spine of the safe-evolution layer. Every strategy version is immutable once
created (evolved like git commits, never mutated in place). A version advances
through the lifecycle ONE stage at a time — proposed -> backtested -> shadow ->
canary -> live -> retired — so nothing can jump straight to production. Exactly
one version is ``live`` at a time; promoting a new one supersedes the incumbent,
and ``rollback()`` restores the previous live version (the circuit breaker uses
it).

Pure and in-process: no DB, no Redis, no live capital. A singleton mirrors the
``get_redis_store`` pattern so the rest of the app shares one registry.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from api.constants import FieldName, StrategyStatus

# Allowed forward transitions. RETIRED is terminal and reachable from any stage
# (a strategy can always be pulled).
_VALID_TRANSITIONS: dict[StrategyStatus, frozenset[StrategyStatus]] = {
    StrategyStatus.PROPOSED: frozenset({StrategyStatus.BACKTESTED, StrategyStatus.RETIRED}),
    StrategyStatus.BACKTESTED: frozenset({StrategyStatus.SHADOW, StrategyStatus.RETIRED}),
    StrategyStatus.SHADOW: frozenset({StrategyStatus.CANARY, StrategyStatus.RETIRED}),
    StrategyStatus.CANARY: frozenset({StrategyStatus.LIVE, StrategyStatus.RETIRED}),
    StrategyStatus.LIVE: frozenset({StrategyStatus.RETIRED}),
    StrategyStatus.RETIRED: frozenset(),
}


class InvalidTransitionError(Exception):
    """Raised when a lifecycle transition would skip a stage or leave a terminal one."""


@dataclass(frozen=True)
class StrategyVersion:
    """Immutable identity of a strategy version — never changes once created."""

    version_id: str
    version: int
    parent_version: int | None
    config_hash: str
    config: dict[str, Any]
    lineage: tuple[int, ...]
    created_at: float


@dataclass
class StrategyRecord:
    """A version plus its (mutable) lifecycle status and transition history."""

    strategy: StrategyVersion
    status: StrategyStatus
    history: list[tuple[StrategyStatus, float]] = field(default_factory=list)


def _hash_config(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:16]


class StrategyRegistry:
    """In-process registry of immutable strategy versions and their lifecycle."""

    def __init__(self) -> None:
        self._records: dict[str, StrategyRecord] = {}
        self._next_version = 1
        self._live_stack: list[str] = []  # version_ids promoted to live; top = current

    def register(
        self, config: dict[str, Any], *, parent_version: int | None = None
    ) -> StrategyVersion:
        """Create and store a new immutable version at PROPOSED."""
        version = self._next_version
        self._next_version += 1
        parent = self._by_version(parent_version)
        lineage = (*(parent.strategy.lineage if parent else ()), version)
        sv = StrategyVersion(
            version_id=f"v{version}-{_hash_config(config)}",
            version=version,
            parent_version=parent_version,
            config_hash=_hash_config(config),
            config=dict(config),
            lineage=lineage,
            created_at=time.time(),
        )
        self._records[sv.version_id] = StrategyRecord(strategy=sv, status=StrategyStatus.PROPOSED)
        return sv

    def get(self, version_id: str) -> StrategyRecord | None:
        return self._records.get(version_id)

    def status(self, version_id: str) -> StrategyStatus | None:
        rec = self._records.get(version_id)
        return rec.status if rec else None

    def versions(self) -> list[StrategyVersion]:
        return [r.strategy for r in self._records.values()]

    def find_by_strategy(self, strategy_name: str) -> StrategyRecord | None:
        """Return the highest-version record for a strategy name, or None.

        Keeps lifecycle registration idempotent across the two producers that
        both want a candidate registered exactly once: the route's startup
        seeder and the shadow ChallengerAgents.
        """
        matches = [
            rec
            for rec in self._records.values()
            if rec.strategy.config.get(FieldName.STRATEGY) == strategy_name
        ]
        return max(matches, key=lambda r: r.strategy.version) if matches else None

    def transition(self, version_id: str, to_status: StrategyStatus) -> StrategyVersion:
        """Advance a version exactly one stage. Raises InvalidTransitionError on a skip."""
        rec = self._records.get(version_id)
        if rec is None:
            raise InvalidTransitionError(f"unknown version {version_id}")
        if to_status not in _VALID_TRANSITIONS[rec.status]:
            raise InvalidTransitionError(f"{rec.status.value} -> {to_status.value} is not allowed")
        if to_status == StrategyStatus.LIVE:
            self._supersede_current_live()
            self._live_stack.append(version_id)
        self._set_status(rec, to_status)
        return rec.strategy

    def current_live(self) -> StrategyVersion | None:
        for rec in self._records.values():
            if rec.status == StrategyStatus.LIVE:
                return rec.strategy
        return None

    def rollback(self) -> StrategyVersion | None:
        """Retire the current live version and restore the previous one.

        Used by the circuit breaker. Returns the restored version, or None when
        there is no prior live version to fall back to.
        """
        if not self._live_stack:
            return None
        current_id = self._live_stack.pop()
        self._set_status(self._records[current_id], StrategyStatus.RETIRED)
        if self._live_stack:
            prev = self._records[self._live_stack[-1]]
            self._set_status(prev, StrategyStatus.LIVE)
            return prev.strategy
        return None

    # -- internals --
    def _set_status(self, rec: StrategyRecord, status: StrategyStatus) -> None:
        rec.status = status
        rec.history.append((status, time.time()))

    def _supersede_current_live(self) -> None:
        if self._live_stack:
            self._set_status(self._records[self._live_stack[-1]], StrategyStatus.RETIRED)

    def _by_version(self, version: int | None) -> StrategyRecord | None:
        if version is None:
            return None
        for rec in self._records.values():
            if rec.strategy.version == version:
                return rec
        return None


_registry: StrategyRegistry | None = None


def get_strategy_registry() -> StrategyRegistry:
    """Return the process-wide registry, creating it on first use."""
    global _registry
    if _registry is None:
        _registry = StrategyRegistry()
    return _registry


def set_strategy_registry(registry: StrategyRegistry | None) -> None:
    """Replace the singleton (tests reset to a fresh registry)."""
    global _registry
    _registry = registry
