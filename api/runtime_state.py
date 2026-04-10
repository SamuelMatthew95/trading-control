from __future__ import annotations

from api.constants import RuntimeMode, StorageBackend
from api.in_memory_store import InMemoryStore

# Simple state: try DB, if fails use memory
_store: InMemoryStore | None = None
_db_available: bool = False  # True = DB works, False = use memory


def set_runtime_store(store: InMemoryStore) -> None:
    """Set the in-memory store."""
    global _store
    _store = store


def get_runtime_store() -> InMemoryStore:
    """Get the in-memory store."""
    global _store
    if _store is None:
        _store = InMemoryStore()
    return _store


def set_db_available(is_available: bool) -> None:
    """Set if database is available. Call this when DB init succeeds or fails."""
    global _db_available
    _db_available = is_available


def is_db_available() -> bool:
    """Check if database is available."""
    return _db_available


def get_active_backend() -> str:
    """
    Get active storage backend.

    Simple logic:
    - If DB is available -> use StorageBackend.DATABASE
    - If DB is not available -> use StorageBackend.MEMORY
    """
    return StorageBackend.DATABASE if _db_available else StorageBackend.MEMORY


def get_runtime_mode() -> str:
    """Get runtime mode: RuntimeMode.CONNECTED if DB works, RuntimeMode.IN_MEMORY_FALLBACK if not."""
    return RuntimeMode.CONNECTED if _db_available else RuntimeMode.IN_MEMORY_FALLBACK


# Legacy functions - keep them working
def storage_backend() -> str:
    """Legacy: use get_active_backend()"""
    return get_active_backend()


def runtime_mode() -> str:
    """Legacy: use get_runtime_mode()"""
    return get_runtime_mode()


# Remove old auto/db/memory config - no longer needed
def get_persistence_mode() -> str:
    """Legacy: always returns 'auto' for compatibility"""
    return "auto"


def set_persistence_mode(mode: str) -> None:
    """Legacy: does nothing, persistence is now automatic"""
    pass
