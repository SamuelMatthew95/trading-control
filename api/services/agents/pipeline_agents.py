"""Backwards-compatible re-export of the pipeline agents.

The pipeline agents were decomposed into one focused module per agent for
maintainability. This module preserves the original
``api.services.agents.pipeline_agents`` import path so existing call sites and
inline imports keep working unchanged.
"""

from __future__ import annotations

from api.services.agents.challenger_agent import ChallengerAgent
from api.services.agents.grade_agent import GradeAgent
from api.services.agents.ic_updater import ICUpdater
from api.services.agents.notification_agent import NotificationAgent
from api.services.agents.reflection_agent import ReflectionAgent
from api.services.agents.strategy_proposer import StrategyProposer

__all__ = [
    "ChallengerAgent",
    "GradeAgent",
    "ICUpdater",
    "NotificationAgent",
    "ReflectionAgent",
    "StrategyProposer",
]
