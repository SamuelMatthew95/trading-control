from __future__ import annotations

from api.in_memory_store import InMemoryStore

_store: InMemoryStore | None = None
_db_available: bool = False


def set_runtime_store(store: InMemoryStore) -> None:
    global _store
    _store = store


def get_runtime_store() -> InMemoryStore:
    global _store
    if _store is None:
        _store = InMemoryStore()
    return _store


def set_db_available(is_available: bool) -> None:
    global _db_available
    _db_available = is_available


def is_db_available() -> bool:
    return _db_available


def runtime_mode() -> str:
    return "connected" if _db_available else "in_memory_fallback"
