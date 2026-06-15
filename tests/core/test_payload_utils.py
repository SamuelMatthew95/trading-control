"""Tests for the safe payload-access helpers in api/utils.py."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from api.constants import AgentStatus, FieldName, Source
from api.core import defaults, enums
from api.core.payload_keys import PayloadKey
from api.utils import (
    bytes_to_text,
    clamp,
    cosine_similarity,
    get_dict,
    get_nested,
    get_required_str,
    get_str,
    now_iso,
    parse_agent_status,
    parse_iso_datetime,
    parse_iso_timestamp,
    parse_source,
    safe_float,
    safe_json_loads,
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


class TestSafeFloat:
    def test_coerces_numeric_string(self):
        assert safe_float("42.5") == 42.5

    def test_coerces_int(self):
        assert safe_float(7) == 7.0

    def test_passes_through_float(self):
        assert safe_float(3.14) == 3.14

    def test_none_returns_default_none(self):
        assert safe_float(None) is None

    def test_non_numeric_returns_default_none(self):
        assert safe_float("not-a-number") is None

    def test_custom_default_on_none(self):
        assert safe_float(None, default=0.0) == 0.0

    def test_custom_default_on_bad_value(self):
        assert safe_float("oops", default=0.0) == 0.0

    def test_valid_zero_is_preserved_not_defaulted(self):
        assert safe_float(0, default=99.0) == 0.0


class TestNowIso:
    def test_returns_parseable_iso_string(self):
        value = now_iso()
        assert isinstance(value, str)
        # Round-trips through fromisoformat without raising.
        parsed = datetime.fromisoformat(value)
        assert parsed.tzinfo is not None  # timezone-aware (UTC)


class TestParseIsoDatetime:
    def test_parses_z_suffix_to_utc(self):
        dt = parse_iso_datetime("2026-06-15T03:45:14Z")
        assert dt == datetime(2026, 6, 15, 3, 45, 14, tzinfo=timezone.utc)

    def test_parses_explicit_offset(self):
        dt = parse_iso_datetime("2026-06-15T03:45:14+00:00")
        assert dt.tzinfo is not None and dt.utcoffset().total_seconds() == 0

    def test_naive_treated_as_utc(self):
        dt = parse_iso_datetime("2026-06-15T03:45:14")
        assert dt == datetime(2026, 6, 15, 3, 45, 14, tzinfo=timezone.utc)

    def test_non_utc_offset_converted_to_utc(self):
        dt = parse_iso_datetime("2026-06-15T05:45:14+02:00")
        assert dt == datetime(2026, 6, 15, 3, 45, 14, tzinfo=timezone.utc)

    def test_none_and_empty_return_none(self):
        assert parse_iso_datetime(None) is None
        assert parse_iso_datetime("") is None

    def test_unparseable_returns_none(self):
        assert parse_iso_datetime("not-a-date") is None

    def test_roundtrips_now_iso(self):
        assert parse_iso_datetime(now_iso()) is not None


class TestParseIsoTimestamp:
    def test_returns_epoch_seconds(self):
        ts = parse_iso_timestamp("1970-01-01T00:00:00Z")
        assert ts == 0.0

    def test_none_returns_none(self):
        assert parse_iso_timestamp(None) is None

    def test_unparseable_returns_none(self):
        assert parse_iso_timestamp("garbage") is None


class TestBytesToText:
    def test_decodes_bytes(self):
        assert bytes_to_text(b"hello") == "hello"

    def test_replaces_decode_errors(self):
        # invalid utf-8 byte does not raise
        assert isinstance(bytes_to_text(b"\xff"), str)

    def test_coerces_non_bytes(self):
        assert bytes_to_text(42) == "42"

    def test_passes_through_str(self):
        assert bytes_to_text("x") == "x"


class TestSafeJsonLoads:
    def test_parses_str(self):
        assert safe_json_loads('{"a": 1}') == {"a": 1}

    def test_parses_bytes(self):
        assert safe_json_loads(b'{"a": 1}') == {"a": 1}

    def test_none_returns_default(self):
        assert safe_json_loads(None) is None
        assert safe_json_loads(None, default={}) == {}

    def test_invalid_json_returns_default(self):
        assert safe_json_loads("{not json") is None
        assert safe_json_loads("{not json", default={}) == {}

    def test_non_dict_payload_passes_through(self):
        assert safe_json_loads("[1, 2]") == [1, 2]


class TestClamp:
    def test_within_range(self):
        assert clamp(0.5) == 0.5

    def test_below_lo(self):
        assert clamp(-1.0) == 0.0

    def test_above_hi(self):
        assert clamp(2.0) == 1.0

    def test_custom_bounds(self):
        assert clamp(15, lo=0, hi=10) == 10


class TestCosineSimilarity:
    def test_identical_vectors_are_one(self):
        assert round(cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 6) == 1.0

    def test_orthogonal_vectors_are_zero(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_empty_or_zero_magnitude_is_zero(self):
        assert cosine_similarity([], [1.0]) == 0.0
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_truncates_to_shorter_length(self):
        # extra trailing element on the second vector is ignored
        assert round(cosine_similarity([1.0, 1.0], [1.0, 1.0, 99.0]), 6) == 1.0
