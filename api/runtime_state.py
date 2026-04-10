from __future__ import annotations

from api.in_memory_store import InMemoryStore

_store: InMemoryStore | None = None
_db_available: bool = False
_persistence_mode: str = "auto"


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


def set_persistence_mode(mode: str) -> None:
    global _persistence_mode
    _persistence_mode = mode


def get_persistence_mode() -> str:
    return _persistence_mode


def storage_backend() -> str:
    """Return the effective persistence backend for this process."""
    if _persistence_mode == "memory":
        return "memory"
    if _persistence_mode == "db":
        return "db"
    return "db" if _db_available else "memory"


def runtime_mode() -> str:
    return "connected" if storage_backend() == "db" else "in_memory_fallback"
