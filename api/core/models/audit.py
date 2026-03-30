"""
Audit models - clean architecture.
"""

from sqlalchemy import Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text

from .base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False, index=True)
    old_values = Column(Text, nullable=True)
    new_values = Column(Text, nullable=True)
    user_id = Column(String, nullable=True, index=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_audit_created", "created_at"),
        Index("idx_audit_entity", "entity_type", "entity_id"),
    )


class SchemaWriteAudit(Base):
    __tablename__ = "schema_write_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    table_name = Column(String, nullable=False, index=True)
    schema_version = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, index=True)
    operation = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_schema_audit_table_created", "table_name", "created_at"),
        Index("idx_schema_audit_schema_version", "schema_version"),
    )
