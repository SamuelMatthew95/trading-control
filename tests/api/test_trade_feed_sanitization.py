from api.constants import FieldName
from api.services.dashboard.trading import _normalize_in_memory_trade_row


def test_trade_feed_sanitizes_invalid_numeric_fields():
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
    assert out["degraded_reason"] == "invalid_numeric_fields_sanitized"


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
