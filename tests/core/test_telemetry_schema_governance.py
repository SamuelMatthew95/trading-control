"""Guardrail: the telemetry-attribute schema registry is the source of truth.

``TELEMETRY_SCHEMA`` (api/constants.py) declares every ``trading.*`` attribute
the app may emit / use as a RED dimension, plus its cardinality budget. This is
the build-time enforcement layer of the telemetry governance design
(docs/platform/telemetry-governance.md §2 Layer A):

* every ``trading.*`` attribute emitted by ``api/telemetry.py`` is registered, and
* every ``trading.*`` RED dimension in the collector's spanmetrics allowlist is
  registered AND flagged ``is_red_dimension=True``.

A new attribute that skips the registry therefore fails CI instead of silently
expanding cardinality (and the SigNoz bill). Mirrors the lock-step approach of
``test_otel_collector_normalization.py`` — it pins the contract, not a live export.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import api.telemetry as telemetry_mod
from api.constants import TELEMETRY_ATTR_PREFIX, TELEMETRY_SCHEMA, TelemetryAttr

ROOT = Path(__file__).resolve().parents[2]
TELEMETRY_SRC = ROOT / "api" / "telemetry.py"
COLLECTOR_CONFIG = ROOT / "observability" / "signoz" / "otel-collector-config.yaml"

# The two functions every emitted attribute funnels through: _attrs() builds the
# namespaced dict and _add() forwards **attributes into it. Scanning their
# call-site keyword names captures the full emitted set without a live export.
_EMITTER_FUNCS = {"_attrs", "_add"}
# _add(instrument_key, amount=1, **attributes) — amount is not an attribute.
_NON_ATTR_KWARGS = {"amount"}


def _emitted_trading_attrs() -> set[str]:
    """AST-scan api/telemetry.py for the trading.* attributes it emits."""
    tree = ast.parse(TELEMETRY_SRC.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id in _EMITTER_FUNCS):
            continue
        for kw in node.keywords:
            if kw.arg and kw.arg not in _NON_ATTR_KWARGS:
                keys.add(f"{TELEMETRY_ATTR_PREFIX}{kw.arg}")
    return keys


def _collector_trading_dimensions() -> set[str]:
    yaml = pytest.importorskip("yaml")
    cfg = yaml.safe_load(COLLECTOR_CONFIG.read_text(encoding="utf-8"))
    dims = {d["name"] for d in cfg["connectors"]["spanmetrics"]["dimensions"]}
    return {d for d in dims if d.startswith(TELEMETRY_ATTR_PREFIX)}


class TestRegistrySelfConsistency:
    def test_dict_key_matches_entry_key(self):
        for key, attr in TELEMETRY_SCHEMA.items():
            assert isinstance(attr, TelemetryAttr)
            assert key == attr.key

    def test_all_keys_are_namespaced(self):
        for key in TELEMETRY_SCHEMA:
            assert key.startswith(TELEMETRY_ATTR_PREFIX), key

    def test_every_entry_has_owner_and_valid_budget(self):
        for attr in TELEMETRY_SCHEMA.values():
            assert attr.owner, f"{attr.key} has no owner"
            assert attr.cardinality_budget >= 0, attr.key
            # The 0 sentinel (deliberately unbounded) must document itself.
            if attr.cardinality_budget == 0:
                assert attr.note, f"{attr.key} uses the 0 sentinel without a note"

    def test_unbounded_attrs_are_never_red_dimensions(self):
        # An unbounded key as a metric label is the classic cardinality bomb.
        for attr in TELEMETRY_SCHEMA.values():
            if attr.cardinality_budget == 0:
                assert not attr.is_red_dimension, f"{attr.key} is unbounded but a RED dimension"


class TestAppEmissionsAreRegistered:
    def test_telemetry_prefix_matches_registry(self):
        # api/telemetry.py's _ATTR_PREFIX and the registry prefix must not drift.
        assert telemetry_mod._ATTR_PREFIX == TELEMETRY_ATTR_PREFIX

    def test_scan_finds_known_attributes(self):
        # Sanity: the scan actually sees the obvious ones, so a broken scan can't
        # make the enforcement test below pass vacuously.
        emitted = _emitted_trading_attrs()
        for key in ("trading.agent", "trading.symbol", "trading.operation"):
            assert key in emitted, f"scan missed {key}: {sorted(emitted)}"

    def test_every_emitted_attribute_is_registered(self):
        unregistered = _emitted_trading_attrs() - set(TELEMETRY_SCHEMA)
        assert not unregistered, (
            f"api/telemetry.py emits unregistered trading.* attributes: "
            f"{sorted(unregistered)} — add them to TELEMETRY_SCHEMA in api/constants.py"
        )


class TestCollectorDimensionsAreRegistered:
    def test_every_red_dimension_is_registered_and_flagged(self):
        for dim in _collector_trading_dimensions():
            assert dim in TELEMETRY_SCHEMA, f"collector RED dimension {dim} not in TELEMETRY_SCHEMA"
            assert TELEMETRY_SCHEMA[dim].is_red_dimension, (
                f"{dim} is a collector RED dimension but is_red_dimension=False"
            )

    def test_dimensions_scan_is_not_empty(self):
        # Guards against a YAML-shape change silently emptying the check.
        assert _collector_trading_dimensions(), "no trading.* RED dimensions found in collector"
