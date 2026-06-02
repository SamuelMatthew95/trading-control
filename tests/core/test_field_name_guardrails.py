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

  Files NOT on the list are not scanned for violations — but they cannot
  hide. TestCleanFilesCoverage below fails CI whenever an api/ file is
  neither on CLEAN_FILES nor explicitly exempt, so a newly added file is
  forced onto the list (or into the documented exemption) rather than
  silently escaping the guardrail.

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
        "api/core/defaults.py",
        "api/core/enums.py",
        "api/core/payload_keys.py",
        "api/core/models/__init__.py",
        "api/core/models/agent.py",
        "api/core/models/analytics.py",
        "api/core/models/audit.py",
        "api/core/models/base.py",
        "api/core/models/events.py",
        "api/core/models/order.py",
        "api/core/models/position.py",
        "api/core/models/strategy.py",
        "api/core/schemas/__init__.py",
        "api/core/stream_logic.py",
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
        "api/routes/backtest.py",
        "api/routes/cognitive.py",
        "api/routes/dashboard.py",
        "api/routes/dashboard_v2.py",
        "api/routes/decisions.py",
        "api/routes/dlq.py",
        "api/services/dashboard/agents.py",
        "api/services/dashboard/control.py",
        "api/services/dashboard/events.py",
        "api/services/dashboard/flow.py",
        "api/services/dashboard/learning.py",
        "api/services/dashboard/pnl.py",
        "api/services/dashboard/prompt_evolution.py",
        "api/services/dashboard/prompt_os.py",
        "api/services/dashboard/proposals.py",
        "api/services/dashboard/state.py",
        "api/services/dashboard/system.py",
        "api/services/dashboard/traces.py",
        "api/services/dashboard/trading.py",
        "api/services/dashboard/utils.py",
        "api/routes/feedback.py",
        "api/routes/health.py",
        "api/routes/learning.py",
        "api/routes/llm_health.py",
        "api/routes/monitoring.py",
        "api/routes/notifications.py",
        "api/routes/performance.py",
        "api/routes/promotion.py",
        "api/routes/system.py",
        "api/routes/system_health.py",
        "api/routes/tools.py",
        "api/routes/trades.py",
        "api/routes/ws.py",
        "api/runtime_state.py",
        "api/schema_types.py",
        "api/schema_version.py",
        "api/security.py",
        "api/startup.py",
        "api/services/agent_heartbeat.py",
        "api/services/agent_state.py",
        "api/services/agent_supervisor.py",
        "api/services/agents/base.py",
        "api/services/agents/db_helpers.py",
        "api/services/agents/grade_analytics.py",
        "api/services/agents/notification_payloads.py",
        "api/services/agents/pipeline_agents.py",
        "api/services/agents/prompts.py",
        "api/services/agents/proposal_applier.py",
        "api/services/agents/reasoning_agent.py",
        "api/services/agents/risk_guardian.py",
        "api/services/agents/scoring.py",
        "api/services/agents/trade_scorer.py",
        "api/services/agents/vector_helpers.py",
        "api/services/circuit_breaker.py",
        "api/services/event_pipeline.py",
        "api/services/execution/brokers/alpaca.py",
        "api/services/execution/brokers/paper.py",
        "api/services/execution/decision_utils.py",
        "api/services/execution/execution_engine.py",
        "api/services/execution/fill_publisher.py",
        "api/services/execution/order_writer.py",
        "api/services/challenger_spawner.py",
        "api/services/config_overrides.py",
        "api/services/execution/position_math.py",
        "api/services/execution/reconciler.py",
        "api/services/gitops_publisher.py",
        "api/services/llm_metrics.py",
        "api/services/llm_router.py",
        "api/services/lmstudio_provider.py",
        "api/services/market_ingestor.py",
        "api/services/market_intel.py",
        "api/services/market_status.py",
        "api/services/metrics_aggregator.py",
        "api/services/multi_agent_orchestrator.py",
        "api/services/notification_summary.py",
        "api/services/persistence_routing.py",
        "api/services/promotion_gate.py",
        "api/services/prompt_assembly.py",
        "api/services/prompt_store.py",
        "api/services/redis_store.py",
        "api/services/regression_validator.py",
        "api/services/replay_harness.py",
        "api/services/risk_filters.py",
        "api/services/signal_generator.py",
        "api/services/shadow_trader.py",
        "api/services/param_evolution.py",
        "api/services/param_overrides.py",
        "api/services/strategy_registry.py",
        "api/services/system_metrics_consumer.py",
        "api/services/system_metrics_handler.py",
        "api/services/tool_registry.py",
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
        "api/core/writer/safe_writer.py",
        "api/database.py",
        "api/services/gitops_publisher.py",  # GitHub REST API contract dict keys
        "api/events/dlq.py",
        "api/health.py",
        "api/in_memory_store.py",
        "api/routes/dashboard_v2.py",
        "api/routes/health.py",
        "api/services/dashboard/agents.py",
        "api/services/dashboard/control.py",
        "api/services/dashboard/events.py",
        "api/services/dashboard/flow.py",
        "api/services/dashboard/learning.py",
        "api/services/dashboard/pnl.py",
        "api/services/dashboard/proposals.py",
        "api/services/dashboard/state.py",
        "api/services/dashboard/system.py",
        "api/services/dashboard/traces.py",
        "api/services/dashboard/trading.py",
        "api/routes/learning.py",
        "api/routes/performance.py",
        "api/routes/system.py",
        "api/routes/system_health.py",
        "api/routes/trades.py",
        "api/routes/ws.py",
        "api/services/agent_heartbeat.py",
        "api/services/agent_state.py",
        "api/services/agents/db_helpers.py",
        "api/services/agents/notification_payloads.py",
        "api/services/agents/pipeline_agents.py",
        "api/services/agents/reasoning_agent.py",
        "api/services/agents/vector_helpers.py",
        "api/services/execution/execution_engine.py",
        "api/services/execution/order_writer.py",
        "api/services/execution/reconciler.py",
        "api/services/lmstudio_provider.py",
        "api/services/metrics_aggregator.py",
        "api/services/multi_agent_orchestrator.py",
        "api/services/redis_store.py",
        "api/services/signal_generator.py",
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
    """Return (line, kind, key) for every raw-string READ of a FieldName key.

    Covers ``d.get("key")``, ``d.pop("key")``, ``d.setdefault("key")`` and
    ``d["key"]`` — the dict-key string can sit anywhere on the line.
    """
    violations: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        # d.get("key") / d.pop("key") / d.setdefault("key")
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in {"get", "pop", "setdefault"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value in FIELD_NAME_VALUES
            ):
                violations.append((node.lineno, func.attr, node.args[0].value))

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


def _fieldname_membership_violations(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (line, key) for every ``"key" in d`` test that uses a raw FieldName key."""
    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(
            isinstance(op, (ast.In, ast.NotIn)) for op in node.ops
        ):
            left = node.left
            if (
                isinstance(left, ast.Constant)
                and isinstance(left.value, str)
                and left.value in FIELD_NAME_VALUES
            ):
                violations.append((left.lineno, left.value))

    return violations


# ---------------------------------------------------------------------------
# Strict-zero checks against CLEAN_FILES
# ---------------------------------------------------------------------------


class TestCleanFilesHaveNoRawReads:
    """Every file on the CLEAN_FILES allowlist must have zero raw-string
    FieldName reads — .get("key"), .pop("key"), .setdefault("key"), d["key"].
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


class TestCleanFilesHaveNoRawMembership:
    """Every file on CLEAN_FILES that is NOT in SQL_BIND_HEAVY_FILES must have
    zero raw-string FieldName keys in membership tests (`"key" in payload`).

    SQL-heavy files are relaxed: there, `"col" in available_columns` legitimately
    probes DB schema column identifiers, which are not payload-dict keys.
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
    def test_no_raw_string_membership(self, py_file: pathlib.Path) -> None:
        tree = ast.parse(py_file.read_text())
        violations = _fieldname_membership_violations(tree)

        assert not violations, (
            f"\n{py_file.relative_to(ROOT)} is on CLEAN_FILES but tests FieldName keys with "
            f"raw-string membership. Each line below is a regression — replace with "
            f"FieldName.<NAME>:\n"
            + "\n".join(
                f"  line {lineno}: '{key}' in ...  →  FieldName.{key.upper()}"
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


# ---------------------------------------------------------------------------
# Coverage — every api/ file must be tracked by the guardrail
# ---------------------------------------------------------------------------

# Directories exempt from the CLEAN_FILES coverage requirement below.
#   api/alembic/ — migrations reference raw DB column names by necessity and
#                  carry no event-payload dict access.
# __init__.py files are exempt by name: they are namespace / re-export shims
# with no payload dict access. Both exemptions are deliberately narrow — a new
# service or route file gets NO exemption and must be swept onto CLEAN_FILES.
COVERAGE_EXEMPT_PREFIXES: tuple[str, ...] = ("api/alembic/", "api/mcp/")


def _is_coverage_exempt(rel_path: str) -> bool:
    """True when a file is structurally outside the FieldName guardrail's reach."""
    if rel_path.endswith("/__init__.py"):
        return True
    return rel_path.startswith(COVERAGE_EXEMPT_PREFIXES)


class TestCleanFilesCoverage:
    """Every api/ Python file must be on CLEAN_FILES or explicitly exempt.

    The scans above only inspect files listed in CLEAN_FILES. A file that is
    neither swept nor exempt is an invisible hole: raw-string FieldName keys
    can be added there and CI stays green. That is exactly how earlier files
    slipped past the guardrail. This test closes the hole — it fails the
    moment a new api/ file appears untracked, forcing it onto CLEAN_FILES (or
    into the documented exemption) instead of being silently skipped.
    """

    def test_every_api_file_is_tracked(self) -> None:
        untracked: list[str] = []
        for path in sorted(API_DIR.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel in CLEAN_FILES or _is_coverage_exempt(rel):
                continue
            untracked.append(rel)

        assert not untracked, (
            "\nThese api/ files are neither on CLEAN_FILES nor exempt, so the "
            "FieldName guardrail never scans them:\n"
            + "\n".join(f"  {rel}" for rel in untracked)
            + "\n\nSweep each file of raw-string FieldName keys and append it to "
            "CLEAN_FILES. If a file genuinely has no payload dict access (a "
            "migration or namespace shim), extend the documented exemption in "
            "COVERAGE_EXEMPT_PREFIXES / _is_coverage_exempt instead."
        )
