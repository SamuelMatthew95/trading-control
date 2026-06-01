"""Deterministic, event-stream-driven multi-agent cognitive trading brain.

This package wires the system the spec describes into ONE closed loop on a
single event stream (:mod:`cognitive.events`):

    market -> agents (news/tech/macro/risk/reasoning) -> feature aggregation
        -> deterministic decision engine -> risk gate -> execution
        -> learning (attribution + grading) -> proposal -> challenger
        -> backtest gate -> GitOps PR  ->  (merge)  ->  config  ->  market ...

Integrity rules enforced by construction:
  * Agents are advisory cognitive specialists; they never decide trades.
  * The decision engine is pure math (score = Σ signalᵢ·weightᵢ); no LLM/agent
    can influence it.
  * Behaviour changes ONLY via Proposal → Challenger → Backtest → Git PR; the
    backtest is the judge and every proposal must carry its PnL/Sharpe deltas.
  * Nothing computes durable state off the event stream, so the UI is a pure
    read-only mirror and the whole brain is reproducible.

It lives outside ``api/`` (like ``backtest/``) on purpose — it is the decision
core, not request-path code — and depends on no Redis, DB, or network.
"""

from cognitive.config import DEFAULT_CONFIG, CognitiveConfig, load_config
from cognitive.events import Event, EventStream, EventType

__all__ = [
    "DEFAULT_CONFIG",
    "CognitiveConfig",
    "Event",
    "EventStream",
    "EventType",
    "load_config",
]
