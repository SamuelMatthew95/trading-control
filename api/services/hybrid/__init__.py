"""Hybrid trading-decision pipeline.

Deterministic code owns market validation, signal generation, risk checks,
position sizing, execution hand-off, and ledger truth. LLMs only analyze and
recommend — they can never approve or place a trade.

Flow:
    market data
      → market_validator   (deterministic, blocks before any LLM call)
      → signal_engine      (deterministic indicators)
      → candidate_gate     (deterministic, blocks weak setups before LLM)
      → llm_decision       (fast instruct model → strict JSON)
      → llm_decision       (reasoning review model — only when needed)
      → risk_engine        (deterministic final authority)
      → position_sizing    (deterministic qty)
      → pipeline           (orchestrates + emits durable lifecycle events)

The orchestrator never calls the broker; it produces an approved, sized order
and emits lifecycle events. The existing ExecutionEngine remains the only
component allowed to place orders.
"""

from api.services.hybrid.pipeline import HybridDecisionPipeline

__all__ = ["HybridDecisionPipeline"]
