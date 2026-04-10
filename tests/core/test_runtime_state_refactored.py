"""Unit tests for refactored runtime_state module."""

import pytest

from api.runtime_state import (
    PersistenceMode,
    RuntimeMode,
    get_active_backend,
    get_persistence_mode,
    get_runtime_mode,
    get_runtime_store,
    is_db_available,
    set_db_available,
    set_persistence_mode,
)


class TestRuntimeStateRefactored:
    """Test the refactored runtime_state implementation."""

    def test_persistence_mode_enum_values(self):
        """Test PersistenceMode enum has correct values."""
        assert PersistenceMode.AUTO.value == "auto"
        assert PersistenceMode.DATABASE.value == "db"
        assert PersistenceMode.MEMORY.value == "memory"

    def test_runtime_mode_enum_values(self):
        """Test RuntimeMode enum has correct values."""
        assert RuntimeMode.CONNECTED.value == "connected"
        assert RuntimeMode.IN_MEMORY.value == "in_memory"
        assert RuntimeMode.IN_MEMORY_FALLBACK.value == "in_memory_fallback"

    def test_set_persistence_mode_with_string(self):
        """Test setting persistence mode with string input."""
        set_persistence_mode("auto")
        assert get_persistence_mode() == "auto"

        set_persistence_mode("db")
        assert get_persistence_mode() == "db"

        set_persistence_mode("memory")
        assert get_persistence_mode() == "memory"

    def test_set_persistence_mode_with_enum(self):
        """Test setting persistence mode with enum input."""
        set_persistence_mode(PersistenceMode.AUTO)
        assert get_persistence_mode() == "auto"

        set_persistence_mode(PersistenceMode.DATABASE)
        assert get_persistence_mode() == "db"

        set_persistence_mode(PersistenceMode.MEMORY)
        assert get_persistence_mode() == "memory"

    def test_set_db_available(self):
        """Test setting database availability."""
        set_db_available(True)
        assert is_db_available() is True

        set_db_available(False)
        assert is_db_available() is False

    def test_memory_mode_always_returns_memory(self):
        """Test MEMORY mode always returns memory backend regardless of DB availability."""
        set_persistence_mode(PersistenceMode.MEMORY)

        # Even with DB available, should still use memory
        set_db_available(True)
        assert get_active_backend() == "memory"
        assert get_runtime_mode() == "in_memory"

        # With DB unavailable, should still use memory
        set_db_available(False)
        assert get_active_backend() == "memory"
        assert get_runtime_mode() == "in_memory"

    def test_database_mode_always_returns_db(self):
        """Test DATABASE mode always returns db backend regardless of DB availability."""
        set_persistence_mode(PersistenceMode.DATABASE)

        # With DB available
        set_db_available(True)
        assert get_active_backend() == "db"
        assert get_runtime_mode() == "connected"

        # Even with DB unavailable (forced mode)
        set_db_available(False)
        assert get_active_backend() == "db"
        assert get_runtime_mode() == "connected"

    def test_auto_mode_with_db_available(self):
        """Test AUTO mode uses DB when available."""
        set_persistence_mode(PersistenceMode.AUTO)
        set_db_available(True)

        assert get_active_backend() == "db"
        assert get_runtime_mode() == "connected"

    def test_auto_mode_with_db_unavailable(self):
        """Test AUTO mode uses memory when DB unavailable."""
        set_persistence_mode(PersistenceMode.AUTO)
        set_db_available(False)

        assert get_active_backend() == "memory"
        assert get_runtime_mode() == "in_memory_fallback"

    def test_runtime_mode_scenarios(self):
        """Test all runtime mode scenarios."""
        scenarios = [
            # (persistence_mode, db_available, expected_backend, expected_runtime_mode)
            ("auto", True, "db", "connected"),
            ("auto", False, "memory", "in_memory_fallback"),
            ("db", True, "db", "connected"),
            ("db", False, "db", "connected"),  # Forced DB mode
            ("memory", True, "memory", "in_memory"),
            ("memory", False, "memory", "in_memory"),
        ]

        for mode, db_available, expected_backend, expected_runtime_mode in scenarios:
            set_persistence_mode(mode)
            set_db_available(db_available)

            assert get_active_backend() == expected_backend, (
                f"Failed for {mode} + db_available={db_available}"
            )
            assert get_runtime_mode() == expected_runtime_mode, (
                f"Failed for {mode} + db_available={db_available}"
            )

    def test_get_runtime_store_singleton(self):
        """Test runtime store returns same instance."""
        store1 = get_runtime_store()
        store2 = get_runtime_store()

        assert store1 is store2

    def test_invalid_persistence_mode_string(self):
        """Test invalid persistence mode string raises error."""
        with pytest.raises(ValueError):
            set_persistence_mode("invalid_mode")

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
        assert get_active_backend() == "memory"
        assert get_runtime_mode() == "in_memory_fallback"

        # Reset to known state for next test
        set_persistence_mode("auto")
        set_db_available(False)
