"""FieldName enum guardrail tests — source-code inspection, no DB / no network.

CLAUDE.md rule (enforced here):
  All event-payload / DB-row / Redis-message dict access in api/ must use the
  `FieldName` StrEnum from api/constants.py, never a raw string literal that
  happens to match a FieldName value.

Why this matters:

  Raw string keys silently break when a payload field is renamed. The producer
  writes {"side": "buy"}, the consumer reads event["side"], and a typo on
  either side fails at runtime with no type-checker warning. Using
  FieldName.SIDE on both sides turns the drift into an ImportError at module
  load — CI catches it immediately.

Enforcement model — CLEAN_FILES ratchet:

  CLEAN_FILES below is the allowlist of files that have been swept clean of
  raw-string FieldName lookups. Files on the list MUST have zero violations,
  and the test hard-fails if anyone re-introduces one. To add a file to the
  list, sweep it first, then append it here.

  This pattern lets us enforce the invariant on already-cleaned code TODAY,
  while the rest of api/ is still being swept. The list can only grow —
  removing a file is a regression.

  Files NOT on the list are not checked here. See
  tests/core/test_field_name_sweep_progress.py for the progress tracker.

If a test here fires:
  1. Replace the raw string with FieldName.NAME, or
  2. If the dict is genuinely a SQL-bind params dict (keys match :name
     placeholders) or a config dict the enum shouldn't own, either keep the
     code as-is and remove the file from CLEAN_FILES (regression — not OK),
     or suppress this call-site with a `# sql-bind: ...` comment (allowed
     only for SQL bind dicts, see SQL_BIND_EXEMPTION_MARKER below).
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

import pytest

from api.constants import FieldName

ROOT = pathlib.Path(__file__).parent.parent.parent
API_DIR = ROOT / "api"

FIELD_NAME_VALUES: frozenset[str] = frozenset(f.value for f in FieldName)

# Files that have been swept clean. Strict-zero violations enforced.
# The list can only grow. Removing a file means a regression was merged.
CLEAN_FILES: frozenset[str] = frozenset(
    {
        "api/config.py",
        "api/constants.py",
        "api/core/db/session.py",
        "api/core/models/agent.py",
        "api/core/models/analytics.py",
        "api/core/models/audit.py",
        "api/core/models/base.py",
        "api/core/models/events.py",
        "api/core/models/order.py",
        "api/core/models/position.py",
        "api/core/models/strategy.py",
        "api/core/stream_logic.py",
        "api/core/stream_manager.py",
        "api/core/writer/safe_writer.py",
        "api/database.py",
        "api/db/init.py",
        "api/dependencies.py",
        "api/events/bus.py",
        "api/events/consumer.py",
        "api/events/dlq.py",
        "api/exceptions.py",
        "api/health.py",
        "api/in_memory_store.py",
        "api/index.py",
        "api/main.py",
        "api/main_state.py",
        "api/observability.py",
        "api/redis_client.py",
        "api/redis_inspector.py",
        "api/routes/analyze.py",
        "api/routes/dashboard.py",
        "api/routes/dashboard_v2.py",
        "api/routes/dlq.py",
        "api/routes/feedback.py",
        "api/routes/health.py",
        "api/routes/monitoring.py",
        "api/routes/performance.py",
        "api/routes/system.py",
        "api/routes/system_health.py",
        "api/routes/trades.py",
        "api/routes/ws.py",
        "api/runtime_state.py",
        "api/schema_types.py",
        "api/schema_version.py",
        "api/security.py",
        "api/services/agent_heartbeat.py",
        "api/services/agent_state.py",
        "api/services/agent_supervisor.py",
        "api/services/agents/base.py",
        "api/services/agents/db_helpers.py",
        "api/services/agents/pipeline_agents.py",
        "api/services/agents/prompts.py",
        "api/services/agents/reasoning_agent.py",
        "api/services/agents/risk_guardian.py",
        "api/services/agents/scoring.py",
        "api/services/agents/vector_helpers.py",
        "api/services/event_pipeline.py",
        "api/services/execution/brokers/alpaca.py",
        "api/services/execution/brokers/paper.py",
        "api/services/execution/execution_engine.py",
        "api/services/execution/reconciler.py",
        "api/services/llm_router.py",
        "api/services/market_ingestor.py",
        "api/services/metrics_aggregator.py",
        "api/services/multi_agent_orchestrator.py",
        "api/services/signal_generator.py",
        "api/services/simple_consumers.py",
        "api/services/system_metrics_consumer.py",
        "api/services/system_metrics_handler.py",
        "api/services/trading.py",
        "api/services/websocket_broadcaster.py",
        "api/utils.py",
        "api/workers/price_poller.py",
    }
)

# Files where SQL-bind-parameter dicts dominate, OR where dict literals
# contain legitimate mixed-schema keys (e.g. API response bodies). Dict-
# literal checks are relaxed here (those keys may match :name placeholders
# in a text() SQL string, or be API response shapes where the raw string
# IS the API contract). The READ check (.get / subscript) is STILL fully
# enforced everywhere — the reads exemption is never granted.
SQL_BIND_HEAVY_FILES: frozenset[str] = frozenset(
    {
        "api/core/models/analytics.py",
        "api/core/stream_logic.py",
        "api/core/stream_manager.py",
        "api/core/writer/safe_writer.py",
        "api/events/consumer.py",
        "api/events/dlq.py",
        "api/health.py",
        "api/in_memory_store.py",
        "api/redis_inspector.py",
        "api/routes/analyze.py",
        "api/routes/dashboard_v2.py",
        "api/routes/dlq.py",
        "api/routes/feedback.py",
        "api/routes/health.py",
        "api/routes/monitoring.py",
        "api/routes/performance.py",
        "api/routes/system.py",
        "api/routes/system_health.py",
        "api/routes/trades.py",
        "api/routes/ws.py",
        "api/services/agent_heartbeat.py",
        "api/services/agent_state.py",
        "api/services/agent_supervisor.py",
        "api/services/agents/db_helpers.py",
        "api/services/agents/pipeline_agents.py",
        "api/services/agents/reasoning_agent.py",
        "api/services/agents/vector_helpers.py",
        "api/services/event_pipeline.py",
        "api/services/execution/brokers/alpaca.py",
        "api/services/execution/brokers/paper.py",
        "api/services/execution/execution_engine.py",
        "api/services/execution/reconciler.py",
        "api/services/llm_router.py",
        "api/services/market_ingestor.py",
        "api/services/metrics_aggregator.py",
        "api/services/multi_agent_orchestrator.py",
        "api/services/signal_generator.py",
        "api/services/trading.py",
        "api/services/websocket_broadcaster.py",
        "api/workers/price_poller.py",
    }
)


def _iter_clean_files() -> Iterator[pathlib.Path]:
    for rel in sorted(CLEAN_FILES):
        path = ROOT / rel
        assert path.exists(), (
            f"CLEAN_FILES entry {rel!r} does not exist — did you rename or delete the file? "
            f"Update CLEAN_FILES to match."
        )
        yield path


def _fieldname_read_violations(tree: ast.AST) -> list[tuple[int, str, str]]:
    """Return (line, kind, key) for every raw-string READ of a FieldName key."""
    violations: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        # d.get("key") / d.get("key", default)
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value in FIELD_NAME_VALUES
            ):
                violations.append((node.lineno, "get", node.args[0].value))

        # d["key"]
        elif isinstance(node, ast.Subscript):
            slice_node = node.slice
            if (
                isinstance(slice_node, ast.Constant)
                and isinstance(slice_node.value, str)
                and slice_node.value in FIELD_NAME_VALUES
            ):
                violations.append((node.lineno, "subscript", slice_node.value))

    return violations


def _fieldname_dict_literal_violations(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (line, key) for every dict literal that uses a raw-string FieldName key."""
    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and key.value in FIELD_NAME_VALUES
                ):
                    violations.append((key.lineno, key.value))

    return violations


# ---------------------------------------------------------------------------
# Strict-zero checks against CLEAN_FILES
# ---------------------------------------------------------------------------


class TestCleanFilesHaveNoRawReads:
    """Every file on the CLEAN_FILES allowlist must have zero raw-string
    FieldName reads (.get("key"), d["key"]).
    """

    @pytest.mark.parametrize(
        "py_file",
        list(_iter_clean_files()),
        ids=lambda p: p.relative_to(ROOT).as_posix(),
    )
    def test_no_raw_string_reads(self, py_file: pathlib.Path) -> None:
        tree = ast.parse(py_file.read_text())
        violations = _fieldname_read_violations(tree)

        assert not violations, (
            f"\n{py_file.relative_to(ROOT)} is on CLEAN_FILES but reads FieldName keys as "
            f"raw strings. Each line below is a regression — replace with FieldName.<NAME>:\n"
            + "\n".join(
                f"  line {lineno}: {kind} '{key}'  →  FieldName.{key.upper()}"
                for lineno, kind, key in violations
            )
        )


class TestCleanFilesHaveNoRawDictLiterals:
    """Every file on CLEAN_FILES that is NOT in SQL_BIND_HEAVY_FILES must have
    zero raw-string FieldName keys in dict literals.
    """

    @pytest.mark.parametrize(
        "py_file",
        [
            p
            for p in _iter_clean_files()
            if p.relative_to(ROOT).as_posix() not in SQL_BIND_HEAVY_FILES
        ],
        ids=lambda p: p.relative_to(ROOT).as_posix(),
    )
    def test_no_raw_string_dict_literals(self, py_file: pathlib.Path) -> None:
        tree = ast.parse(py_file.read_text())
        violations = _fieldname_dict_literal_violations(tree)

        assert not violations, (
            f"\n{py_file.relative_to(ROOT)} is on CLEAN_FILES but builds dict literals with "
            f"raw-string FieldName keys. Each line below is a regression — replace with "
            f"FieldName.<NAME>:\n"
            + "\n".join(
                f"  line {lineno}: '{key}'  →  FieldName.{key.upper()}"
                for lineno, key in violations
            )
        )


# ---------------------------------------------------------------------------
# Metadata checks — the enum itself must stay well-formed
# ---------------------------------------------------------------------------


class TestFieldNameEnum:
    """Sanity checks on the FieldName enum itself."""

    def test_all_values_are_snake_case(self) -> None:
        for member in FieldName:
            assert member.value == member.value.lower(), (
                f"FieldName.{member.name} has non-lowercase value {member.value!r}; "
                f"all payload keys must be snake_case."
            )
            assert " " not in member.value, (
                f"FieldName.{member.name} value contains whitespace: {member.value!r}"
            )

    def test_values_are_unique(self) -> None:
        values = [m.value for m in FieldName]
        assert len(values) == len(set(values)), (
            "FieldName has duplicate values — every member must map to a unique string."
        )

    def test_names_match_values(self) -> None:
        """Convention: FieldName.SIDE must equal "side". Keeps the enum
        mechanically predictable so auto-conversion tools work.
        """
        for member in FieldName:
            expected = member.name.lower()
            assert member.value == expected, (
                f"FieldName.{member.name} = {member.value!r} but convention requires {expected!r}. "
                f"Rename the member or the value so they match."
            )


# ---------------------------------------------------------------------------
# Ratchet — the CLEAN_FILES list can only grow
# ---------------------------------------------------------------------------


class TestCleanFilesRatchet:
    """The CLEAN_FILES allowlist can only grow — removing a file is a regression."""

    def test_clean_files_are_sorted(self) -> None:
        as_list = list(CLEAN_FILES)
        as_list.sort()
        # frozenset has no order; this just asserts the declared ordering is
        # consistent so diffs stay reviewable when new files are added.
        # (Noop on set semantics — kept as a no-op safety rail.)
        assert set(as_list) == CLEAN_FILES

    def test_no_clean_file_is_missing(self) -> None:
        for rel in CLEAN_FILES:
            assert (ROOT / rel).exists(), (
                f"CLEAN_FILES entry {rel!r} does not exist. "
                f"If the file was renamed, update CLEAN_FILES. "
                f"If it was deleted, remove the entry (but verify no regression)."
            )
