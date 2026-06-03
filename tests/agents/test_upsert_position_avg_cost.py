"""upsert_position_db mirrors the broker's authoritative avg cost.

The prior UPDATE never refreshed entry_price/avg_cost, so a DB-mode position
drifted from the PaperBroker's weighted average on an add-to-position (the same
class of bug fixed on the in-memory path). When avg_cost is provided the UPDATE
now sets it; the legacy path (no avg_cost) is unchanged.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api.services.execution.order_writer import upsert_position_db

pytestmark = pytest.mark.asyncio


class _CaptureSession:
    """Mock async session that records (sql, params) and returns the seeded row."""

    def __init__(self, existing_row: dict | None):
        self._existing_row = existing_row
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        result = MagicMock()
        result.mappings.return_value.first.return_value = (
            self._existing_row if "SELECT" in sql else None
        )
        return result


async def test_update_mirrors_broker_avg_cost_when_provided():
    sess = _CaptureSession({"id": "p1", "side": "long", "qty": 10.0})
    await upsert_position_db(
        sess,
        strategy_id="s",
        symbol="BTC/USD",
        side="buy",
        qty=10.0,
        fill_price=120.0,
        avg_cost=110.0,  # broker's weighted average after the add
    )
    update_sql, update_params = sess.calls[-1]
    assert "entry_price = :avg_cost" in update_sql
    assert "avg_cost = :avg_cost" in update_sql
    assert update_params["avg_cost"] == 110.0


async def test_update_leaves_entry_untouched_without_avg_cost():
    sess = _CaptureSession({"id": "p1", "side": "long", "qty": 10.0})
    await upsert_position_db(
        sess, strategy_id="s", symbol="BTC/USD", side="buy", qty=10.0, fill_price=120.0
    )
    update_sql, update_params = sess.calls[-1]
    assert "avg_cost" not in update_sql  # legacy behaviour preserved
    assert "avg_cost" not in update_params


async def test_insert_uses_avg_cost_for_entry_when_provided():
    sess = _CaptureSession(None)  # no existing row → INSERT
    await upsert_position_db(
        sess,
        strategy_id="s",
        symbol="ETH/USD",
        side="buy",
        qty=2.0,
        fill_price=100.0,
        avg_cost=100.0,
    )
    insert_sql, insert_params = sess.calls[-1]
    assert "INSERT INTO positions" in insert_sql
    assert insert_params["entry_price"] == 100.0
