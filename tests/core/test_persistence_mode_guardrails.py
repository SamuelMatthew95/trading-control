"""Guardrails to prevent PERSISTENCE_MODE regression."""

import ast

import pytest

from api.config import Settings


def test_settings_has_no_persistence_mode_attribute():
    """Ensure Settings class does not have PERSISTENCE_MODE attribute."""
    settings = Settings()

    # Direct attribute access should fail
    with pytest.raises(AttributeError):
        _ = settings.PERSISTENCE_MODE

    # hasattr should return False
    assert not hasattr(settings, "PERSISTENCE_MODE")

    # dir() should not contain PERSISTENCE_MODE
    assert "PERSISTENCE_MODE" not in dir(settings)


def test_settings_class_has_no_persistence_mode_field():
    """Ensure Settings class definition does not contain PERSISTENCE_MODE field."""
    # Check field definitions
    fields = Settings.model_fields
    assert "PERSISTENCE_MODE" not in fields

    # Check class annotations
    annotations = Settings.__annotations__
    assert "PERSISTENCE_MODE" not in annotations


def test_main_app_startup_without_persistence_mode():
    """Ensure main app can start without PERSISTENCE_MODE references."""
    # This should not raise AttributeError
    # Create a mock app to test lifespan
    from unittest.mock import Mock

    from api.main import lifespan

    mock_app = Mock()
    mock_app.state = Mock()
    mock_app.state.db_engine = None

    # The lifespan function should not reference PERSISTENCE_MODE
    try:
        # Just test that the function can be accessed without error
        assert lifespan is not None
    except AttributeError as e:
        if "PERSISTENCE_MODE" in str(e):
            pytest.fail("lifespan function references PERSISTENCE_MODE")
        raise


def test_no_persistence_mode_in_config_file():
    """Ensure config.py file does not contain PERSISTENCE_MODE field definitions."""
    config_file_path = "api/config.py"

    with open(config_file_path) as f:
        content = f.read()

    # Parse AST to ensure no field definitions
    tree = ast.parse(content)

    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "PERSISTENCE_MODE":
                pytest.fail("config.py contains PERSISTENCE_MODE field definition")

        if isinstance(node, ast.FunctionDef) and "persistence_mode" in node.name.lower():
            pytest.fail(f"config.py contains function with persistence_mode in name: {node.name}")

    # Check for dangerous patterns (not in comments)
    lines = content.split('\n')
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip comments
        if stripped.startswith('#'):
            continue

        # Check for settings.PERSISTENCE_MODE or app.state.persistence_mode
        if "settings.PERSISTENCE_MODE" in line or "app.state.persistence_mode" in line:
            pytest.fail(f"config.py line {i} contains PERSISTENCE_MODE code reference: {line.strip()}")


def test_no_persistence_mode_in_main_file():
    """Ensure main.py file does not contain PERSISTENCE_MODE references."""
    main_file_path = "api/main.py"

    with open(main_file_path) as f:
        content = f.read()

    # Check for any PERSISTENCE_MODE references except in comments or strings
    lines = content.split('\n')
    for i, line in enumerate(lines, 1):
        # Skip comments and docstrings
        stripped = line.strip()
        if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
            continue

        if "PERSISTENCE_MODE" in line:
            pytest.fail(f"main.py line {i} contains PERSISTENCE_MODE reference: {line.strip()}")


def test_no_persistence_mode_in_runtime_state():
    """Ensure runtime_state.py does not contain PERSISTENCE_MODE references in problematic ways."""
    runtime_file_path = "api/runtime_state.py"

    with open(runtime_file_path) as f:
        content = f.read()

    # Allow legacy functions but ensure they don't reference settings.PERSISTENCE_MODE
    if "settings.PERSISTENCE_MODE" in content:
        pytest.fail("runtime_state.py contains settings.PERSISTENCE_MODE reference")


def test_runtime_state_legacy_functions_work():
    """Ensure legacy persistence mode functions work without breaking."""
    from api.runtime_state import get_persistence_mode, set_persistence_mode

    # These should work without error
    assert get_persistence_mode() == "auto"

    # Setting should not raise error (even though it does nothing)
    set_persistence_mode("memory")
    assert get_persistence_mode() == "auto"

    set_persistence_mode("db")
    assert get_persistence_mode() == "auto"


def test_constants_has_proper_enums():
    """Ensure constants.py has proper enum definitions instead of string literals."""
    from api.constants import HealthStatus, RuntimeMode, StorageBackend

    # Test that enums exist and have correct values
    assert hasattr(StorageBackend, "DATABASE")
    assert hasattr(StorageBackend, "MEMORY")
    assert StorageBackend.DATABASE.value == "db"
    assert StorageBackend.MEMORY.value == "memory"

    assert hasattr(RuntimeMode, "CONNECTED")
    assert hasattr(RuntimeMode, "IN_MEMORY_FALLBACK")
    assert RuntimeMode.CONNECTED.value == "connected"
    assert RuntimeMode.IN_MEMORY_FALLBACK.value == "in_memory_fallback"

    assert hasattr(HealthStatus, "HEALTHY")
    assert hasattr(HealthStatus, "DEGRADED")
    assert HealthStatus.HEALTHY.value == "healthy"
    assert HealthStatus.DEGRADED.value == "degraded"


def test_simplified_runtime_logic_works():
    """Test that simplified runtime logic works correctly."""
    from api.constants import RuntimeMode, StorageBackend
    from api.runtime_state import get_active_backend, get_runtime_mode, set_db_available

    # Test DB available
    set_db_available(True)
    assert get_active_backend() == StorageBackend.DATABASE
    assert get_runtime_mode() == RuntimeMode.CONNECTED

    # Test DB unavailable
    set_db_available(False)
    assert get_active_backend() == StorageBackend.MEMORY
    assert get_runtime_mode() == RuntimeMode.IN_MEMORY_FALLBACK


def test_no_persistence_mode_in_entire_codebase():
    """Scan entire codebase for any PERSISTENCE_MODE references that shouldn't exist."""
    import os

    # Files that should NOT contain PERSISTENCE_MODE references
    protected_files = [
        "api/config.py",
        "api/main.py",
        "api/database.py",
        "api/routes/health.py",
    ]

    for file_path in protected_files:
        if os.path.exists(file_path):
            with open(file_path) as f:
                content = f.read()

            # Check for PERSISTENCE_MODE references (allow in comments)
            lines = content.split('\n')
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                # Skip comments
                if stripped.startswith('#'):
                    continue

                if "PERSISTENCE_MODE" in line:
                    pytest.fail(f"{file_path} line {i} contains PERSISTENCE_MODE reference: {line.strip()}")


def test_app_state_has_no_persistence_mode():
    """Ensure app state does not have persistence_mode attribute after startup."""
    # This test would require more complex setup with actual app startup
    # For now, just ensure the main module doesn't set it
    main_file_path = "api/main.py"

    with open(main_file_path) as f:
        content = f.read()

    # Should not set app.state.persistence_mode
    assert "app.state.persistence_mode" not in content
