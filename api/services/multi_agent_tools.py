"""Tool execution and document retrieval for the multi-agent orchestrator."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from api.constants import FieldName
from api.services.multi_agent_memory import MemoryGuard
from api.services.multi_agent_models import ToolError


class DocumentRetriever:
    """Tiny local retriever for grounding outputs in checked-in references."""

    def __init__(self, root: str = "skills/trade-bot/references"):
        self.root = Path(root)
        self.documents: dict[str, str] = {}
        if self.root.exists():
            for path in self.root.glob("*.md"):
                self.documents[path.name] = path.read_text(encoding="utf-8")

    def retrieve(self, query: str, *, top_k: int = 2) -> list[dict[str, str]]:
        scored: list[tuple[int, str, str]] = []
        q_terms = {term.lower() for term in query.split() if len(term) > 2}
        for name, doc_text in self.documents.items():
            lower = doc_text.lower()
            score = sum(1 for term in q_terms if term in lower)
            if score:
                scored.append((score, name, doc_text[:500]))
        scored.sort(reverse=True)
        return [
            {FieldName.SOURCE: name, FieldName.SNIPPET: snippet}
            for _, name, snippet in scored[:top_k]
        ]


class TradeTools:
    def __init__(
        self,
        *,
        allowed_assets: set[str] | None = None,
        price_provider: Callable[[str], float] | None = None,
        max_retries: int = 2,
        circuit_breaker_threshold: int = 3,
    ):
        self.allowed_assets = allowed_assets or {"AAPL", "MSFT", "GOOGL", "TSLA"}
        self.price_provider = price_provider or (
            lambda asset: {
                "AAPL": 150.25,
                "MSFT": 380.5,
                "GOOGL": 2800.0,
                "TSLA": 250.0,
            }[asset]
        )
        self.max_retries = max_retries
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.failure_count = 0
        self.circuit_open = False
        self.memory_guard = MemoryGuard()
        self.guard_hits = 0

    def _guard(self, tool_name: str, payload: dict[str, Any]) -> None:
        match = self.memory_guard.check(tool_name, payload)
        if not match:
            return
        self.guard_hits += 1
        reason = match.get(FieldName.REASON, "blocked")
        raise ToolError(f"skipped_by_memory_guard:{reason}")

    def get_current_price(self, asset: str) -> float:
        self._guard("get_current_price", {FieldName.ASSET: asset})
        if self.circuit_open:
            raise ToolError("Price tool circuit breaker is open")
        if asset not in self.allowed_assets:
            raise ToolError(f"Asset '{asset}' blocked by tool guardrail")
        for _ in range(self.max_retries + 1):
            try:
                price = float(self.price_provider(asset))
                self.failure_count = 0
                return price
            except Exception as exc:  # noqa: BLE001
                self.failure_count += 1
                if self.failure_count >= self.circuit_breaker_threshold:
                    self.circuit_open = True
                last_error = exc
        raise ToolError(f"Price lookup failed after retries: {last_error}")

    def get_atr(self, asset: str, timeframe: str) -> float:
        self._guard("get_atr", {FieldName.ASSET: asset, FieldName.TIMEFRAME: timeframe})
        if timeframe not in {"1H", "4H", "1D", "1W"}:
            raise ToolError(f"Unsupported timeframe '{timeframe}'")
        _ = asset
        return 5.0
