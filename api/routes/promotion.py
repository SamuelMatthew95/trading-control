"""Promotion / regression API — runs a candidate through the replay + gate.

``POST /learning/replay-regression`` replays champion and candidate trade sets
and returns the deterministic regression verdict the promotion gate uses. This
is the operator-facing surface for "would this challenger be safe to promote?".
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.services.regression_validator import RegressionValidator, RegressionVerdict
from api.services.replay_harness import ReplayHarness, ReplayMetrics

router = APIRouter(prefix="/learning", tags=["promotion"])


class ReplayRegressionRequest(BaseModel):
    champion_trades: list[dict[str, Any]] = Field(default_factory=list)
    candidate_trades: list[dict[str, Any]] = Field(default_factory=list)


class ReplayRegressionResponse(BaseModel):
    champion: ReplayMetrics
    candidate: ReplayMetrics
    verdict: RegressionVerdict


@router.post("/replay-regression", response_model=ReplayRegressionResponse)
async def replay_regression(req: ReplayRegressionRequest) -> ReplayRegressionResponse:
    harness = ReplayHarness()
    champion = harness.replay(req.champion_trades)
    candidate = harness.replay(req.candidate_trades)
    verdict = RegressionValidator().validate(champion, candidate)
    return ReplayRegressionResponse(champion=champion, candidate=candidate, verdict=verdict)
