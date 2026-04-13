"""Guardrail tests for test-suite isolation.

These tests exist to catch one specific recurring bug class:
  - Global InMemoryStore state leaking between tests because
    agent.process() writes to the store when is_db_available() is False.

History:
  test_signal_pipeline.py called SignalGenerator.process() without mocking
  is_db_available(). Since _db_available defaults to False, process() took
  the memory path and wrote events to the global InMemoryStore. Later tests
  that expected an empty store (e.g. test_event_history_falls_back_when_query_fails)
  failed non-deterministically depending on test execution order.

Fix: tests/conftest.py autouse fixture resets InMemoryStore + db_available
     before every test. These tests verify that fixture is alive and working.

If these tests fail it means the isolation contract was broken — do not
suppress or delete them.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.runtime_state import get_runtime_store, is_db_available

# ---------------------------------------------------------------------------
# Part 1 — Verify the autouse fixture gives every test a clean slate
# ---------------------------------------------------------------------------


def test_store_is_empty_at_test_start():
    """InMemoryStore must be empty at the start of every test.

    If this fails, the _reset_runtime_state autouse fixture in
    tests/conftest.py has been removed or disabled.
    """
    store = get_runtime_store()
    assert len(store.event_history) == 0, (
        "event_history is not empty — _reset_runtime_state autouse fixture "
        "in tests/conftest.py must have been removed."
    )
    assert len(store.grade_history) == 0
    assert len(store.agent_runs) == 0
    assert len(store.vector_memory) == 0


def test_db_available_is_false_at_test_start():
    """is_db_available() must return False at the start of every test.

    If this fails, a previous test called set_db_available(True) without
    resetting, OR the autouse fixture was removed.
    """
    assert is_db_available() is False, (
        "is_db_available() is True — the autouse fixture in tests/conftest.py "
        "should have reset it to False before this test."
    )


# ---------------------------------------------------------------------------
# Part 2 — Prove the pollution scenario exists, then the next test proves
#           isolation kills it. These two tests must stay adjacent and in order.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signal_generator_process_writes_to_store__pollution_exists(monkeypatch):
    """Confirm that SignalGenerator.process() in memory mode writes to the store.

    This is the SOURCE of the pollution. If this test passes, it means the
    store WILL contain events after process() — which is exactly why the
    autouse reset in conftest.py is mandatory.
    """
    monkeypatch.setattr("api.services.signal_generator.is_db_available", lambda: False)

    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.redis = AsyncMock()
    dlq = MagicMock(spec=DLQManager)

    from api.services.signal_generator import SignalGenerator

    sg = SignalGenerator(bus, dlq)
    await sg.process({"symbol": "BTC/USD", "price": 50000.0, "pct": 4.5})

    store = get_runtime_store()
    assert len(store.event_history) > 0, (
        "Expected process() to write events to the store in memory mode."
    )
    assert len(store.agent_runs) > 0, (
        "Expected process() to write an agent_run to the store in memory mode."
    )
    # Store is now dirty — the autouse fixture must clean it before the next test.


def test_store_is_clean_after_polluting_test():
    """Store must be empty even after the previous test dirtied it.

    This test is the PROOF that isolation works. It runs immediately after
    test_signal_generator_process_writes_to_store__pollution_exists, which
    left events in the store. If the autouse fixture is running, this store
    is a brand-new InMemoryStore with nothing in it.

    If this test fails: the autouse fixture in tests/conftest.py was removed
    or is broken. Re-add it — do not modify this test instead.
    """
    store = get_runtime_store()
    assert len(store.event_history) == 0, (
        "event_history still has data from the previous test — "
        "_reset_runtime_state autouse fixture is not running between tests."
    )
    assert len(store.agent_runs) == 0
    assert is_db_available() is False


# ---------------------------------------------------------------------------
# Part 3 — Verify the autouse fixture is actually wired in conftest.py
#           (source-code inspection so a rename doesn't silently break it)
# ---------------------------------------------------------------------------


def test_conftest_autouse_fixture_exists():
    """The _reset_runtime_state autouse fixture must exist in tests/conftest.py.

    Inspect the conftest to confirm the fixture is registered and autouse=True.
    This catches accidental deletion or rename.
    """
    import tests.conftest as conftest_module

    assert hasattr(conftest_module, "_reset_runtime_state"), (
        "_reset_runtime_state fixture missing from tests/conftest.py — "
        "test isolation is broken for the entire suite."
    )

    fixture_fn = conftest_module._reset_runtime_state
    marker = getattr(fixture_fn, "_pytestfixturefunction", None)
    assert marker is not None, (
        "_reset_runtime_state exists but is not decorated with @pytest.fixture."
    )
    assert marker.autouse is True, (
        "_reset_runtime_state is a fixture but autouse=False — "
        "it will not run automatically before every test."
    )


def test_conftest_fixture_body_resets_both_store_and_db_flag():
    """The autouse fixture source must call both set_runtime_store and set_db_available.

    Inspects the fixture's source code so a partial edit (e.g. deleting one
    of the two reset calls) is caught immediately.
    """
    import inspect

    import tests.conftest as conftest_module

    src = inspect.getsource(conftest_module._reset_runtime_state)

    assert "set_runtime_store" in src, (
        "_reset_runtime_state does not call set_runtime_store() — "
        "InMemoryStore will not be cleared between tests."
    )
    assert "InMemoryStore()" in src, (
        "_reset_runtime_state does not create a fresh InMemoryStore() — "
        "the old dirty store will persist between tests."
    )
    assert "set_db_available" in src, (
        "_reset_runtime_state does not call set_db_available() — "
        "is_db_available() may return True in subsequent tests."
    )
