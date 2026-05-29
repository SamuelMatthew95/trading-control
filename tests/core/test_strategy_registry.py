"""Tests for the versioned strategy registry + lifecycle state machine."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from api.constants import StrategyStatus
from api.services.strategy_registry import InvalidTransitionError, StrategyRegistry

_TO_LIVE = (
    StrategyStatus.BACKTESTED,
    StrategyStatus.SHADOW,
    StrategyStatus.CANARY,
    StrategyStatus.LIVE,
)


def _advance(reg: StrategyRegistry, version_id: str, stages) -> None:
    for stage in stages:
        reg.transition(version_id, stage)


def test_register_creates_immutable_proposed_version():
    reg = StrategyRegistry()
    sv = reg.register({"strategy": "strong_only"})
    assert reg.status(sv.version_id) == StrategyStatus.PROPOSED
    assert sv.version == 1
    with pytest.raises(FrozenInstanceError):
        sv.version = 2  # type: ignore[misc]


def test_cannot_skip_stages():
    reg = StrategyRegistry()
    sv = reg.register({"a": 1})
    with pytest.raises(InvalidTransitionError):
        reg.transition(sv.version_id, StrategyStatus.LIVE)  # proposed -> live forbidden


def test_full_lifecycle_to_live():
    reg = StrategyRegistry()
    sv = reg.register({"a": 1})
    _advance(reg, sv.version_id, _TO_LIVE)
    assert reg.current_live().version_id == sv.version_id


def test_single_live_invariant_and_lineage():
    reg = StrategyRegistry()
    v1 = reg.register({"a": 1})
    _advance(reg, v1.version_id, _TO_LIVE)
    v2 = reg.register({"a": 2}, parent_version=v1.version)
    _advance(reg, v2.version_id, _TO_LIVE)
    assert reg.current_live().version_id == v2.version_id
    assert reg.status(v1.version_id) == StrategyStatus.RETIRED  # superseded
    assert v2.parent_version == v1.version
    assert v2.lineage == (v1.version, v2.version)


def test_rollback_restores_previous_live():
    reg = StrategyRegistry()
    v1 = reg.register({"a": 1})
    _advance(reg, v1.version_id, _TO_LIVE)
    v2 = reg.register({"a": 2})
    _advance(reg, v2.version_id, _TO_LIVE)
    restored = reg.rollback()
    assert restored is not None
    assert restored.version_id == v1.version_id
    assert reg.current_live().version_id == v1.version_id
    assert reg.status(v2.version_id) == StrategyStatus.RETIRED


def test_retired_is_terminal():
    reg = StrategyRegistry()
    sv = reg.register({"a": 1})
    reg.transition(sv.version_id, StrategyStatus.RETIRED)
    with pytest.raises(InvalidTransitionError):
        reg.transition(sv.version_id, StrategyStatus.BACKTESTED)
