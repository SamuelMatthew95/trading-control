from api.constants import FieldName
from api.in_memory_store import InMemoryStore


def test_unrealized_pnl_long_and_short_and_missing_price():
    s = InMemoryStore()
    s.upsert_position(
        "BTC/USD",
        {
            FieldName.SYMBOL: "BTC/USD",
            FieldName.SIDE: "long",
            FieldName.QTY: 2.0,
            FieldName.AVG_ENTRY_PRICE: 100.0,
            FieldName.PRICE: 110.0,
        },
    )
    s.upsert_position(
        "ETH/USD",
        {
            FieldName.SYMBOL: "ETH/USD",
            FieldName.SIDE: "short",
            FieldName.QTY: 3.0,
            FieldName.AVG_ENTRY_PRICE: 100.0,
            FieldName.PRICE: 90.0,
        },
    )
    s.upsert_position(
        "SOL/USD",
        {
            FieldName.SYMBOL: "SOL/USD",
            FieldName.SIDE: "long",
            FieldName.QTY: 1.0,
            FieldName.AVG_ENTRY_PRICE: 50.0,
        },
    )

    payload = s.paired_pnl_payload()
    rows = {r[FieldName.SYMBOL]: r for r in payload[FieldName.OPEN_POSITIONS]}
    assert rows["BTC/USD"][FieldName.UNREALIZED_PNL] == 20.0
    assert rows["ETH/USD"][FieldName.UNREALIZED_PNL] == 30.0
    assert rows["SOL/USD"][FieldName.UNREALIZED_PNL] is None


def test_unrealized_pnl_short_with_negative_qty_uses_absolute_position_size():
    s = InMemoryStore()
    s.upsert_position(
        "ETH/USD",
        {
            FieldName.SYMBOL: "ETH/USD",
            FieldName.SIDE: "short",
            FieldName.QTY: -3.0,
            FieldName.AVG_ENTRY_PRICE: 100.0,
            FieldName.PRICE: 90.0,
        },
    )
    payload = s.paired_pnl_payload()
    rows = {r[FieldName.SYMBOL]: r for r in payload[FieldName.OPEN_POSITIONS]}
    assert rows["ETH/USD"][FieldName.UNREALIZED_PNL] == 30.0
