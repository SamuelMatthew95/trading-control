"""Guardrail for the SigNoz gateway collector's operation-name normalization.

`observability/signoz/otel-collector-config.yaml` rewrites high-cardinality
span names / attributes (random ``challenger-<hex>`` ids and variable-length
``SET XADD PUBLISH ... XTRIM`` Redis pipeline spans) into stable signatures so
the SigNoz "Operations" table aggregates them into one row each.

This test keeps the OTTL regexes in lock-step with the operation names the app
actually exports (sampled from a real "Top Operations" export). It does not run
the collector — it pins the *patterns* and the pipeline wiring, which is where
a regression would silently let cardinality leak back in.

The OTTL `IsMatch`/`replace_pattern` regexes use RE2 syntax; the subset used
here (``^ $ + [..] (..) \\s \\.``) is identical in Python's ``re``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "observability" / "signoz" / "otel-collector-config.yaml"
)

# --- The OTTL regexes, mirrored from the collector config -------------------
# Each MUST appear verbatim in the YAML (asserted below) so test and config
# cannot drift apart.
RE_CHALLENGER_NAME = r"^agent\.process challenger-[0-9a-f]+$"
RE_REDIS_PIPELINE_XTRIM = r"(?i)^(set\s+xadd\s+publish)(\s+set\s+xadd\s+publish)*\s+xtrim$"
RE_REDIS_PIPELINE = r"(?i)^(set\s+xadd\s+publish)(\s+set\s+xadd\s+publish)*$"
RE_CHALLENGER_ATTR = r"challenger-[0-9a-f]+"

# Canonical low-cardinality replacements (also asserted present in the YAML).
CANON_CHALLENGER = "agent.process challenger-<id>"
CANON_REDIS_XTRIM = "SET XADD PUBLISH XTRIM"
CANON_REDIS = "SET XADD PUBLISH"
CANON_CHALLENGER_ATTR = "challenger-<id>"

# --- Real operation names sampled from the SigNoz "Top Operations" export ---
HIGH_CARDINALITY_CHALLENGERS = [
    "agent.process challenger-6d80ebcb",
    "agent.process challenger-1cbb937e",
    "agent.process challenger-3b5f8264",
    "agent.process challenger-7544e4ea",
    "agent.process challenger-1351c1df",
    "agent.process challenger-7946a01e",
    "agent.process challenger-869219e5",
    "agent.process challenger-65f099d6",
    "agent.process challenger-a594ec89",
]

REDIS_PIPELINES_XTRIM = [
    "SET XADD PUBLISH SET XADD PUBLISH SET XADD PUBLISH XTRIM",
    (
        "SET XADD PUBLISH SET XADD PUBLISH SET XADD PUBLISH "
        "SET XADD PUBLISH SET XADD PUBLISH SET XADD PUBLISH XTRIM"
    ),
]

# Static, already-low-cardinality operations that MUST be left untouched.
STATIC_AGENT_OPS = [
    "agent.process reasoning-agent",
    "agent.process signal-agent",
    "agent.process execution-engine",
    "agent.process notification-agent",
    "agent.process reflection-agent",
    "agent.process ic-updater",
    "agent.process grade-agent",
    "agent.process proposal-applier",
]

STATIC_REDIS_COMMANDS = [
    "GET",
    "SET",
    "XADD",
    "XREADGROUP",
    "XREAD",
    "HGETALL",
    "XTRIM",
    "PING",
    "LRANGE",
    "XGROUP CREATE",
    "XAUTOCLAIM",
]

STATIC_OTHER_OPS = [
    "broker.place_order",
    "tools/call get_health_summary",
    "tools/list",
    "GET /dashboard/state",
]


@pytest.fixture(scope="module")
def config_text() -> str:
    assert CONFIG_PATH.is_file(), f"collector config missing at {CONFIG_PATH}"
    return CONFIG_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Behaviour of the normalization regexes against real operation names.
# ---------------------------------------------------------------------------
class TestChallengerNameNormalization:
    def test_all_challenger_names_match(self):
        pattern = re.compile(RE_CHALLENGER_NAME)
        for name in HIGH_CARDINALITY_CHALLENGERS:
            assert pattern.match(name), f"{name!r} should be normalized"

    def test_static_agents_are_not_matched(self):
        pattern = re.compile(RE_CHALLENGER_NAME)
        for name in STATIC_AGENT_OPS:
            assert not pattern.match(name), f"{name!r} must NOT be rewritten"

    def test_attribute_value_collapses_to_canonical(self):
        # Mirrors replace_pattern(attributes["trading.agent"], ...) on a span/metric.
        for name in HIGH_CARDINALITY_CHALLENGERS:
            agent_attr = name.removeprefix("agent.process ")  # e.g. challenger-6d80ebcb
            collapsed = re.sub(RE_CHALLENGER_ATTR, CANON_CHALLENGER_ATTR, agent_attr)
            assert collapsed == CANON_CHALLENGER_ATTR

    def test_attribute_value_leaves_named_agents_untouched(self):
        for name in STATIC_AGENT_OPS:
            agent_attr = name.removeprefix("agent.process ")
            assert re.sub(RE_CHALLENGER_ATTR, CANON_CHALLENGER_ATTR, agent_attr) == agent_attr


class TestRedisPipelineNormalization:
    def test_xtrim_pipelines_match_xtrim_rule(self):
        pattern = re.compile(RE_REDIS_PIPELINE_XTRIM)
        for name in REDIS_PIPELINES_XTRIM:
            assert pattern.match(name), f"{name!r} should collapse to {CANON_REDIS_XTRIM!r}"

    def test_xtrim_pipelines_excluded_from_non_xtrim_rule(self):
        # The two rules are mutually exclusive via the `$` anchor / XTRIM suffix.
        pattern = re.compile(RE_REDIS_PIPELINE)
        for name in REDIS_PIPELINES_XTRIM:
            assert not pattern.match(name)

    def test_single_occurrence_pipeline_matches_non_xtrim_rule(self):
        assert re.compile(RE_REDIS_PIPELINE).match("SET XADD PUBLISH")
        assert re.compile(RE_REDIS_PIPELINE_XTRIM).match("SET XADD PUBLISH XTRIM")

    def test_casing_and_whitespace_variance_tolerated(self):
        # (?i) + \s+ hardening: lowercase / mixed-case / multi-space variants
        # still collapse, so an instrumentation tweak can't leak cardinality.
        for name in [
            "set xadd publish set xadd publish xtrim",
            "Set Xadd Publish XTRIM",
            "SET  XADD   PUBLISH    XTRIM",
        ]:
            assert re.compile(RE_REDIS_PIPELINE_XTRIM).match(name), name
        assert re.compile(RE_REDIS_PIPELINE).match("set  xadd  publish")

    def test_single_redis_commands_are_not_collapsed(self):
        xtrim = re.compile(RE_REDIS_PIPELINE_XTRIM)
        plain = re.compile(RE_REDIS_PIPELINE)
        for cmd in STATIC_REDIS_COMMANDS:
            assert not xtrim.match(cmd), f"{cmd!r} must NOT match the pipeline rule"
            assert not plain.match(cmd), f"{cmd!r} must NOT match the pipeline rule"

    def test_other_operations_are_untouched(self):
        xtrim = re.compile(RE_REDIS_PIPELINE_XTRIM)
        plain = re.compile(RE_REDIS_PIPELINE)
        name_rule = re.compile(RE_CHALLENGER_NAME)
        for op in STATIC_OTHER_OPS:
            assert not xtrim.match(op)
            assert not plain.match(op)
            assert not name_rule.match(op)


# ---------------------------------------------------------------------------
# The config file actually contains these patterns + canonical names, so the
# mirrored constants above can never drift from the deployed collector.
# ---------------------------------------------------------------------------
class TestConfigContainsPatterns:
    @pytest.mark.parametrize(
        "needle",
        [
            RE_CHALLENGER_NAME,
            RE_REDIS_PIPELINE_XTRIM,
            RE_REDIS_PIPELINE,
            RE_CHALLENGER_ATTR,
            CANON_CHALLENGER,
            CANON_REDIS_XTRIM,
            CANON_REDIS,
            CANON_CHALLENGER_ATTR,
        ],
    )
    def test_pattern_present_in_config(self, config_text: str, needle: str):
        assert needle in config_text, f"{needle!r} missing from collector config"

    def test_ingestion_key_is_env_ref_not_hardcoded(self, config_text: str):
        # The secret must come from the environment, never be committed.
        assert "${env:SIGNOZ_INGESTION_KEY}" in config_text
        assert "signoz-ingestion-key:" in config_text


# ---------------------------------------------------------------------------
# Structural wiring — skipped cleanly if PyYAML isn't installed in this env.
# ---------------------------------------------------------------------------
class TestCollectorPipelineWiring:
    def _load(self):
        yaml = pytest.importorskip("yaml")
        return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_transform_processors_defined(self):
        cfg = self._load()
        processors = cfg["processors"]
        assert "transform/standardize_operations" in processors
        assert "transform/standardize_metrics" in processors

    def test_traces_pipeline_runs_transform_before_export(self):
        cfg = self._load()
        chain = cfg["service"]["pipelines"]["traces"]["processors"]
        assert "transform/standardize_operations" in chain
        # memory_limiter first, batch last, transform in between.
        assert chain.index("memory_limiter") < chain.index("transform/standardize_operations")
        assert chain.index("transform/standardize_operations") < chain.index("batch")

    def test_metrics_pipeline_runs_attribute_transform(self):
        cfg = self._load()
        chain = cfg["service"]["pipelines"]["metrics"]["processors"]
        assert "transform/standardize_metrics" in chain

    def test_exporter_targets_signoz_cloud_with_env_key(self):
        cfg = self._load()
        exporter = cfg["exporters"]["otlp/signoz"]
        assert exporter["endpoint"].endswith("signoz.cloud:443")
        assert exporter["headers"]["signoz-ingestion-key"] == "${env:SIGNOZ_INGESTION_KEY}"


# ---------------------------------------------------------------------------
# Additive R.E.D. generation via the spanmetrics connector (keeps domain metrics).
# ---------------------------------------------------------------------------
class TestSpanmetricsAdditive:
    def _load(self):
        yaml = pytest.importorskip("yaml")
        return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_spanmetrics_connector_defined(self):
        assert "spanmetrics" in self._load().get("connectors", {})

    def test_traces_pipeline_feeds_spanmetrics_and_trace_storage(self):
        exporters = self._load()["service"]["pipelines"]["traces"]["exporters"]
        assert "spanmetrics" in exporters  # RED generation
        assert "otlp/signoz" in exporters  # raw spans still stored

    def test_generated_red_metrics_have_own_pipeline(self):
        pipe = self._load()["service"]["pipelines"]["metrics/spanmetrics"]
        assert pipe["receivers"] == ["spanmetrics"]
        assert "otlp/signoz" in pipe["exporters"]

    def test_uniform_latency_buckets_cover_slow_llm_spans(self):
        buckets = self._load()["connectors"]["spanmetrics"]["histogram"]["explicit"]["buckets"]
        assert all(isinstance(b, str) for b in buckets)  # durations, not bare ints

        def to_seconds(b: str) -> float:
            return float(b[:-2]) / 1000 if b.endswith("ms") else float(b[:-1])

        # Top bucket must exceed the measured reasoning-agent P99 (~66.8s) so the
        # slowest percentile lands in a real bucket instead of the +Inf overflow.
        assert max(to_seconds(b) for b in buckets) >= 90.0

    def test_dimension_allowlist_preserves_trading_schema(self):
        dims = {d["name"] for d in self._load()["connectors"]["spanmetrics"]["dimensions"]}
        # Domain schema preserved — the destructive blueprint would have dropped these.
        assert {"trading.symbol", "trading.agent", "trading.operation"} <= dims


class TestNonDestructiveGuards:
    """Encode the 'additive, keep domain' decision: the destructive RED-only
    governance steps from the blueprint must never be (re)introduced."""

    def _load(self):
        yaml = pytest.importorskip("yaml")
        return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_no_strict_attribute_whitelist(self, config_text: str):
        # A keep-only-http.* whitelist would strip the trading.* domain schema.
        assert "strict_schema" not in config_text

    def test_no_drop_all_custom_metrics_filter(self, config_text: str):
        assert "drop_custom_app_metrics" not in config_text

    def test_app_metrics_pipeline_still_exports_domain_metrics(self):
        # The OTLP app-metrics pipeline (PnL / win_rate / signals / trades / ...)
        # must survive — RED cannot regenerate domain metrics.
        assert "otlp/signoz" in self._load()["service"]["pipelines"]["metrics"]["exporters"]
