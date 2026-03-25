"""
Database Guard - Claim-First Pattern with atomic processing.

Exactly-once semantics through processed_events claim mechanism.
PostgreSQL upserts for safe concurrent writes.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert, update, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..models import (
    Event, Order, Position, AgentLog, SystemMetrics, TradePerformance,
    VectorMemory, ProcessedEvent
)

logger = logging.getLogger(__name__)


class SafeWriter:
    """Atomic database writer with claim-first pattern and validation."""
    
    def __init__(self, session_factory):
        self.session_factory = session_factory
    
    def _validate_schema_v2(self, data: Dict[str, Any], model_name: str) -> None:
        """Strict V2 schema validation - centralized enforcement."""
        # All models must have schema_version
        if 'schema_version' not in data:
            raise ValueError(
                f"{model_name}: Missing required field 'schema_version'"
            )
        
        if data['schema_version'] != 'v2':
            raise ValueError(
                f"{model_name}: Invalid schema version '{data['schema_version']}'. Expected 'v2'"
            )
        
        # Source field validation for models that have it
        if model_name in [
            'Order', 'Event', 'VectorMemory', 'AgentLog', 
            'SystemMetrics', 'TradePerformance'
        ]:
            if 'source' not in data or not data['source']:
                raise ValueError(
                    f"{model_name}: Source field is required and cannot be empty"
                )
    
    def _log_write_operation(self, operation: str, model_name: str, data: Dict[str, Any]) -> None:
        """Log write operations with proper context."""
        entity_id = data.get('id') or data.get('msg_id') or 'unknown'
        logger.info(
            f"[WRITE_AUDIT] operation={operation} "
            f"model={model_name} id={entity_id}"
        )

    @asynccontextmanager
    async def transaction(self):
        """Atomic transaction context manager."""
        async with self.session_factory() as session:
            async with session.begin():
                yield session

    def validate_payload(
        self, data: Dict[str, Any], required_fields: List[str], operation: str = ""
    ) -> None:
        """Validate required fields exist and have correct types."""
        for field in required_fields:
            if field not in data or data[field] is None:
                raise ValueError(f"Missing required field: {field}")
        
        # Validate idempotency_key for financial operations
        financial_operations = ['write_order', 'write_execution', 'write_trade_performance']
        if operation in financial_operations:
            if 'idempotency_key' not in data or not data['idempotency_key']:
                raise ValueError(f"idempotency_key is required for {operation}")

    def safe_parse_dt(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Safely parse ISO datetime strings."""
        if not dt_str:
            return None
        
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError) as e:
            logger.warning(f"Failed to parse datetime '{dt_str}': {e}")
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
            logger.debug(f"Message {msg_id} already claimed")
            return False

    async def write_order(self, msg_id: str, stream: str, data: Dict[str, Any]) -> bool:
        """Write order with atomic claim-at-end pattern."""
        async with self.transaction() as session:
            try:
                # Strict V2 schema validation
                self._validate_schema_v2(data, 'Order')
                self.validate_payload(
                    data, ['strategy_id', 'symbol', 'side', 'order_type', 'quantity'], 'write_order'
                )

                # Require idempotency_key (fix NULL dedup issue)
                idempotency_key = data.get('idempotency_key')
                if not idempotency_key:
                    raise ValueError("idempotency_key is required for order deduplication")

                # Log the operation
                self._log_write_operation('write_order', 'Order', data)

                # STEP 1: Insert Order FIRST (business logic)
                order = Order(
                    strategy_id=data['strategy_id'],
                    external_order_id=data.get('external_order_id'),
                    idempotency_key=idempotency_key,
                    symbol=data['symbol'],
                    side=data['side'],
                    order_type=data['order_type'],
                    quantity=data['quantity'],
                    price=data.get('price'),
                    exchange=data.get('exchange'),
                    order_metadata=data.get('metadata', {})
                )
                
                # Handle upsert with race condition protection
                try:
                    session.add(order)
                    await session.flush()  # Try to insert
                    order_id = order.id  # 🔥 CRITICAL: Get actual ID after flush
                except IntegrityError:
                    # 🔥 CRITICAL: Verify it's the same idempotency_key, not hiding bugs
                    from sqlalchemy import select
                    existing = await session.execute(
                        select(Order).where(Order.idempotency_key == idempotency_key)
                    )
                    if not existing.scalar():
                        raise ValueError(
                            f"IntegrityError but no existing order found "
                            f"for idempotency_key={idempotency_key}"
                        )
                    
                    # Get the existing order's ID
                    existing_order = existing.scalar_one()
                    order_id = existing_order.id
                    logger.info(
                        "write_order_duplicate",
                        extra={"msg_id": msg_id, "idempotency_key": idempotency_key}
                    )

                # STEP 2: Insert Event (audit trail)
                event = Event(
                    event_type='order.created',
                    entity_type='order',
                    entity_id=order_id,  # 🔥 CRITICAL: Use actual order ID
                    idempotency_key=msg_id,  # Use msg_id for Event dedup
                    data=data
                )
                session.add(event)
                await session.flush()  # Ensure event persists

                # STEP 3: CLAIM LAST (atomic guarantee)
                claim = ProcessedEvent(msg_id=msg_id, stream=stream)
                session.add(claim)
                await session.flush()  # Final flush before commit
                
                logger.info(f"[WRITE_ORDER] msg={msg_id} stream={stream} symbol={data['symbol']}")
                return True
                
            except Exception as e:
                logger.error(f"[WRITE_ERROR] msg={msg_id} stream={stream} err={e}")
                raise

    async def write_execution(self, msg_id: str, stream: str, data: Dict[str, Any]) -> bool:
        """Write execution with atomic claim-at-end and order existence check."""
        async with self.transaction() as session:
            try:
                # Strict V2 schema validation
                self._validate_schema_v2(data, 'Event')
                self.validate_payload(data, ['strategy_id', 'symbol', 'order_id'])

                # Log the operation
                self._log_write_operation('write_execution', 'Event', data)

                # Insert event
                await session.execute(
                    insert(Event).values(
                        event_type='order.filled',
                        entity_type='order',
                        entity_id=data['order_id'],
                        data=data
                    )
                )

                # Update order with existence check (fix silent failure)
                result = await session.execute(
                    update(Order)
                    .where(Order.id == data['order_id'])
                    .values(
                        filled_quantity=data.get('filled_quantity'),
                        filled_price=data.get('filled_price'),
                        status='filled',
                        commission=data.get('commission', 0)
                    )
                )

                if result.rowcount == 0:
                    raise ValueError(f"Order {data['order_id']} not found for execution")

                # Upsert position with on_conflict_do_update
                position_stmt = pg_insert(Position).values(
                    strategy_id=data['strategy_id'],
                    symbol=data['symbol'],
                    quantity=data.get('new_quantity'),
                    avg_cost=data.get('new_avg_cost'),
                    market_value=data.get('market_value'),
                    unrealized_pnl=data.get('unrealized_pnl', 0),
                    last_price=data.get('filled_price'),
                    metadata=data.get('metadata', {})
                ).on_conflict_do_update(
                    index_elements=['strategy_id', 'symbol'],
                    set_=dict(
                        quantity=data.get('new_quantity'),
                        avg_cost=data.get('new_avg_cost'),
                        market_value=data.get('market_value'),
                        unrealized_pnl=data.get('unrealized_pnl', 0),
                        last_price=data.get('filled_price'),
                        updated_at=func.now()
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
                    raise ValueError(
                        f"Message {msg_id} was already processed in this transaction"
                    )
                
                logger.info(
                    f"[WRITE_SUCCESS] msg={msg_id} stream={stream} order_id={data['order_id']}"
                )
                return True

            except Exception as e:
                logger.error(f"[WRITE_ERROR] msg={msg_id} stream={stream} err={e}")
                raise

    async def write_agent_log(self, msg_id: str, stream: str, data: Dict[str, Any]) -> bool:
        """Write agent log with atomic claim-at-end pattern."""
        async with self.transaction() as session:
            try:
                # Strict V2 schema validation
                self._validate_schema_v2(data, 'AgentLog')
                self.validate_payload(data, ['agent_id', 'level', 'message'])

                # Log the operation
                self._log_write_operation('write_agent_log', 'AgentLog', data)

                # Handle timestamp with explicit fallback logging
                timestamp_str = data.get('timestamp')
                created_at = self.safe_parse_dt(timestamp_str)
                
                if created_at is None:
                    logger.warning(
                        "timestamp_fallback_used",
                        extra={
                            "stream": stream,
                            "msg_id": msg_id,
                            "provided_timestamp": timestamp_str,
                            "fallback_reason": "missing_or_invalid"
                        }
                    )
                    created_at = datetime.now(timezone.utc)

                log_data = {
                    'agent_run_id': data['agent_id'],  # Map agent_id to agent_run_id
                    'log_level': data.get('log_level', 'INFO'),
                    'message': data['message'],
                    'step_name': data.get('step_name'),
                    'step_data': data.get('step_data', {}),
                    'trace_id': data.get('trace_id', msg_id),
                    'schema_version': data.get('schema_version', 'v2'),
                    'source': data.get('source', 'unknown'),
                    'created_at': created_at
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
                    raise ValueError(
                        f"Message {msg_id} was already processed in this transaction"
                    )
                
                logger.debug(
                    f"[WRITE_SUCCESS] msg={msg_id} stream={stream} agent_run={data['agent_run_id']}"
                )
                return True

            except Exception as e:
                logger.error(f"[WRITE_ERROR] msg={msg_id} stream={stream} err={e}")
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
        async with self.transaction() as session:
            try:
                # Validate required parameters
                if not msg_id:
                    raise ValueError("msg_id is required for idempotent writes")
                
                if not metric_name:
                    raise ValueError("metric_name is required")
                
                if metric_value is None:
                    raise ValueError("metric_value is required")
                
                # Log the operation with actual msg_id
                logger.info(
                    "[WRITE_AUDIT] operation=write_system_metric model=SystemMetrics id=%s",
                    msg_id,
                )

                # Use PostgreSQL UPSERT for idempotent writes
                stmt = pg_insert(SystemMetrics).values(
                    id=msg_id,  # ✅ critical fix: use msg_id as primary ID
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
                    logger.info(
                        "write_system_metric_duplicate",
                        extra={"msg_id": msg_id, "metric_name": metric_name}
                    )
                
                await session.flush()

                # CLAIM LAST with RETURNING
                if not await self._claim_message(session, msg_id, "system_metrics"):
                    raise ValueError(
                        f"Message {msg_id} was already processed in this transaction"
                    )
                
                logger.info(
                    "write_system_metric_success",
                    extra={"msg_id": msg_id, "metric": metric_name}
                )
                return True

            except Exception as e:
                logger.error("write_system_metric_error", extra={"msg_id": msg_id, "error": str(e)})
                raise

    async def write_trade_performance(self, msg_id: str, stream: str, data: Dict[str, Any]) -> bool:
        """Write trade performance with validation."""
        async with self.transaction() as session:
            try:
                # Strict V2 schema validation
                self._validate_schema_v2(data, 'TradePerformance')
                self.validate_payload(
                    data, ['strategy_id', 'symbol', 'trade_id', 'entry_price', 'quantity']
                )

                # Log the operation
                self._log_write_operation('write_trade_performance', 'TradePerformance', data)

                # Handle timestamps with explicit fallback logging
                entry_time_str = data['entry_time']
                entry_time = self.safe_parse_dt(entry_time_str)
                
                if entry_time is None:
                    logger.warning(
                        "timestamp_fallback_used",
                        extra={
                            "stream": stream,
                            "msg_id": msg_id,
                            "provided_timestamp": entry_time_str,
                            "fallback_reason": "missing_or_invalid_entry_time"
                        }
                    )
                    entry_time = datetime.now(timezone.utc)

                perf_data = {
                    'strategy_id': data['strategy_id'],
                    'agent_id': data.get('agent_id'),
                    'symbol': data['symbol'],
                    'trade_id': data['trade_id'],
                    'entry_time': entry_time,
                    'exit_time': self.safe_parse_dt(data.get('exit_time')),
                    'entry_price': data['entry_price'],
                    'exit_price': data.get('exit_price'),
                    'quantity': data['quantity'],
                    'pnl': data.get('pnl'),
                    'pnl_percent': data.get('pnl_percent'),
                    'holding_period_minutes': data.get('holding_period_minutes'),
                    'max_drawdown': data.get('max_drawdown'),
                    'max_runup': data.get('max_runup'),
                    'sharpe_ratio': data.get('sharpe_ratio'),
                    'trade_type': data.get('trade_type', 'long'),
                    'exit_reason': data.get('exit_reason'),
                    'regime': data.get('regime'),
                    'hour_utc': data.get('hour_utc'),
                    'performance_metrics': data.get('performance_metrics', {})
                }

                await session.execute(insert(TradePerformance).values(**perf_data))
                await session.flush()

                # CLAIM LAST with RETURNING
                if not await self._claim_message(session, msg_id, stream):
                    raise ValueError(
                        f"Message {msg_id} was already processed in this transaction"
                    )
                
                logger.info(
                    "write_trade_performance_success",
                    extra={"msg_id": msg_id, "trade_id": data['trade_id']}
                )
                return True

            except Exception as e:
                logger.error(
                    "write_trade_performance_error", extra={"msg_id": msg_id, "error": str(e)}
                )
                raise

    async def write_vector_memory(self, msg_id: str, stream: str, data: Dict[str, Any]) -> bool:
        """Write vector memory with embedding validation."""
        async with self.transaction() as session:
            try:
                # Strict V2 schema validation
                self._validate_schema_v2(data, 'VectorMemory')
                self.validate_payload(data, ['content', 'content_type', 'embedding'])

                # 🔥 CRITICAL: Validate embedding size and type
                embedding = data['embedding']
                if not isinstance(embedding, list) or len(embedding) != 1536:
                    raise ValueError("embedding must be 1536-length list")
                
                if not all(isinstance(x, (int, float)) for x in embedding):
                    raise ValueError("embedding must be numeric")

                # Log the operation
                self._log_write_operation('write_vector_memory', 'VectorMemory', data)

                vector_data = {
                    'content': data['content'],
                    'content_type': data['content_type'],
                    'embedding': data['embedding'],  # Validated to be 1536 floats
                    'vector_metadata': data.get('metadata', {}),  # Map metadata to vector_metadata
                    'agent_id': data.get('agent_id'),
                    'strategy_id': data.get('strategy_id'),
                    'schema_version': data.get('schema_version', 'v2'),
                    'source': data.get('source', 'unknown')
                }

                await session.execute(insert(VectorMemory).values(**vector_data))
                await session.flush()

                # CLAIM LAST with RETURNING
                if not await self._claim_message(session, msg_id, stream):
                    raise ValueError(
                        f"Message {msg_id} was already processed in this transaction"
                    )
                
                logger.info(
                    "write_vector_memory_success",
                    extra={"msg_id": msg_id, "content_type": data['content_type']}
                )
                return True

            except Exception as e:
                logger.error("write_vector_memory_error", extra={"msg_id": msg_id, "error": str(e)})
                raise

    async def write_risk_alert(self, msg_id: str, stream: str, data: Dict[str, Any]) -> bool:
        """Write risk alert as event."""
        async with self.transaction() as session:
            try:
                event_data = {
                    'event_type': 'risk.alert',
                    'entity_type': data.get('entity_type', 'system'),
                    'entity_id': data.get('entity_id'),
                    'data': data
                }

                await session.execute(insert(Event).values(**event_data))
                await session.flush()

                # CLAIM LAST with RETURNING
                if not await self._claim_message(session, msg_id, stream):
                    raise ValueError(
                        f"Message {msg_id} was already processed in this transaction"
                    )
                
                logger.info(
                    "write_risk_alert_success",
                    extra={"msg_id": msg_id, "alert_type": data.get('alert_type')}
                )
                return True

            except Exception as e:
                logger.error("write_risk_alert_error", extra={"msg_id": msg_id, "error": str(e)})
                raise
