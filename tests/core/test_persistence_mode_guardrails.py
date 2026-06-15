"""Smart guardrails to prevent PERSISTENCE_MODE regression."""

import pytest

from api.config import Settings
from api.constants import RuntimeMode, StorageBackend
from api.runtime_state import get_active_backend, get_runtime_mode, set_db_available


def test_settings_has_no_persistence_mode():
    """Settings should not have PERSISTENCE_MODE attribute."""
    settings = Settings()

    # Direct access should fail
    with pytest.raises(AttributeError):
        _ = settings.PERSISTENCE_MODE

    # hasattr should be False
    assert not hasattr(settings, "PERSISTENCE_MODE")


def test_app_can_start_without_persistence_mode():
    """App should start without PERSISTENCE_MODE references."""
    from api.main import app

    # Just creating the app should not raise AttributeError
    assert app is not None


def test_simplified_runtime_logic():
    """Test the simplified runtime logic works."""
    # Test DB available
    set_db_available(True)
    assert get_active_backend() == StorageBackend.DATABASE
    assert get_runtime_mode() == RuntimeMode.CONNECTED

    # Test DB unavailable
    set_db_available(False)
    assert get_active_backend() == StorageBackend.MEMORY
    assert get_runtime_mode() == RuntimeMode.IN_MEMORY_FALLBACK
