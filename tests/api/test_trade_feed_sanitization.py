from api.constants import FieldName
from api.services.dashboard.trading import _normalize_in_memory_trade_row


def test_trade_feed_flags_only_genuinely_malformed_numeric_fields():
    # "bad" is genuine garbage and must be sanitized + flagged. The null-like
    # sentinels ("", "  ", "null", "None") are legitimately-absent values and
    # must parse to None WITHOUT being reported as degraded.
    row = {
        FieldName.ID: "1",
        FieldName.SYMBOL: "BTC/USD",
        FieldName.SIDE: "buy",
        FieldName.QTY: "",
        FieldName.ENTRY_PRICE: "  ",
        FieldName.EXIT_PRICE: "null",
        FieldName.PNL: "None",
        FieldName.PNL_PERCENT: "bad",
        FieldName.FILLED_AT: "2026-01-01T00:00:00Z",
    }
    out = _normalize_in_memory_trade_row(row)
    assert out is not None
    assert out["qty"] is None
    assert out["entry_price"] is None
    assert out["exit_price"] is None
    assert out["pnl"] is None
    assert out["pnl_percent"] is None
    # Only the genuinely-malformed field is flagged — not the null-like ones.
    assert out["sanitized_fields"] == ["pnl_percent"]
    assert out["degraded_reason"] == "invalid_numeric_fields_sanitized"


def test_open_position_with_absent_exit_and_pnl_is_not_degraded():
    # An open BUY has no exit price or realized P&L yet. Whether those arrive as
    # real None or the stringified "None"/"null" the in-memory store sometimes
    # writes, the row is a normal open position — it must never be "degraded".
    row = {
        FieldName.ID: "open-1",
        FieldName.SYMBOL: "BTC/USD",
        FieldName.SIDE: "buy",
        FieldName.QTY: 0.0204,
        FieldName.ENTRY_PRICE: 73478.16,
        FieldName.EXIT_PRICE: "None",
        FieldName.PNL: None,
        FieldName.PNL_PERCENT: 0.0,
        FieldName.FILLED_AT: "2026-05-31T14:18:53Z",
    }
    out = _normalize_in_memory_trade_row(row)
    assert out is not None
    assert out["entry_price"] == 73478.16
    assert out["exit_price"] is None
    assert out["pnl"] is None
    assert out["pnl_percent"] == 0.0
    assert "degraded_reason" not in out
    assert "sanitized_fields" not in out


def test_trade_feed_drops_non_finite_numeric_values():
    # NaN/Inf must never reach the JSON response as bare NaN tokens; they are
    # treated as absent, and (being null-like) do not mark the row degraded.
    row = {
        FieldName.ID: "3",
        FieldName.SYMBOL: "ETH/USD",
        FieldName.SIDE: "buy",
        FieldName.QTY: float("nan"),
        FieldName.ENTRY_PRICE: float("inf"),
        FieldName.PNL: "NaN",
    }
    out = _normalize_in_memory_trade_row(row)
    assert out is not None
    assert out["qty"] is None
    assert out["entry_price"] is None
    assert out["pnl"] is None
    assert "degraded_reason" not in out


def test_trade_feed_preserves_valid_zero_values():
    row = {
        FieldName.ID: "2",
        FieldName.SYMBOL: "BTC/USD",
        FieldName.SIDE: "sell",
        FieldName.QTY: "0",
        FieldName.PNL: 0.0,
    }
    out = _normalize_in_memory_trade_row(row)
    assert out is not None
    assert out["qty"] == 0.0
    assert out["pnl"] == 0.0
