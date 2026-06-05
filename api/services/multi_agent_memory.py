"""Memory and risk-guard components for the multi-agent orchestrator."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from api.constants import FieldName
from api.services.multi_agent_models import _to_sync_db_url


class MemoryGuard:
    def __init__(self, threshold: float = 0.82):
        self.threshold = threshold
        self.risk_memory_store: dict[str, int] = {}

    def check(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        db_url = _to_sync_db_url(os.getenv("DATABASE_URL", "sqlite:///./trading-control.db"))
        probe = f"{tool_name}:{json.dumps(payload, sort_keys=True)}"
        probe_embedding = self._embed(probe)
        try:
            engine = create_engine(db_url)
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT content, embedding_json, metadata_json
                        FROM vector_memory_records
                        WHERE store_type = 'negative-memory'
                        ORDER BY id DESC
                        LIMIT 100
                        """)
                ).fetchall()
        except Exception:
            return None

        for row in rows:
            try:
                candidate = json.loads(row.embedding_json)
                similarity = self._cosine(probe_embedding, candidate)
                if similarity > self.threshold:
                    metadata = json.loads(row.metadata_json) if row.metadata_json else {}
                    risk_key = f"{tool_name}:{hashlib.sha256(probe.encode('utf-8')).hexdigest()}"
                    self.risk_memory_store[risk_key] = self.risk_memory_store.get(risk_key, 0) + 1
                    if self.risk_memory_store[risk_key] > 3:
                        return {
                            FieldName.SIMILARITY: 1.0,
                            FieldName.REASON: "repeated_risk_violation",
                            FieldName.CONTENT: f"Pattern failed {self.risk_memory_store[risk_key]} times",
                        }
                    return {
                        FieldName.SIMILARITY: round(similarity, 3),
                        FieldName.REASON: metadata.get(
                            FieldName.REASON, "blocked by prior negative memory"
                        ),
                        FieldName.CONTENT: row.content,
                    }
            except Exception:
                continue
        return None

    def _embed(self, text_input: str) -> list[float]:
        digest = hashlib.sha256(text_input.encode("utf-8")).digest()
        return [round(b / 255.0, 6) for b in digest[:16]]

    def _cosine(self, a: list[float], b: list[float]) -> float:
        n = min(len(a), len(b))
        if n == 0:
            return 0.0
        a = a[:n]
        b = b[:n]
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


class ConversationMemory:
    def __init__(self, limit: int = 10):
        self.limit = limit
        self.events: list[dict[str, Any]] = []

    def add(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        self.events = self.events[-self.limit :]


class TaskStateMemory:
    def __init__(self):
        self.state: dict[str, dict[str, Any]] = {}

    def put(self, task_id: str, value: dict[str, Any]) -> None:
        self.state[task_id] = value

    def get(self, task_id: str) -> dict[str, Any] | None:
        return self.state.get(task_id)


class PersistentMemory:
    def __init__(self, path: str = "trade-memory.json"):
        self.path = Path(path)
        self._store = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {FieldName.TRADES: []}

    def append_trade(self, trade: dict[str, Any]) -> None:
        self._store.setdefault(FieldName.TRADES, []).append(trade)
        self.path.write_text(json.dumps(self._store, indent=2, default=str), encoding="utf-8")
