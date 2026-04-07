"""Guardrail tests: constants file is complete and all magic values are centralised.

These tests make it impossible to silently introduce new magic numbers, bare
log_type strings, or inconsistent TTL values — the kind of bugs that are hard
to debug in production.
"""

from __future__ import annotations


def test_heartbeat_ttl_greater_than_stale_threshold() -> None:
    """TTL must exceed stale threshold so agents can show STALE before going offline."""
    from api.constants import AGENT_HEARTBEAT_TTL_SECONDS, AGENT_STALE_THRESHOLD_SECONDS

    assert AGENT_HEARTBEAT_TTL_SECONDS > AGENT_STALE_THRESHOLD_SECONDS, (
        f"AGENT_HEARTBEAT_TTL_SECONDS={AGENT_HEARTBEAT_TTL_SECONDS} must be greater than "
        f"AGENT_STALE_THRESHOLD_SECONDS={AGENT_STALE_THRESHOLD_SECONDS}. "
        "If TTL == threshold, the Redis key expires at exactly the moment STALE would trigger, "
        "so agents go straight from ACTIVE to 'offline' with no STALE warning."
    )


def test_no_bare_ex_120_in_agent_code() -> None:
    """No agent file may use hardcoded ex=120 or ex=60 for heartbeat TTL."""
    import ast
    import pathlib

    agent_files = [
        pathlib.Path("api/services/signal_generator.py"),
        pathlib.Path("api/services/agents/reasoning_agent.py"),
        pathlib.Path("api/services/execution/execution_engine.py"),
        pathlib.Path("api/services/agents/pipeline_agents.py"),
    ]
    violations: list[str] = []
    for path in agent_files:
        src = path.read_text()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "ex":
                if isinstance(node.value, ast.Constant) and node.value.value in (60, 120):
                    violations.append(f"{path}:{node.value.lineno} ex={node.value.value}")

    assert not violations, (
        "Use AGENT_HEARTBEAT_TTL_SECONDS instead of hardcoded ex= values:\n" + "\n".join(violations)
    )


def test_no_bare_log_type_strings_in_queries() -> None:
    """SQL queries must use LogType constants, not bare 'proposal'/'grade' strings."""
    import pathlib
    import re

    # Patterns that should NOT appear outside constants.py
    bad_patterns = [
        r"log_type\s*=\s*'proposal'",
        r"log_type\s*=\s*'grade'",
        r"log_type\s*=\s*'reflection'",
        r"log_type\s*=\s*'reasoning_summary'",
    ]

    violations: list[str] = []
    for path in pathlib.Path("api").rglob("*.py"):
        if path.name == "constants.py" or "test_" in path.name:
            continue
        src = path.read_text()
        for pat in bad_patterns:
            for m in re.finditer(pat, src):
                # Allow f-string interpolated versions like {LogType.PROPOSAL}
                # by checking the surrounding context
                start = max(0, m.start() - 50)
                context = src[start : m.end() + 10]
                if "LogType." not in context:
                    line_num = src[: m.start()].count("\n") + 1
                    violations.append(f"{path}:{line_num} — {m.group()!r}")

    assert not violations, (
        "Use LogType.PROPOSAL / LogType.GRADE etc. instead of bare strings:\n"
        + "\n".join(violations)
    )


def test_no_bare_agent_status_fstrings() -> None:
    """No code outside constants.py may construct agent:status: keys via f-string."""
    import pathlib
    import re

    bad = re.compile(r'f["\']agent:status:')
    violations: list[str] = []
    for path in pathlib.Path("api").rglob("*.py"):
        if path.name == "constants.py":
            continue
        src = path.read_text()
        for m in bad.finditer(src):
            line_num = src[: m.start()].count("\n") + 1
            violations.append(f"{path}:{line_num}")

    assert not violations, (
        "Use REDIS_AGENT_STATUS_KEY.format(name=...) instead of f-string key construction:\n"
        + "\n".join(violations)
    )


def test_log_type_enum_covers_all_known_values() -> None:
    """LogType must define every value used in SQL queries."""
    from api.constants import LogType

    required = {"proposal", "grade", "reflection", "reasoning_summary", "signal_generated"}
    defined = {member.value for member in LogType}
    missing = required - defined
    assert not missing, f"LogType is missing values used in SQL: {missing}"


def test_all_agent_names_are_screaming_snake_case() -> None:
    """All agent names must be SCREAMING_SNAKE_CASE — never PascalCase."""
    import re

    from api.constants import ALL_AGENT_NAMES

    pascal_pattern = re.compile(r"^[A-Z][a-z]")
    for name in ALL_AGENT_NAMES:
        assert not pascal_pattern.match(name), (
            f"Agent name {name!r} looks PascalCase — must be SCREAMING_SNAKE_CASE. "
            "PascalCase names cause Redis key mismatches."
        )


def test_redis_key_constants_are_format_strings() -> None:
    """Redis key constants that accept parameters must use {placeholder} syntax."""
    from api.constants import REDIS_AGENT_STATUS_KEY

    assert "{name}" in REDIS_AGENT_STATUS_KEY, (
        f"REDIS_AGENT_STATUS_KEY={REDIS_AGENT_STATUS_KEY!r} must contain {{name}} placeholder"
    )


def test_worker_heartbeat_ttl_defined() -> None:
    """WORKER_HEARTBEAT_TTL_SECONDS must exist for background worker liveness keys."""
    from api.constants import WORKER_HEARTBEAT_TTL_SECONDS

    assert isinstance(WORKER_HEARTBEAT_TTL_SECONDS, int)
    assert WORKER_HEARTBEAT_TTL_SECONDS > 0
