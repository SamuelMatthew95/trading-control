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


def test_open_positions_marked_to_market_not_stale_stored_value():
    # Regression: a position whose stored unrealized_pnl is a stale 0.0 (written
    # at fill time) must be marked to market on read, so the Open Positions table
    # (/dashboard/state and get_positions) agrees with the equity-curve figure
    # instead of showing 0.00 for every position.
    s = InMemoryStore()
    s.upsert_position(
        "BTC/USD",
        {
            FieldName.SYMBOL: "BTC/USD",
            FieldName.SIDE: "long",
            FieldName.QTY: 0.04,
            FieldName.QUANTITY: 0.04,
            FieldName.AVG_COST: 73478.16,
            FieldName.LAST_PRICE: 73472.19,
            FieldName.UNREALIZED_PNL: 0.0,  # stale value stored at fill time
        },
    )
    expected = round((73472.19 - 73478.16) * 0.04, 8)
    assert expected != 0.0

    # open_positions() — MCP get_positions / pnl path.
    pos = s.open_positions()[0]
    assert pos[FieldName.UNREALIZED_PNL] == expected
    assert pos[FieldName.PNL] == expected

    # dashboard_fallback_snapshot() — /dashboard/state path the table renders.
    snap_pos = s.dashboard_fallback_snapshot()[FieldName.POSITIONS][0]
    assert snap_pos[FieldName.PNL] == expected

    # paired_pnl_payload() — equity curve / summary. All three must agree.
    paired = s.paired_pnl_payload()
    assert paired[FieldName.OPEN_POSITIONS][0][FieldName.UNREALIZED_PNL] == expected


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
