"""Data models and shared helpers for the multi-agent orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Direction = Literal["LONG", "SHORT", "FLAT"]


@dataclass
class AgentCall:
    agent_name: str
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    timestamp: datetime
    success: bool
    error: str | None = None
    duration_ms: int = 0


@dataclass
class PlanStep:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class TradePlan:
    asset: str
    timeframe: str
    steps: list[PlanStep]


class ToolError(RuntimeError):
    """Tool execution failed validation or guardrails."""


def _to_sync_db_url(raw_url: str) -> str:
    if raw_url.startswith("sqlite+aiosqlite://"):
        return raw_url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    if raw_url.startswith("postgresql+asyncpg://"):
        return raw_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return raw_url
