"""
Atomic outbox pattern for WebSocket correctness.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

OUTBOX PATTERN:
- Atomic DB + outbox_event (same transaction)
- Async broadcaster for reliable delivery
- Prevents UI lying when WebSocket fails
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.models.trade_ledger import TradeLedger
from api.observability import log_structured


class OutboxEvent(BaseModel):
    """Outbox event for reliable delivery."""
    event_id: str = Field(..., description="Unique event identifier")
    trade_id: str = Field(..., description="Associated trade ID")
    signal_id: str = Field(..., description="Source signal ID")
    symbol: str = Field(..., description="Trading symbol")
    action: str = Field(..., description="Trade action")
    price: Decimal = Field(..., gt=0, description="Trade price")
    quantity: Decimal = Field(..., gt=0, description="Trade quantity")
    status: str = Field(..., description="Trade status")
    payload: dict[str, Any] = Field(..., description="Event payload")
    created_at: datetime = Field(..., description="Event creation timestamp")
    published_at: datetime | None = Field(None, description="Event publish timestamp")
    retry_count: int = Field(default=0, description="Retry count")
    max_retries: int = Field(default=3, description="Maximum retries")
    error_message: str | None = Field(None, description="Error message")

    @property
    def is_published(self) -> bool:
        """Check if event is published."""
        return self.published_at is not None

    @property
    def is_failed(self) -> bool:
        """Check if event failed permanently."""
        return self.retry_count >= self.max_retries

    @property
    def can_retry(self) -> bool:
        """Check if event can be retried."""
        return not self.is_published and not self.is_failed

    def to_websocket_payload(self) -> dict[str, Any]:
        """Convert to WebSocket payload format."""
        return {
            "type": "trade_execution",
            "event_id": self.event_id,
            "trade_id": self.trade_id,
            "signal_id": self.signal_id,
            "payload": self.payload,
            "timestamp": self.created_at.isoformat(),
            "retry_count": self.retry_count,
        }


class AtomicOutboxManager:
    """Manages atomic outbox operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._outbox_table = self._get_outbox_table()
        self._metadata = self._get_metadata()

    async def create_trade_with_outbox(
        self,
        trade_data: dict[str, Any],
        websocket_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Create trade and outbox event in same atomic transaction.

        This ensures DB commit and outbox creation are atomic.
        """
        try:
            # Start transaction
            async with self.session.begin():
                # Create trade record
                trade = TradeLedger(**trade_data)
                self.session.add(trade)
                await self.session.flush()  # Get trade_id

                # Create outbox event
                outbox_event = OutboxEvent(
                    event_id=str(uuid.uuid4()),
                    trade_id=str(trade.trade_id),
                    signal_id=trade_data.get("signal_id", ""),
                    symbol=trade_data.get("symbol", ""),
                    action=trade_data.get("trade_type", ""),
                    price=trade_data.get("entry_price", Decimal("0")),
                    quantity=trade_data.get("quantity", Decimal("0")),
                    status=trade_data.get("status", ""),
                    payload=websocket_payload,
                    created_at=datetime.now(timezone.utc),
                )

                # Store outbox event
                stmt = self._outbox_table.insert().values(
                    event_id=outbox_event.event_id,
                    trade_id=outbox_event.trade_id,
                    signal_id=outbox_event.signal_id,
                    symbol=outbox_event.symbol,
                    action=outbox_event.action,
                    price=outbox_event.price,
                    quantity=outbox_event.quantity,
                    status=outbox_event.status,
                    payload=json.dumps(outbox_event.payload),
                    created_at=outbox_event.created_at,
                    retry_count=outbox_event.retry_count,
                    max_retries=outbox_event.max_retries,
                )

                await self.session.execute(stmt)

                # Commit both trade and outbox atomically
                await self.session.commit()

                log_structured(
                    "info",
                    "atomic_trade_outbox_created",
                    trade_id=str(trade.trade_id),
                    event_id=outbox_event.event_id,
                    signal_id=outbox_event.signal_id,
                    symbol=outbox_event.symbol,
                )

                return {
                    "trade_id": str(trade.trade_id),
                    "event_id": outbox_event.event_id,
                    "signal_id": outbox_event.signal_id,
                    "symbol": outbox_event.symbol,
                    "status": "created",
                    "atomic": True,
                }

        except Exception as e:
            await self.session.rollback()

            log_structured(
                "error",
                "atomic_trade_outbox_failed",
                error=str(e),
                exc_info=True,
            )

            raise Exception(f"Atomic trade creation failed: {str(e)}")

    async def publish_pending_events(self, broadcaster) -> list[dict[str, Any]]:
        """
        Publish all pending outbox events.

        This runs separately from trade creation to ensure
        WebSocket failures don't affect trade persistence.
        """
        try:
            # Get all pending events
            stmt = select(self._outbox_table).where(
                self._outbox_table.c.published_at.is_(None)
            ).order_by(self._outbox_table.c.created_at)

            result = await self.session.execute(stmt)
            pending_events = result.fetchall()

            published_events = []
            failed_events = []

            for event_data in pending_events:
                try:
                    # Create OutboxEvent object
                    outbox_event = OutboxEvent(
                        event_id=event_data.event_id,
                        trade_id=event_data.trade_id,
                        signal_id=event_data.signal_id,
                        symbol=event_data.symbol,
                        action=event_data.action,
                        price=event_data.price,
                        quantity=event_data.quantity,
                        status=event_data.status,
                        payload=json.loads(event_data.payload),
                        created_at=event_data.created_at,
                        retry_count=event_data.retry_count,
                        max_retries=event_data.max_retries,
                    )

                    # Broadcast to WebSocket
                    await broadcaster.broadcast(outbox_event.to_websocket_payload())

                    # Mark as published
                    await self._mark_event_published(outbox_event.event_id)

                    published_events.append({
                        "event_id": outbox_event.event_id,
                        "trade_id": outbox_event.trade_id,
                        "status": "published",
                    })

                except Exception as e:
                    # Mark as failed or increment retry count
                    await self._mark_event_failed(event_data.event_id, str(e))

                    failed_events.append({
                        "event_id": event_data.event_id,
                        "trade_id": event_data.trade_id,
                        "status": "failed",
                        "error": str(e),
                    })

            log_structured(
                "info",
                "outbox_publish_completed",
                published_count=len(published_events),
                failed_count=len(failed_events),
            )

            return {
                "published_events": published_events,
                "failed_events": failed_events,
                "total_processed": len(pending_events),
            }

        except Exception as e:
            log_structured(
                "error",
                "outbox_publish_error",
                error=str(e),
                exc_info=True,
            )

            raise Exception(f"Outbox publish failed: {str(e)}")

    async def _mark_event_published(self, event_id: str) -> None:
        """Mark event as published."""
        stmt = self._outbox_table.update().where(
            self._outbox_table.c.event_id == event_id
        ).values(
            published_at=datetime.now(timezone.utc),
        )

        await self.session.execute(stmt)
        await self.session.commit()

    async def _mark_event_failed(self, event_id: str, error_message: str) -> None:
        """Mark event as failed or increment retry count."""
        # Get current event
        stmt = select(self._outbox_table).where(
            self._outbox_table.c.event_id == event_id
        )
        result = await self.session.execute(stmt)
        event_data = result.fetchone()

        if not event_data:
            return

        new_retry_count = event_data.retry_count + 1

        if new_retry_count >= event_data.max_retries:
            # Mark as permanently failed
            stmt = self._outbox_table.update().where(
                self._outbox_table.c.event_id == event_id
            ).values(
                retry_count=new_retry_count,
                error_message=error_message,
            )
        else:
            # Increment retry count for later retry
            stmt = self._outbox_table.update().where(
                self._outbox_table.c.event_id == event_id
            ).values(
                retry_count=new_retry_count,
            )

        await self.session.execute(stmt)
        await self.session.commit()

    async def get_outbox_status(self) -> dict[str, Any]:
        """Get outbox status for monitoring."""
        try:
            # Get counts
            total_stmt = select(func.count(self._outbox_table.c.event_id))
            total_result = await self.session.execute(total_stmt)
            total_events = total_result.scalar() or 0

            pending_stmt = select(func.count(self._outbox_table.c.event_id)).where(
                self._outbox_table.c.published_at.is_(None)
            )
            pending_result = await self.session.execute(pending_stmt)
            pending_events = pending_result.scalar() or 0

            published_stmt = select(func.count(self._outbox_table.c.event_id)).where(
                self._outbox_table.c.published_at.isnot(None)
            )
            published_result = await self.session.execute(published_stmt)
            published_events = published_result.scalar() or 0

            failed_stmt = select(func.count(self._outbox_table.c.event_id)).where(
                and_(
                    self._outbox_table.c.retry_count >= self._outbox_table.c.max_retries,
                    self._outbox_table.c.error_message.isnot(None)
                )
            )
            failed_result = await self.session.execute(failed_stmt)
            failed_events = failed_result.scalar() or 0

            return {
                "total_events": total_events,
                "pending_events": pending_events,
                "published_events": published_events,
                "failed_events": failed_events,
                "status_timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            log_structured(
                "error",
                "outbox_status_error",
                error=str(e),
                exc_info=True,
            )

            return {
                "error": str(e),
                "status_timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def _get_outbox_table(self):
        """Get outbox table model."""
        from sqlalchemy import Column, DateTime, Integer, Numeric, String, Table, Text

        return Table(
            'atomic_outbox',
            self._metadata,
            Column('event_id', String, primary_key=True),
            Column('trade_id', String, nullable=False),
            Column('signal_id', String, nullable=False),
            Column('symbol', String, nullable=False),
            Column('action', String, nullable=False),
            Column('price', Numeric, nullable=False),
            Column('quantity', Numeric, nullable=False),
            Column('status', String, nullable=False),
            Column('payload', Text, nullable=False),
            Column('created_at', DateTime, nullable=False),
            Column('published_at', DateTime, nullable=True),
            Column('retry_count', Integer, default=0),
            Column('max_retries', Integer, default=3),
            Column('error_message', Text, nullable=True),
        )

    def _get_metadata(self):
        """Get SQLAlchemy metadata."""
        from sqlalchemy import MetaData
        return MetaData()
