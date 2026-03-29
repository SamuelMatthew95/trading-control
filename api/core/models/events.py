"""
Event model - clean architecture.
"""

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.sql import func, text

from .base import Base


class Event(Base):
    __tablename__ = 'events'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    event_type = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    idempotency_key = Column(String, unique=True, nullable=False, index=True)
    processed = Column(Boolean, default=False, nullable=False, index=True)
    data = Column(MutableDict.as_mutable(JSONB), nullable=False, server_default=text("'{}'::jsonb"))
    schema_version = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_events_entity_created', 'entity_type', 'entity_id', 'created_at'),
        Index('idx_events_type_created', 'event_type', 'created_at'),
        Index('idx_events_processed_created', 'processed', 'created_at'),
        Index('idx_events_schema_version', 'schema_version'),
        Index('idx_events_created', 'created_at', postgresql_using='brin'),
        CheckConstraint('schema_version = \'v2\'', name='check_events_schema_v2'),
    )


class ProcessedEvent(Base):
    """Track processed stream messages for claim-first pattern."""
    __tablename__ = 'processed_events'

    msg_id = Column(String, primary_key=True)
    stream = Column(String, nullable=False, index=True)
    processed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_processed_events_stream_time', 'stream', 'processed_at'),
    )
