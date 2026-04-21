"""
Database Guard - Claim-First Pattern with atomic processing.

Exactly-once semantics through processed_events claim mechanism.
PostgreSQL upserts for safe concurrent writes.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.constants import SOURCE_REFLECTION, FieldName, OrderStatus, PositionSide
from api.observability import log_structured
from api.schema_version import DB_SCHEMA_VERSION

from ..models import (
    AgentGrades,
    AgentLog,
    Event,
    Order,
    Position,
    ProcessedEvent,
    SystemMetrics,
    TradePerformance,
    VectorMemory,
)

logger = logging.getLogger(__name__)


class SafeWriter:
    """Atomic database writer with claim-first pattern and validation."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def _validate_schema_v3(self, data: dict[str, Any], model_name: str) -> None:
        """Strict V3 schema validation - centralized enforcement."""
        # All models must have schema_version
        if FieldName.SCHEMA_VERSION not in data:
            raise ValueError(f"{model_name}: Missing required field 'schema_version'")

        if data[FieldName.SCHEMA_VERSION] != DB_SCHEMA_VERSION:
            raise ValueError(
                f"{model_name}: Invalid schema version '{data[FieldName.SCHEMA_VERSION]}'. Expected '{DB_SCHEMA_VERSION}'"
            )

        # Source field validation for models that have it
        if model_name in [
            "Order",
            "Event",
            "VectorMemory",
            "AgentLog",
            "SystemMetrics",
            "TradePerformance",
        ]:
            if FieldName.SOURCE not in data or not data[FieldName.SOURCE]:
                raise ValueError(f"{model_name}: Source field is required and cannot be empty")

        # Trace ID validation for v3 (optional for notifications)
        if model_name != "Notification":
            if FieldName.TRACE_ID not in data or not data[FieldName.TRACE_ID]:
                raise ValueError(f"{model_name}: trace_id field is required for v3 events")

    def _validate_schema_v2(self, data: dict[str, Any], model_name: str) -> None:
        """V2 schema validation for backward compatibility."""
        # All models must have schema_version
        if FieldName.SCHEMA_VERSION not in data:
            raise ValueError(f"{model_name}: Missing required field 'schema_version'")

        if data[FieldName.SCHEMA_VERSION] != "v2":
            raise ValueError(
                f"{model_name}: Invalid schema version '{data[FieldName.SCHEMA_VERSION]}'. Expected 'v2'"
            )

    def _log_write_operation(self, operation: str, model_name: str, entity_id: str) -> None:
        """Log write operations with proper context."""
        if not entity_id:
            raise ValueError("entity_id is required for audit logging")

        log_structured("info", "write audit", operation=operation, model=model_name, id=entity_id)

    @asynccontextmanager
    async def transaction(self):
        """Atomic transaction context manager."""
        async with self.session_factory() as session:
            async with session.begin():
                yield session

    def validate_payload(
        self, data: dict[str, Any], required_fields: list[str], operation: str = ""
    ) -> None:
        """Validate required fields exist and have correct types."""
        for field in required_fields:
            if field not in data or data[field] is None:
                raise ValueError(f"Missing required field: {field}")

        # Validate idempotency_key for financial operations
        financial_operations = [
            "write_order",
            "write_execution",
            "write_trade_performance",
        ]
        if operation in financial_operations:
            if FieldName.IDEMPOTENCY_KEY not in data or not data[FieldName.IDEMPOTENCY_KEY]:
                raise ValueError(f"idempotency_key is required for {operation}")

    def safe_parse_dt(self, dt_str: str | None) -> datetime | None:
        """Safely parse ISO datetime strings."""
        if not dt_str:
            return None

        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            log_structured("warning", "datetime parse failed", dt_str=dt_str, exc_info=True)
            return None

    async def _claim_message(self, session: AsyncSession, msg_id: str, stream: str) -> bool:
        """Atomically claim message with RETURNING to check success."""
        try:
            result = await session.execute(
                pg_insert(ProcessedEvent)
                .values(msg_id=msg_id, stream=stream)
                .on_conflict_do_nothing()
                .returning(ProcessedEvent.msg_id)
            )
            return result.scalar() is not None
        except IntegrityError:
            # Message already processed
            log_structured("debug", "message already claimed", msg_id=msg_id)
            return False

    async def write_order(self, msg_id: str, stream: str, data: dict[str, Any]) -> bool:
        """Write order with atomic claim-at-end pattern."""
        if not msg_id:
            raise ValueError("msg_id is required for write_order")

        async with self.transaction() as session:
            try:
                # Strict V3 schema validation
                self._validate_schema_v3(data, "Order")
                self.validate_payload(
                    data,
                    ["strategy_id", "symbol", "side", "order_type", "quantity"],
                    "write_order",
                )

                # Require idempotency_key (fix NULL dedup issue)
                idempotency_key = data.get(FieldName.IDEMPOTENCY_KEY)
                if not idempotency_key:
                    raise ValueError("idempotency_key is required for order deduplication")

                # Log the operation
                self._log_write_operation("write_order", "Order", msg_id)

                # STEP 1: Insert Order FIRST (business logic)
                order = Order(
                    strategy_id=data[FieldName.STRATEGY_ID],
                    external_order_id=data.get(FieldName.EXTERNAL_ORDER_ID),
                    idempotency_key=idempotency_key,
                    symbol=data[FieldName.SYMBOL],
                    side=data[FieldName.SIDE],
                    order_type=data[FieldName.ORDER_TYPE],
                    quantity=data[FieldName.QUANTITY],
                    price=data.get(FieldName.PRICE),
                    exchange=data.get(FieldName.EXCHANGE),
                    order_metadata=data.get(FieldName.METADATA, {}),
                )

                # Handle upsert with race condition protection
                try:
                    session.add(order)
                    await session.flush()  # Try to insert
                    order_id = order.id  # Capture the actual persisted ID after flush
                except IntegrityError:
                    # Verify the idempotency key maps to the same existing order
                    from sqlalchemy import select

                    existing = await session.execute(
                        select(Order).where(Order.idempotency_key == idempotency_key)
                    )
                    if not existing.scalar():
                        raise ValueError(
                            f"IntegrityError but no existing order found "
                            f"for idempotency_key={idempotency_key}"
                        ) from None

                    # Get the existing order's ID
                    existing_order = existing.scalar_one()
                    order_id = existing_order.id
                    log_structured(
                        "info",
                        "write order duplicate",
                        msg_id=msg_id,
                        idempotency_key=idempotency_key,
                    )

                # STEP 2: Insert Event (audit trail)
                event = Event(
                    event_type="order.created",
                    entity_type="order",
                    entity_id=order_id,  # Use the persisted order ID
                    idempotency_key=msg_id,  # Use msg_id for Event dedup
                    data=data,
                )
                session.add(event)
                await session.flush()  # Ensure event persists

                # STEP 3: CLAIM LAST (atomic guarantee)
                claim = ProcessedEvent(msg_id=msg_id, stream=stream)
                session.add(claim)
                await session.flush()  # Final flush before commit

                log_structured(
                    "info",
                    "write order",
                    msg_id=msg_id,
                    stream=stream,
                    symbol=data[FieldName.SYMBOL],
                )
                return True

            except Exception:
                log_structured(
                    "error",
                    "write order failed",
                    msg_id=msg_id,
                    stream=stream,
                    exc_info=True,
                )
                raise

    async def write_execution(self, msg_id: str, stream: str, data: dict[str, Any]) -> bool:
        """Write execution with atomic claim-at-end and order existence check."""
        if not msg_id:
            raise ValueError("msg_id is required for write_execution")

        async with self.transaction() as session:
            try:
                # Strict V3 schema validation
                self._validate_schema_v3(data, "Event")
                self.validate_payload(data, ["strategy_id", "symbol", "order_id"])

                # Log the operation
                self._log_write_operation("write_execution", "Event", msg_id)

                # Insert event
                await session.execute(
                    insert(Event).values(
                        event_type="order.filled",
                        entity_type="order",
                        entity_id=data[FieldName.ORDER_ID],
                        data=data,
                    )
                )

                # Update order with existence check (fix silent failure)
                result = await session.execute(
                    update(Order)
                    .where(Order.id == data[FieldName.ORDER_ID])
                    .values(
                        filled_quantity=data.get(FieldName.FILLED_QUANTITY),
                        filled_price=data.get(FieldName.FILLED_PRICE),
                        status=OrderStatus.FILLED,
                        commission=data.get(FieldName.COMMISSION, 0),
                    )
                )

                if result.rowcount == 0:
                    raise ValueError(f"Order {data[FieldName.ORDER_ID]} not found for execution")

                # Upsert position with on_conflict_do_update
                position_stmt = (
                    pg_insert(Position)
                    .values(
                        strategy_id=data[FieldName.STRATEGY_ID],
                        symbol=data[FieldName.SYMBOL],
                        quantity=data.get(FieldName.NEW_QUANTITY),
                        avg_cost=data.get(FieldName.NEW_AVG_COST),
                        market_value=data.get(FieldName.MARKET_VALUE),
                        unrealized_pnl=data.get(FieldName.UNREALIZED_PNL, 0),
                        last_price=data.get(FieldName.FILLED_PRICE),
                        metadata=data.get(FieldName.METADATA, {}),
                    )
                    .on_conflict_do_update(
                        index_elements=["strategy_id", "symbol"],
                        set_={
                            "quantity": data.get(FieldName.NEW_QUANTITY),
                            "avg_cost": data.get(FieldName.NEW_AVG_COST),
                            "market_value": data.get(FieldName.MARKET_VALUE),
                            "unrealized_pnl": data.get(FieldName.UNREALIZED_PNL, 0),
                            "last_price": data.get(FieldName.FILLED_PRICE),
                            "updated_at": func.now(),
                        },
                    )
                )

                await session.execute(position_stmt)

                # CLAIM LAST (same transaction) - ATOMIC GUARANTEE
                claim_result = await session.execute(
                    pg_insert(ProcessedEvent)
                    .values(msg_id=msg_id, stream=stream)
                    .on_conflict_do_nothing()
                    .returning(ProcessedEvent.msg_id)
                )

                if claim_result.scalar() is None:
                    raise ValueError(f"Message {msg_id} was already processed in this transaction")

                log_structured(
                    "info",
                    "write success",
                    msg_id=msg_id,
                    stream=stream,
                    order_id=data[FieldName.ORDER_ID],
                )
                return True

            except Exception:
                log_structured("error", "write error", msg_id=msg_id, stream=stream, exc_info=True)
                raise

    async def write_agent_log(self, msg_id: str, stream: str, data: dict[str, Any]) -> bool:
        """Write agent log with atomic claim-at-end pattern."""
        if not msg_id:
            raise ValueError("msg_id is required for write_agent_log")

        async with self.transaction() as session:
            try:
                # Strict V3 schema validation
                self._validate_schema_v3(data, "AgentLog")
                self.validate_payload(data, ["level", "message"])  # agent_id is optional

                # Log the operation
                self._log_write_operation("write_agent_log", "AgentLog", msg_id)

                # Handle timestamp with explicit fallback logging
                timestamp_str = data.get(FieldName.TIMESTAMP)
                created_at = self.safe_parse_dt(timestamp_str)

                if created_at is None:
                    log_structured(
                        "warning",
                        "timestamp fallback used",
                        stream=stream,
                        msg_id=msg_id,
                        provided_timestamp=timestamp_str,
                        fallback_reason="missing_or_invalid",
                    )
                    created_at = datetime.now(timezone.utc)

                log_data = {
                    "agent_run_id": data.get(
                        FieldName.AGENT_ID
                    ),  # Map agent_id to agent_run_id (optional)
                    "log_level": data.get(FieldName.LOG_LEVEL, "INFO"),
                    "message": data[FieldName.MESSAGE],
                    "step_name": data.get(FieldName.STEP_NAME),
                    "step_data": data.get(FieldName.STEP_DATA, {}),
                    "trace_id": data.get(FieldName.TRACE_ID, msg_id),
                    "schema_version": data.get(FieldName.SCHEMA_VERSION, "v2"),
                    "source": data.get(FieldName.SOURCE, "unknown"),
                    "created_at": created_at,
                }

                # DO WORK FIRST
                await session.execute(insert(AgentLog).values(**log_data))

                # CLAIM LAST (same transaction) - ATOMIC GUARANTEE
                claim_result = await session.execute(
                    pg_insert(ProcessedEvent)
                    .values(msg_id=msg_id, stream=stream)
                    .on_conflict_do_nothing()
                    .returning(ProcessedEvent.msg_id)
                )

                if claim_result.scalar() is None:
                    raise ValueError(f"Message {msg_id} was already processed in this transaction")

                log_structured(
                    "debug",
                    "agent log write success",
                    msg_id=msg_id,
                    stream=stream,
                    agent_run=data[FieldName.AGENT_ID],
                )
                return True

            except Exception:
                log_structured(
                    "error",
                    "agent log write error",
                    msg_id=msg_id,
                    stream=stream,
                    exc_info=True,
                )
                raise

    async def write_system_metric(
        self,
        msg_id: str,
        metric_name: str,
        metric_value: float,
        metric_unit: str | None,
        tags: dict,
        schema_version: str,
        source: str,
        timestamp: datetime,
    ) -> bool:
        """Write system metric with idempotent msg_id as primary identifier."""
        # Validate msg_id is a proper UUID string
        if not isinstance(msg_id, str):
            raise ValueError("msg_id must be string UUID")
        if not msg_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"Invalid msg_id format: {msg_id}")

        async with self.transaction() as session:
            try:
                # Validate required parameters
                if not msg_id:
                    raise ValueError("msg_id is required for idempotent writes")

                if not metric_name:
                    raise ValueError("metric_name is required")

                if metric_value is None:
                    metric_value = 0.0  # Fallback to prevent NOT NULL violations

                # Log operation with actual msg_id
                log_structured(
                    "info",
                    "write audit",
                    operation="write_system_metric",
                    model="SystemMetrics",
                    id=msg_id,
                )

                # Use PostgreSQL UPSERT for idempotent writes
                stmt = pg_insert(SystemMetrics).values(
                    id=UUID(msg_id),  # Convert string to UUID for SQLAlchemy
                    metric_name=metric_name,
                    metric_value=metric_value,
                    metric_unit=metric_unit,
                    tags=tags,
                    schema_version=schema_version,
                    source=source,
                    timestamp=timestamp,
                )

                # Enforce idempotency - ignore duplicates
                stmt = stmt.on_conflict_do_nothing(index_elements=["id"])

                result = await session.execute(stmt)

                # Check if insert was successful (not a duplicate)
                if result.rowcount == 0:
                    log_structured(
                        "info",
                        "system metric duplicate",
                        msg_id=msg_id,
                        metric_name=metric_name,
                    )

                await session.flush()

                # CLAIM LAST with RETURNING
                if not await self._claim_message(session, msg_id, "system_metrics"):
                    raise ValueError(f"Message {msg_id} was already processed in this transaction")

                log_structured(
                    "info",
                    "system metric write success",
                    msg_id=msg_id,
                    metric=metric_name,
                )
                return True

            except Exception:
                log_structured("error", "system metric write error", msg_id=msg_id, exc_info=True)
                raise

    async def write_trade_performance(self, msg_id: str, stream: str, data: dict[str, Any]) -> bool:
        """Write trade performance with validation."""
        if not msg_id:
            raise ValueError("msg_id is required for write_trade_performance")

        async with self.transaction() as session:
            try:
                # Strict V3 schema validation
                self._validate_schema_v3(data, "TradePerformance")
                self.validate_payload(
                    data,
                    ["strategy_id", "symbol", "trade_id", "entry_price", "quantity"],
                )

                # Log the operation
                self._log_write_operation("write_trade_performance", "TradePerformance", msg_id)

                # Handle timestamps with explicit fallback logging
                entry_time_str = data[FieldName.ENTRY_TIME]
                entry_time = self.safe_parse_dt(entry_time_str)

                if entry_time is None:
                    log_structured(
                        "warning",
                        "timestamp fallback used",
                        stream=stream,
                        msg_id=msg_id,
                        provided_timestamp=entry_time_str,
                        fallback_reason="missing_or_invalid_entry_time",
                    )
                    entry_time = datetime.now(timezone.utc)

                perf_data = {
                    "strategy_id": data[FieldName.STRATEGY_ID],
                    "agent_id": data.get(FieldName.AGENT_ID),
                    "symbol": data[FieldName.SYMBOL],
                    "trade_id": data[FieldName.TRADE_ID],
                    "entry_time": entry_time,
                    "exit_time": self.safe_parse_dt(data.get(FieldName.EXIT_TIME)),
                    "entry_price": data[FieldName.ENTRY_PRICE],
                    "exit_price": data.get(FieldName.EXIT_PRICE),
                    "quantity": data[FieldName.QUANTITY],
                    "pnl": data.get(FieldName.PNL),
                    "pnl_percent": data.get(FieldName.PNL_PERCENT),
                    "holding_period_minutes": data.get(FieldName.HOLDING_PERIOD_MINUTES),
                    "max_drawdown": data.get(FieldName.MAX_DRAWDOWN),
                    "max_runup": data.get(FieldName.MAX_RUNUP),
                    "sharpe_ratio": data.get(FieldName.SHARPE_RATIO),
                    "trade_type": data.get(FieldName.TRADE_TYPE, PositionSide.LONG),
                    "exit_reason": data.get(FieldName.EXIT_REASON),
                    "regime": data.get(FieldName.REGIME),
                    "hour_utc": data.get(FieldName.HOUR_UTC),
                    "performance_metrics": data.get(FieldName.PERFORMANCE_METRICS, {}),
                }

                await session.execute(insert(TradePerformance).values(**perf_data))
                await session.flush()

                # CLAIM LAST with RETURNING
                if not await self._claim_message(session, msg_id, stream):
                    raise ValueError(f"Message {msg_id} was already processed in this transaction")

                log_structured(
                    "info",
                    "trade performance write success",
                    msg_id=msg_id,
                    trade_id=data[FieldName.TRADE_ID],
                )
                return True

            except Exception:
                log_structured(
                    "error",
                    "trade performance write error",
                    msg_id=msg_id,
                    exc_info=True,
                )
                raise

    async def write_vector_memory(self, msg_id: str, stream: str, data: dict[str, Any]) -> bool:
        """Write vector memory with embedding validation."""
        if not msg_id:
            raise ValueError("msg_id is required for write_vector_memory")

        async with self.transaction() as session:
            try:
                # Strict V3 schema validation
                self._validate_schema_v3(data, "VectorMemory")
                self.validate_payload(data, ["content", "content_type", "embedding"])

                # Validate embedding size and type
                embedding = data[FieldName.EMBEDDING]
                if not isinstance(embedding, list) or len(embedding) != 1536:
                    raise ValueError("embedding must be 1536-length list")

                if not all(isinstance(x, (int, float)) for x in embedding):
                    raise ValueError("embedding must be numeric")

                # Log the operation
                self._log_write_operation("write_vector_memory", "VectorMemory", msg_id)

                vector_data = {
                    "content": data[FieldName.CONTENT],
                    "content_type": data[FieldName.CONTENT_TYPE],
                    "embedding": data[FieldName.EMBEDDING],  # Validated to be 1536 floats
                    "vector_metadata": data.get(
                        FieldName.METADATA, {}
                    ),  # Map metadata to vector_metadata
                    "agent_id": data.get(FieldName.AGENT_ID),
                    "strategy_id": data.get(FieldName.STRATEGY_ID),
                    "schema_version": data.get(FieldName.SCHEMA_VERSION, "v2"),
                    "source": data.get(FieldName.SOURCE, "unknown"),
                }

                await session.execute(insert(VectorMemory).values(**vector_data))
                await session.flush()

                # CLAIM LAST with RETURNING
                if not await self._claim_message(session, msg_id, stream):
                    raise ValueError(f"Message {msg_id} was already processed in this transaction")

                log_structured(
                    "info",
                    "vector memory write success",
                    msg_id=msg_id,
                    content_type=data[FieldName.CONTENT_TYPE],
                )
                return True

            except Exception:
                log_structured("error", "vector memory write error", msg_id=msg_id, exc_info=True)
                raise

    async def write_risk_alert(self, msg_id: str, stream: str, data: dict[str, Any]) -> bool:
        """Write risk alert as event."""
        if not msg_id:
            raise ValueError("msg_id is required for write_risk_alert")

        async with self.transaction() as session:
            try:
                event_data = {
                    "event_type": "risk.alert",
                    "entity_type": data.get(FieldName.ENTITY_TYPE, "system"),
                    "entity_id": data.get(FieldName.ENTITY_ID),
                    "data": data,
                }

                await session.execute(insert(Event).values(**event_data))
                await session.flush()

                # CLAIM LAST with RETURNING
                if not await self._claim_message(session, msg_id, stream):
                    raise ValueError(f"Message {msg_id} was already processed in this transaction")

                log_structured(
                    "info",
                    "risk alert write success",
                    msg_id=msg_id,
                    alert_type=data.get(FieldName.ALERT_TYPE),
                )
                return True

            except Exception:
                log_structured("error", "risk alert write error", msg_id=msg_id, exc_info=True)
                raise

    async def write_agent_grade(self, msg_id: str, stream: str, data: dict[str, Any]) -> bool:
        """Write agent grade with atomic claim-at-end pattern."""
        if not msg_id:
            raise ValueError("msg_id is required for write_agent_grade")

        async with self.transaction() as session:
            try:
                # Strict V3 schema validation
                self._validate_schema_v3(data, "AgentGrades")
                self.validate_payload(data, ["agent_id", "agent_run_id", "grade_type", "score"])

                # Log the operation
                self._log_write_operation("write_agent_grade", "AgentGrades", msg_id)

                grade_data = {
                    "agent_id": data[FieldName.AGENT_ID],
                    "agent_run_id": data[FieldName.AGENT_RUN_ID],
                    "grade_type": data[FieldName.GRADE_TYPE],
                    "score": data[FieldName.SCORE],
                    "metrics": data.get(FieldName.METRICS, {}),
                    "feedback": data.get(FieldName.FEEDBACK),
                    "schema_version": data.get(FieldName.SCHEMA_VERSION, DB_SCHEMA_VERSION),
                    "source": data.get(FieldName.SOURCE, "unknown"),
                }

                await session.execute(insert(AgentGrades).values(**grade_data))
                await session.flush()

                # CLAIM LAST with RETURNING
                if not await self._claim_message(session, msg_id, stream):
                    raise ValueError(f"Message {msg_id} was already processed in this transaction")

                log_structured(
                    "info",
                    "agent grade write success",
                    msg_id=msg_id,
                    agent_id=data[FieldName.AGENT_ID],
                    grade_type=data[FieldName.GRADE_TYPE],
                )
                return True

            except Exception:
                log_structured("error", "agent grade write error", msg_id=msg_id, exc_info=True)
                raise

    async def write_ic_weight(self, msg_id: str, stream: str, data: dict[str, Any]) -> bool:
        """Write IC weight with atomic claim-at-end pattern."""
        if not msg_id:
            raise ValueError("msg_id is required for write_ic_weight")

        async with self.transaction() as session:
            try:
                # Strict V3 schema validation
                self._validate_schema_v3(data, "ICWeight")
                self.validate_payload(data, ["factor_name", "ic_value", "weight"])

                # Log the operation
                self._log_write_operation("write_ic_weight", "ICWeight", msg_id)

                # Insert as event for now (can be extended to dedicated table later)
                event_data = {
                    "event_type": "ic.weight_updated",
                    "entity_type": "factor",
                    "entity_id": data.get(FieldName.FACTOR_ID),
                    "data": data,
                }

                await session.execute(insert(Event).values(**event_data))
                await session.flush()

                # CLAIM LAST with RETURNING
                if not await self._claim_message(session, msg_id, stream):
                    raise ValueError(f"Message {msg_id} was already processed in this transaction")

                log_structured(
                    "info",
                    "ic weight write success",
                    msg_id=msg_id,
                    factor_name=data.get(FieldName.FACTOR_NAME),
                )
                return True

            except Exception:
                log_structured("error", "ic weight write error", msg_id=msg_id, exc_info=True)
                raise

    async def write_reflection_output(self, msg_id: str, stream: str, data: dict[str, Any]) -> bool:
        """Write reflection output with atomic claim-at-end pattern."""
        if not msg_id:
            raise ValueError("msg_id is required for write_reflection_output")

        async with self.transaction() as session:
            try:
                # Strict V3 schema validation
                self._validate_schema_v3(data, "ReflectionOutput")
                self.validate_payload(data, ["agent_id", "reflection_type", "insights"])

                # Log the operation
                self._log_write_operation("write_reflection_output", "ReflectionOutput", msg_id)

                # Insert as vector memory for semantic search
                vector_data = {
                    "content": data.get(FieldName.INSIGHTS, ""),
                    "content_type": "reflection",
                    "embedding": data.get(
                        FieldName.EMBEDDING, [0.0] * 1536
                    ),  # Placeholder embedding
                    "vector_metadata": {
                        "reflection_type": data.get(FieldName.REFLECTION_TYPE),
                        "agent_id": data.get(FieldName.AGENT_ID),
                        "trace_id": data.get(FieldName.TRACE_ID),
                        "schema_version": data.get(FieldName.SCHEMA_VERSION, DB_SCHEMA_VERSION),
                        "source": data.get(FieldName.SOURCE, SOURCE_REFLECTION),
                    },
                    "agent_id": data.get(FieldName.AGENT_ID),
                    "strategy_id": data.get(FieldName.STRATEGY_ID),
                    "schema_version": data.get(FieldName.SCHEMA_VERSION, DB_SCHEMA_VERSION),
                    "source": data.get(FieldName.SOURCE, SOURCE_REFLECTION),
                }

                await session.execute(insert(VectorMemory).values(**vector_data))
                await session.flush()

                # CLAIM LAST with RETURNING
                if not await self._claim_message(session, msg_id, stream):
                    raise ValueError(f"Message {msg_id} was already processed in this transaction")

                log_structured(
                    "info",
                    "reflection output write success",
                    msg_id=msg_id,
                    agent_id=data.get(FieldName.AGENT_ID),
                )
                return True

            except Exception:
                log_structured(
                    "error",
                    "reflection output write error",
                    msg_id=msg_id,
                    exc_info=True,
                )
                raise

    async def write_strategy_proposal(self, msg_id: str, stream: str, data: dict[str, Any]) -> bool:
        """Write strategy proposal with atomic claim-at-end pattern."""
        if not msg_id:
            raise ValueError("msg_id is required for write_strategy_proposal")

        async with self.transaction() as session:
            try:
                # Strict V3 schema validation
                self._validate_schema_v3(data, "StrategyProposal")
                self.validate_payload(data, ["proposal_type", "content"])

                # Log the operation
                self._log_write_operation("write_strategy_proposal", "StrategyProposal", msg_id)

                # Insert as event for now (can be extended to dedicated table later)
                event_data = {
                    "event_type": "strategy.proposed",
                    "entity_type": "strategy",
                    "entity_id": data.get(FieldName.STRATEGY_ID),
                    "data": data,
                }

                await session.execute(insert(Event).values(**event_data))
                await session.flush()

                # CLAIM LAST with RETURNING
                if not await self._claim_message(session, msg_id, stream):
                    raise ValueError(f"Message {msg_id} was already processed in this transaction")

                log_structured(
                    "info",
                    "strategy proposal write success",
                    msg_id=msg_id,
                    proposal_type=data.get(FieldName.PROPOSAL_TYPE),
                )
                return True

            except Exception:
                log_structured(
                    "error",
                    "strategy proposal write error",
                    msg_id=msg_id,
                    exc_info=True,
                )
                raise

    async def write_notification(self, msg_id: str, stream: str, data: dict[str, Any]) -> bool:
        """Write notification with atomic claim-at-end pattern."""
        if not msg_id:
            raise ValueError("msg_id is required for write_notification")

        async with self.transaction() as session:
            try:
                # Strict V3 schema validation
                self._validate_schema_v3(data, "Notification")
                self.validate_payload(data, ["notification_type", "message"])

                # Log the operation
                self._log_write_operation("write_notification", "Notification", msg_id)

                # Insert as event for now (can be extended to dedicated table later)
                event_data = {
                    "event_type": "notification.created",
                    "entity_type": "notification",
                    "entity_id": data.get(FieldName.NOTIFICATION_ID)
                    or data.get(FieldName.TRACE_ID)
                    or msg_id,
                    "data": data,
                }

                await session.execute(insert(Event).values(**event_data))
                await session.flush()

                # CLAIM LAST with RETURNING
                if not await self._claim_message(session, msg_id, stream):
                    raise ValueError(f"Message {msg_id} was already processed in this transaction")

                log_structured(
                    "info",
                    "notification write success",
                    msg_id=msg_id,
                    notification_type=data.get(FieldName.NOTIFICATION_TYPE),
                )
                return True

            except Exception:
                log_structured("error", "notification write error", msg_id=msg_id, exc_info=True)
                raise
