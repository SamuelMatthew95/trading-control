from __future__ import annotations

from api.runtime_state import (
    runtime_mode,
    set_db_available,
    set_persistence_mode,
    storage_backend,
)


def test_storage_backend_respects_explicit_modes():
    set_db_available(False)
    set_persistence_mode("memory")  # Legacy function, no longer affects behavior
    assert storage_backend() == "memory"
    assert runtime_mode() == "in_memory_fallback"  # Simplified behavior

    set_persistence_mode("db")  # Legacy function, no longer affects behavior
    assert storage_backend() == "memory"  # Still memory because DB is not available
    assert runtime_mode() == "in_memory_fallback"


def test_storage_backend_auto_tracks_db_health():
    set_persistence_mode("auto")
    set_db_available(False)
    assert storage_backend() == "memory"
    assert runtime_mode() == "in_memory_fallback"

    set_db_available(True)
    assert storage_backend() == "db"
    assert runtime_mode() == "connected"
