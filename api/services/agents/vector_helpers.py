"""Helpers for embedding text and querying vector memory.

Used by ReasoningAgent. Isolated here so the embedding strategy
(OpenAI or SHA-256 fallback) can change without touching agent logic.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import aiohttp
from sqlalchemy import text

from api.config import settings
from api.database import AsyncSessionFactory
from api.observability import log_structured

EMBED_DIMENSIONS = 1536
_OPENAI_EMBEDDING_URL = "https://api.openai.com/v1/embeddings"


def build_vector_literal(embedding: list[float]) -> str:
    """Format a float list as a pgvector literal string: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"


async def embed_text(text_value: str) -> list[float]:
    """Embed text via OpenAI API. Falls back to deterministic SHA-256 hash if no API key."""
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=settings.LLM_TIMEOUT_SECONDS)
        ) as http:
            async with http.post(
                _OPENAI_EMBEDDING_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": "text-embedding-3-small", "input": text_value},
            ) as response:
                if response.status >= 400:
                    raise RuntimeError(f"Embedding API error: HTTP {response.status}")
                payload = await response.json()
                return payload["data"][0]["embedding"]

    # Deterministic fallback: spread SHA-256 bytes into 1536 floats in [0, 1]
    digest = hashlib.sha256(text_value.encode("utf-8")).digest()
    values: list[float] = []
    while len(values) < EMBED_DIMENSIONS:
        for byte in digest:
            values.append(round(byte / 255, 6))
            if len(values) == EMBED_DIMENSIONS:
                break
    return values


async def search_vector_memory(embedding: list[float]) -> list[dict[str, Any]]:
    """Return the 5 nearest entries from vector_memory by cosine distance."""
    vec_literal = build_vector_literal(embedding)
    query = text("""
        SELECT id, content, metadata_, outcome,
               1 - (embedding <=> CAST(:embedding AS vector)) AS sim
        FROM vector_memory
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT 5
    """)
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(query, {"embedding": vec_literal})
            return [
                {
                    "id": str(row["id"]),
                    "content": row["content"],
                    "metadata": row["metadata_"],
                    "outcome": row["outcome"],
                    "sim": float(row["sim"]),
                }
                for row in result.mappings().all()
            ]
    except Exception:
        log_structured("error", "vector_memory_search_failed", exc_info=True)
        return []
