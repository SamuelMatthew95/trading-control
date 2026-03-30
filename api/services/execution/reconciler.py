"""Periodic paper broker reconciliation."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.services.execution.brokers.paper import PaperBroker


class OrderReconciler:
    def __init__(self, broker: PaperBroker, interval_seconds: int = 300):
        self.broker = broker
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="order-reconciler")

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_once(self) -> None:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2)
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text(
                    "SELECT id, broker_order_id, status FROM orders WHERE status IN ('pending', 'partial') AND created_at < :cutoff"
                ),
                {"cutoff": cutoff},
            )
            rows = result.mappings().all()
            for row in rows:
                broker_status = await self.broker.get_order_status(str(row["broker_order_id"]))
                discrepancy = self._build_discrepancy(row, broker_status)
                if discrepancy is None:
                    continue
                await session.execute(
                    text(
                        "INSERT INTO order_reconciliation (order_id, discrepancy, resolved) VALUES (:order_id, CAST(:discrepancy AS JSONB), true)"
                    ),
                    {
                        "order_id": row["id"],
                        "discrepancy": json.dumps(discrepancy, default=str),
                    },
                )
                if broker_status is not None:
                    await session.execute(
                        text("UPDATE orders SET status = :status WHERE id = :order_id"),
                        {"status": broker_status["status"], "order_id": row["id"]},
                    )
                await session.execute(
                    text(
                        "INSERT INTO audit_log (event_type, payload) VALUES ('order_reconciled', CAST(:payload AS JSONB))"
                    ),
                    {"payload": json.dumps(discrepancy, default=str)},
                )
            await session.commit()

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001
                log_structured("warning", "Order reconciliation failed", exc_info=True)
            await asyncio.sleep(self.interval_seconds)  # Reconciliation polling interval - allowed

    def _build_discrepancy(
        self, order_row: dict[str, Any], broker_status: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if broker_status is None:
            return {
                "order_id": str(order_row["id"]),
                "broker_order_id": str(order_row["broker_order_id"]),
                "db_status": order_row["status"],
                "broker_status": "missing",
            }
        if broker_status.get("status") == order_row["status"]:
            return None
        return {
            "order_id": str(order_row["id"]),
            "broker_order_id": str(order_row["broker_order_id"]),
            "db_status": order_row["status"],
            "broker_status": broker_status.get("status"),
        }
