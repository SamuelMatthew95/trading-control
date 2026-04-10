from __future__ import annotations

from enum import Enum
from typing import Literal

from api.in_memory_store import InMemoryStore


class PersistenceMode(Enum):
    AUTO = "auto"
    DATABASE = "db" 
    MEMORY = "memory"


class RuntimeMode(Enum):
    CONNECTED = "connected"
    IN_MEMORY = "in_memory"
    IN_MEMORY_FALLBACK = "in_memory_fallback"


# Global state
_store: InMemoryStore | None = None
_db_available: bool = False
_persistence_mode: PersistenceMode = PersistenceMode.AUTO


def set_runtime_store(store: InMemoryStore) -> None:
    """Set the global in-memory store instance."""
    global _store
    _store = store


def get_runtime_store() -> InMemoryStore:
    """Get the global in-memory store instance."""
    global _store
    if _store is None:
        _store = InMemoryStore()
    return _store


def set_db_available(is_available: bool) -> None:
    """Set database availability status."""
    global _db_available
    _db_available = is_available


def is_db_available() -> bool:
    """Check if database is available."""
    return _db_available


def set_persistence_mode(mode: str | PersistenceMode) -> None:
    """Set persistence mode configuration."""
    global _persistence_mode
    if isinstance(mode, str):
        mode = PersistenceMode(mode)
    _persistence_mode = mode


def get_persistence_mode() -> str:
    """Get current persistence mode as string."""
    return _persistence_mode.value


def get_active_backend() -> Literal["db", "memory"]:
    """Get the active storage backend based on configuration and DB availability."""
    if _persistence_mode == PersistenceMode.MEMORY:
        return "memory"
    if _persistence_mode == PersistenceMode.DATABASE:
        return "db"
    # AUTO mode: use DB if available, otherwise memory
    return "db" if _db_available else "memory"


def get_runtime_mode() -> str:
    """Get current runtime mode."""
    if _persistence_mode == PersistenceMode.MEMORY:
        return RuntimeMode.IN_MEMORY.value
    if get_active_backend() == "db":
        return RuntimeMode.CONNECTED.value
    return RuntimeMode.IN_MEMORY_FALLBACK.value


# Legacy compatibility functions
def storage_backend() -> str:
    """Legacy compatibility - use get_active_backend() instead."""
    return get_active_backend()


def runtime_mode() -> str:
    """Legacy compatibility - use get_runtime_mode() instead."""
    return get_runtime_mode()
