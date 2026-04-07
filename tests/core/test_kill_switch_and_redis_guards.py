"""Regression tests: kill switch, Redis key constants, and schema version guards.

Each test here corresponds to a real runtime bug that was found and fixed.
They exist to prevent regressions — if you see a failure here, a real bug
was just reintroduced.
"""

from __future__ import annotations

import pathlib
import re

# ---------------------------------------------------------------------------
# Kill switch value consistency
# ---------------------------------------------------------------------------


def test_kill_switch_stored_as_one_zero() -> None:
    """dashboard_v2.py must store kill switch as '1'/'0', not 'true'/'false'.

    Consumers check == '1'. If the write side stores 'true', the check never
    matches and the kill switch silently does nothing.
    """
    src = pathlib.Path("api/routes/dashboard_v2.py").read_text()

    # The toggle endpoint must use "1" for active
    assert '"1" if active' in src or '"1" if active else "0"' in src, (
        "dashboard_v2.py must store kill switch as '1' (not 'true'). All consumers check == '1'."
    )

    # Ensure old pattern is gone
    assert '"true" if active' not in src, (
        "dashboard_v2.py still stores kill switch as 'true'. "
        "Change to '1' to match consumer checks."
    )


def test_kill_switch_no_decode_calls() -> None:
    """Kill switch consumers must not call .decode() on Redis result.

    Redis client uses decode_responses=True — get() always returns str.
    Calling .decode() on a str raises AttributeError at runtime.
    """
    files_to_check = [
        pathlib.Path("api/services/simple_consumers.py"),
        pathlib.Path("api/services/system_metrics_consumer.py"),
        pathlib.Path("api/services/execution/execution_engine.py"),
    ]
    bad = re.compile(r"\.decode\(\)")
    violations: list[str] = []

    for path in files_to_check:
        src = path.read_text()
        for m in bad.finditer(src):
            line_num = src[: m.start()].count("\n") + 1
            violations.append(f"{path}:{line_num}")

    assert not violations, (
        "These files call .decode() but Redis uses decode_responses=True (returns str). "
        "Remove .decode() calls:\n" + "\n".join(violations)
    )


def test_kill_switch_uses_constant_everywhere() -> None:
    """All kill switch Redis reads/writes must use REDIS_KEY_KILL_SWITCH constant.

    Bare 'kill_switch:active' strings cause silent mismatches if the key ever changes.
    """
    bad = re.compile(r'"kill_switch:active"')
    violations: list[str] = []

    for path in pathlib.Path("api").rglob("*.py"):
        if path.name == "constants.py":
            continue
        src = path.read_text()
        for m in bad.finditer(src):
            line_num = src[: m.start()].count("\n") + 1
            violations.append(f"{path}:{line_num}")

    assert not violations, (
        "Use REDIS_KEY_KILL_SWITCH instead of bare 'kill_switch:active' strings:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# GET /kill-switch endpoint exists
# ---------------------------------------------------------------------------


def test_get_kill_switch_endpoint_exists() -> None:
    """A GET /kill-switch endpoint must exist to allow the frontend to read state.

    Without it, the frontend cannot query kill switch status on page load.
    """
    src = pathlib.Path("api/routes/dashboard_v2.py").read_text()
    assert '@router.get("/kill-switch")' in src, (
        "dashboard_v2.py is missing a GET /kill-switch endpoint. "
        "The frontend needs to read kill switch state on page load."
    )


# ---------------------------------------------------------------------------
# LLM Redis key constants
# ---------------------------------------------------------------------------


def test_no_bare_llm_key_fstrings() -> None:
    """reasoning_agent.py must use REDIS_KEY_LLM_TOKENS/COST constants.

    Hardcoded f'llm:tokens:{today}' bypasses the constants file and creates
    key drift if the key pattern is ever changed.
    """
    src = pathlib.Path("api/services/agents/reasoning_agent.py").read_text()

    bad_patterns = [r'f"llm:tokens:', r"f'llm:tokens:", r'f"llm:cost:', r"f'llm:cost:"]
    violations = [p for p in bad_patterns if p in src]

    assert not violations, (
        "reasoning_agent.py still uses hardcoded LLM Redis key f-strings. "
        "Use REDIS_KEY_LLM_TOKENS.format(date=today) and REDIS_KEY_LLM_COST.format(date=today):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Order lock key constant
# ---------------------------------------------------------------------------


def test_order_lock_uses_constant() -> None:
    """execution_engine.py must use REDIS_KEY_ORDER_LOCK.format() for lock keys.

    Hardcoded f'order_lock:{symbol}' bypasses the constants file.
    """
    src = pathlib.Path("api/services/execution/execution_engine.py").read_text()

    assert 'f"order_lock:' not in src and "f'order_lock:" not in src, (
        "execution_engine.py still uses hardcoded f'order_lock:{symbol}'. "
        "Use REDIS_KEY_ORDER_LOCK.format(symbol=symbol)."
    )
    assert "REDIS_KEY_ORDER_LOCK" in src, (
        "execution_engine.py must import and use REDIS_KEY_ORDER_LOCK constant."
    )


def test_order_lock_ttl_uses_constant() -> None:
    """execution_engine.py must use ORDER_LOCK_TTL_SECONDS for the lock TTL.

    Hardcoded ex=5 for the order lock bypasses the constant.
    """
    import ast

    src = pathlib.Path("api/services/execution/execution_engine.py").read_text()
    tree = ast.parse(src)

    # Check for ex=5 keyword arg (hardcoded lock TTL)
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "ex":
            if isinstance(node.value, ast.Constant) and node.value.value == 5:
                raise AssertionError(
                    f"execution_engine.py:{node.value.lineno} uses hardcoded ex=5. "
                    "Use ORDER_LOCK_TTL_SECONDS constant instead."
                )


# ---------------------------------------------------------------------------
# Worker heartbeat key constant
# ---------------------------------------------------------------------------


def test_no_bare_worker_heartbeat_key() -> None:
    """price_poller.py must use REDIS_KEY_WORKER_HEARTBEAT constant.

    Hardcoded 'worker:heartbeat' strings bypass the constants file.
    """
    bad = re.compile(r'"worker:heartbeat"')
    violations: list[str] = []

    for path in pathlib.Path("api").rglob("*.py"):
        if path.name == "constants.py":
            continue
        src = path.read_text()
        for m in bad.finditer(src):
            line_num = src[: m.start()].count("\n") + 1
            violations.append(f"{path}:{line_num}")

    assert not violations, (
        "Use REDIS_KEY_WORKER_HEARTBEAT instead of bare 'worker:heartbeat' strings:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# LogType.SIGNAL_GENERATED enum value
# ---------------------------------------------------------------------------


def test_log_type_signal_generated_defined() -> None:
    """LogType must include SIGNAL_GENERATED for signal_generator.py to use.

    Without it, signal_generator inserts an out-of-enum log_type value.
    """
    from api.constants import LogType

    assert hasattr(LogType, "SIGNAL_GENERATED"), (
        "LogType enum is missing SIGNAL_GENERATED. "
        "signal_generator.py writes agent_logs with log_type='signal_generated'."
    )
    assert LogType.SIGNAL_GENERATED == "signal_generated"


def test_signal_generator_uses_log_type_constant() -> None:
    """signal_generator.py must use LogType.SIGNAL_GENERATED, not bare string.

    Bare 'signal_generated' strings bypass the enum and won't be caught by
    the log_type guardrail tests.
    """
    src = pathlib.Path("api/services/signal_generator.py").read_text()

    assert "'signal_generated'" not in src and '"signal_generated"' not in src, (
        "signal_generator.py still has bare 'signal_generated' string. "
        "Use LogType.SIGNAL_GENERATED from api.constants."
    )
    assert "LogType.SIGNAL_GENERATED" in src, (
        "signal_generator.py must use LogType.SIGNAL_GENERATED for agent_logs writes."
    )


# ---------------------------------------------------------------------------
# safe_writer.py uses DB_SCHEMA_VERSION constant
# ---------------------------------------------------------------------------


def test_safe_writer_uses_schema_version_constant() -> None:
    """safe_writer.py validation must use DB_SCHEMA_VERSION, not bare 'v3'.

    If the schema version bumps to v4, a bare string won't update automatically.
    """

    src = pathlib.Path("api/core/writer/safe_writer.py").read_text()

    # Ensure it imports the constant
    assert "DB_SCHEMA_VERSION" in src, (
        "safe_writer.py must import and use DB_SCHEMA_VERSION from api.schema_version."
    )

    # Ensure the validation check references the constant, not a bare string
    # Check the _validate_schema_v3 method does not compare to bare "v3"
    # (it's OK to have "v3" in string literals inside error messages,
    #  but the comparison itself must use the constant)
    lines = src.splitlines()
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Catch: if data["schema_version"] != "v3":
        if '!= "v3"' in stripped and "data" in stripped and "DB_SCHEMA_VERSION" not in stripped:
            raise AssertionError(
                f"safe_writer.py:{i} compares schema_version to bare '\"v3\"'. "
                "Use DB_SCHEMA_VERSION constant."
            )


# ---------------------------------------------------------------------------
# health.py uses text() wrapper
# ---------------------------------------------------------------------------


def test_health_py_uses_text_wrapper() -> None:
    """api/health.py database check must use text('SELECT 1'), not raw string.

    SQLAlchemy async session.execute() requires an Executable object.
    Passing a plain string raises TypeError at runtime.
    """
    src = pathlib.Path("api/health.py").read_text()

    assert 'execute("SELECT 1")' not in src, (
        "api/health.py calls session.execute('SELECT 1') without text() wrapper. "
        "This raises TypeError in SQLAlchemy async. Use text('SELECT 1')."
    )
    assert "text(" in src, (
        "api/health.py must import and use text() from sqlalchemy for raw SQL queries."
    )
