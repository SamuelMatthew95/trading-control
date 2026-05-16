"""Tests for the safe payload-access helpers in api/utils.py."""

from __future__ import annotations

import pytest

from api.constants import AgentStatus, FieldName, Source
from api.core import defaults, enums
from api.core.payload_keys import PayloadKey
from api.utils import (
    get_dict,
    get_nested,
    get_required_str,
    get_str,
    parse_agent_status,
    parse_source,
)


class TestGetStr:
    def test_returns_string_value(self):
        assert get_str({FieldName.SYMBOL: "BTC/USD"}, FieldName.SYMBOL) == "BTC/USD"

    def test_missing_key_returns_default(self):
        assert get_str({}, FieldName.SYMBOL, "?") == "?"

    def test_missing_key_without_default_returns_none(self):
        assert get_str({}, FieldName.SYMBOL) is None

    def test_none_value_returns_default(self):
        assert get_str({FieldName.SYMBOL: None}, FieldName.SYMBOL, "?") == "?"

    def test_none_data_returns_default(self):
        assert get_str(None, FieldName.SYMBOL, "?") == "?"

    def test_coerces_non_string_value(self):
        assert get_str({FieldName.QTY: 5}, FieldName.QTY) == "5"

    def test_strips_whitespace_by_default(self):
        assert get_str({FieldName.SYMBOL: "  BTC  "}, FieldName.SYMBOL) == "BTC"

    def test_strip_disabled_preserves_whitespace(self):
        assert get_str({FieldName.SYMBOL: "  BTC  "}, FieldName.SYMBOL, strip=False) == "  BTC  "


class TestGetRequiredStr:
    def test_returns_value_when_present(self):
        assert get_required_str({FieldName.SYMBOL: "BTC/USD"}, FieldName.SYMBOL) == "BTC/USD"

    def test_missing_key_raises_value_error(self):
        with pytest.raises(ValueError, match="missing required key"):
            get_required_str({}, FieldName.SYMBOL)

    def test_blank_value_raises_value_error(self):
        with pytest.raises(ValueError, match="missing required key"):
            get_required_str({FieldName.SYMBOL: "   "}, FieldName.SYMBOL)

    def test_none_data_raises_value_error(self):
        with pytest.raises(ValueError):
            get_required_str(None, FieldName.SYMBOL)

    def test_context_appears_in_error_message(self):
        with pytest.raises(ValueError, match="execution payload"):
            get_required_str({}, FieldName.SYMBOL, context="execution payload")


class TestGetDict:
    def test_returns_dict_value(self):
        inner = {FieldName.SIDE: "buy"}
        assert get_dict({FieldName.METADATA: inner}, FieldName.METADATA) == inner

    def test_missing_key_returns_empty_dict(self):
        assert get_dict({}, FieldName.METADATA) == {}

    def test_non_dict_value_returns_empty_dict(self):
        assert get_dict({FieldName.METADATA: "oops"}, FieldName.METADATA) == {}

    def test_none_data_returns_empty_dict(self):
        assert get_dict(None, FieldName.METADATA) == {}

    def test_returned_empty_dict_is_fresh(self):
        first = get_dict({}, FieldName.METADATA)
        first["x"] = 1
        assert get_dict({}, FieldName.METADATA) == {}


class TestGetNested:
    def test_walks_full_chain(self):
        data = {"a": {"b": {"c": 42}}}
        assert get_nested(data, "a", "b", "c") == 42

    def test_single_key(self):
        assert get_nested({"a": 1}, "a") == 1

    def test_missing_mid_level_returns_default(self):
        assert get_nested({"a": {}}, "a", "b", "c", default=0) == 0

    def test_non_mapping_mid_level_returns_default(self):
        assert get_nested({"a": "scalar"}, "a", "b", default="x") == "x"

    def test_none_value_mid_level_returns_default(self):
        assert get_nested({"a": {"b": None}}, "a", "b", "c", default=0) == 0

    def test_none_data_returns_default(self):
        assert get_nested(None, "a", "b", default=0) == 0

    def test_default_is_none_when_unspecified(self):
        assert get_nested({}, "a", "b") is None


class TestParseSource:
    def test_known_value(self):
        assert parse_source("db") is Source.DB
        assert parse_source("in_memory") is Source.IN_MEMORY

    def test_case_and_whitespace_insensitive(self):
        assert parse_source("  REDIS ") is Source.REDIS

    def test_unknown_value_maps_to_fallback(self):
        assert parse_source("nonsense") is Source.FALLBACK

    def test_none_maps_to_fallback(self):
        assert parse_source(None) is Source.FALLBACK


class TestParseAgentStatus:
    def test_known_value(self):
        assert parse_agent_status("ACTIVE") is AgentStatus.ACTIVE

    def test_case_and_whitespace_insensitive(self):
        assert parse_agent_status(" stale ") is AgentStatus.STALE

    def test_unknown_value_maps_to_unknown(self):
        assert parse_agent_status("bogus") is AgentStatus.UNKNOWN

    def test_none_maps_to_unknown(self):
        assert parse_agent_status(None) is AgentStatus.UNKNOWN


class TestCoreFacadeModules:
    def test_payload_key_is_field_name(self):
        assert PayloadKey is FieldName

    def test_enums_reexport_canonical(self):
        assert enums.Source is Source
        assert enums.AgentStatus is AgentStatus

    def test_defaults_reexport_canonical(self):
        assert defaults.DEFAULT_TRACE_ID == "unknown-trace"
        assert defaults.UNKNOWN_VALUE == "unknown"
