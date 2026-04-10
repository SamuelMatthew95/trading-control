"""Unit tests for refactored runtime_state module."""

import pytest

from api.constants import RuntimeMode, StorageBackend
from api.runtime_state import (
    set_db_available,
    set_persistence_mode,
    get_active_backend,
    get_runtime_mode,
    get_persistence_mode,
    is_db_available,
    get_runtime_store,
)


class TestRuntimeStateRefactored:
    """Test the refactored runtime_state implementation."""

    def test_storage_backend_enum_values(self):
        """Test StorageBackend enum has correct values."""
        assert StorageBackend.DATABASE.value == "db"
        assert StorageBackend.MEMORY.value == "memory"

    def test_runtime_mode_enum_values(self):
        """Test RuntimeMode enum has correct values."""
        assert RuntimeMode.CONNECTED.value == "connected"
        assert RuntimeMode.IN_MEMORY.value == "in_memory"
        assert RuntimeMode.IN_MEMORY_FALLBACK.value == "in_memory_fallback"

    def test_set_persistence_mode_with_string(self):
        """Test setting persistence mode with string input - legacy function."""
        # Legacy function should always return "auto" regardless of input
        set_persistence_mode("auto")
        assert get_persistence_mode() == "auto"

        set_persistence_mode("db")
        assert get_persistence_mode() == "auto"

        set_persistence_mode("memory")
        assert get_persistence_mode() == "auto"

    def test_set_db_available(self):
        """Test setting database availability."""
        set_db_available(True)
        assert is_db_available() is True

        set_db_available(False)
        assert is_db_available() is False

    def test_db_available_uses_db(self):
        """Test that DB available uses database backend."""
        set_db_available(True)

        assert get_active_backend() == StorageBackend.DATABASE

    def test_db_unavailable_uses_memory(self):
        """Test that DB unavailable uses memory backend."""
        set_db_available(False)

        assert get_active_backend() == StorageBackend.MEMORY
        assert get_runtime_mode() == RuntimeMode.IN_MEMORY_FALLBACK

    def test_runtime_mode_scenarios(self):
        """Test all runtime mode scenarios."""
        scenarios = [
            # (db_available, expected_backend, expected_runtime_mode)
            (True, StorageBackend.DATABASE, RuntimeMode.CONNECTED),
            (False, StorageBackend.MEMORY, RuntimeMode.IN_MEMORY_FALLBACK),
        ]

        for db_available, expected_backend, expected_runtime_mode in scenarios:
            set_db_available(db_available)
            assert get_active_backend() == expected_backend
            assert get_runtime_mode() == expected_runtime_mode

    def test_get_runtime_store_singleton(self):
        """Test runtime store returns same instance."""
        store1 = get_runtime_store()
        store2 = get_runtime_store()

        assert store1 is store2

    def test_invalid_persistence_mode_string(self):
        """Test invalid persistence mode string - legacy function accepts all now."""
        # Legacy function no longer validates, accepts any string
        set_persistence_mode("invalid_mode")
        assert get_persistence_mode() == "auto"  # Always returns "auto"

    def test_legacy_compatibility_functions(self):
        """Test legacy compatibility functions still work."""
        from api.runtime_state import runtime_mode, storage_backend

        set_persistence_mode("auto")
        set_db_available(False)

        # Legacy functions should return same as new functions
        assert storage_backend() == get_active_backend()
        assert runtime_mode() == get_runtime_mode()

    def test_state_isolation(self):
        """Test that state changes don't affect other tests."""
        # Set some state
        set_persistence_mode("auto")
        set_db_available(False)

        # Verify state
        assert get_persistence_mode() == "auto"
        assert is_db_available() is False
        assert get_active_backend() == StorageBackend.MEMORY
        assert get_runtime_mode() == RuntimeMode.IN_MEMORY_FALLBACK

        # Reset to known state for next test
        set_persistence_mode("auto")
        set_db_available(False)
