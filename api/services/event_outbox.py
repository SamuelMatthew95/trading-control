"""
Event outbox pattern for reliable WebSocket delivery.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

RELIABILITY:
- Decouples DB commits from WebSocket broadcasts
- Guarantees event delivery even if WebSocket fails
- Provides retry mechanism for failed broadcasts
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Any, Dict
from enum import Enum
import asyncio
import json

from api.observability import log_structured


class OutboxEventStatus(Enum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class OutboxEvent:
    """Event awaiting reliable delivery to WebSocket."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    payload: Dict[str, Any]
    topic: str = "trades"
    status: OutboxEventStatus = OutboxEventStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=datetime.utcnow)
    published_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    @property
    def is_ready_to_publish(self) -> bool:
        return self.status == OutboxEventStatus.PENDING
    
    @property
    def is_failed(self) -> bool:
        return self.status == OutboxEventStatus.FAILED and self.retry_count >= self.max_retries
    
    @property
    def to_websocket_payload(self) -> Dict[str, Any]:
        """Convert to WebSocket payload format."""
        return {
            "type": "trade_execution",
            "event_id": self.event_id,
            "payload": self.payload,
            "timestamp": self.created_at.isoformat(),
            "retry_count": self.retry_count,
        }


class EventOutbox:
    """Reliable event delivery system."""
    
    def __init__(self, session, broadcaster):
        self.session = session
        self.broadcaster = broadcaster
        self._publishing = False
        self._publish_queue = asyncio.Queue()
    
    async def add_event(self, payload: Dict[str, Any], topic: str = "trades") -> OutboxEvent:
        """Add event to outbox for reliable delivery."""
        event = OutboxEvent(
            payload=payload,
            topic=topic,
        )
        
        # Store in outbox table
        await self._store_event(event)
        
        log_structured(
            "info",
            "outbox_event_added",
            event_id=event.event_id,
            topic=topic,
        )
        
        return event
    
    async def _store_event(self, event: OutboxEvent) -> None:
        """Store event in outbox table."""
        from sqlalchemy import insert
        
        stmt = insert(self._outbox_table).values(
            event_id=event.event_id,
            payload=json.dumps(event.payload),
            topic=event.topic,
            status=event.status.value,
            retry_count=event.retry_count,
            max_retries=event.max_retries,
            created_at=event.created_at,
        )
        
        await self.session.execute(stmt)
        await self.session.flush()
    
    async def process_outbox(self) -> None:
        """Process all pending outbox events."""
        if self._publishing:
            return
        
        self._publishing = True
        try:
            # Get all pending events
            from sqlalchemy import select, update
            
            stmt = select(self._outbox_table).where(
                self._outbox_table.c.status == OutboxEventStatus.PENDING.value
            ).order_by(self._outbox_table.c.created_at)
            
            result = await self.session.execute(stmt)
            pending_events = result.scalars().all()
            
            # Process each event
            for event in pending_events:
                await self._publish_single_event(event)
            
            await self.session.commit()
            
        except Exception as e:
            log_structured(
                "error",
                "outbox_processing_error",
                error=str(e),
                exc_info=True,
            )
            await self.session.rollback()
        finally:
            self._publishing = False
    
    async def _publish_single_event(self, event: OutboxEvent) -> None:
        """Publish single event with retry logic."""
        try:
            # Broadcast to WebSocket
            await self.broadcaster.broadcast(event.to_websocket_payload)
            
            # Mark as published
            await self._mark_event_published(event)
            
            log_structured(
                "info",
                "outbox_event_published",
                event_id=event.event_id,
                topic=event.topic,
            )
            
        except Exception as e:
            # Mark as failed
            await self._mark_event_failed(event, str(e))
            
            log_structured(
                "error",
                "outbox_event_publish_failed",
                event_id=event.event_id,
                error=str(e),
            )
    
    async def _mark_event_published(self, event: OutboxEvent) -> None:
        """Mark event as successfully published."""
        from sqlalchemy import update
        
        stmt = update(self._outbox_table).where(
            self._outbox_table.c.event_id == event.event_id
        ).values(
            status=OutboxEventStatus.PUBLISHED.value,
            published_at=datetime.utcnow(),
        )
        
        await self.session.execute(stmt)
    
    async def _mark_event_failed(self, event: OutboxEvent, error_message: str) -> None:
        """Mark event as failed and increment retry count."""
        from sqlalchemy import update
        
        new_retry_count = event.retry_count + 1
        
        if new_retry_count >= event.max_retries:
            # Max retries exceeded - mark as failed
            status = OutboxEventStatus.FAILED.value
        else:
            # Retry later
            status = OutboxEventStatus.PENDING.value
        
        stmt = update(self._outbox_table).where(
            self._outbox_table.c.event_id == event.event_id
        ).values(
            status=status,
            retry_count=new_retry_count,
            error_message=error_message,
        )
        
        await self.session.execute(stmt)
    
    @property
    def _outbox_table(self):
        """Get outbox table model."""
        from sqlalchemy import Table, Column, String, DateTime, Integer, Text
        
        # Define outbox table if not exists
        return Table(
            'event_outbox',
            self._metadata,
            Column('event_id', String, primary_key=True),
            Column('payload', Text, nullable=False),
            Column('topic', String, nullable=False),
            Column('status', String, nullable=False),
            Column('retry_count', Integer, default=0),
            Column('max_retries', Integer, default=3),
            Column('created_at', DateTime, nullable=False),
            Column('published_at', DateTime, nullable=True),
            Column('error_message', Text, nullable=True),
        )
    
    @property
    def _metadata(self):
        """Get SQLAlchemy metadata."""
        from sqlalchemy import MetaData
        return MetaData()
