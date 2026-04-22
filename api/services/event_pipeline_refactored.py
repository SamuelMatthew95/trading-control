"""
Refactored EventPipeline - Production-grade with strict phases.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

PHASES:
1. Ingestion - Validate and normalize signals
2. Idempotency Gate - Prevent duplicate processing
3. Trade Execution - Core buy/sell logic
4. Persistence - Atomic DB writes
5. Broadcast - WebSocket notifications
6. Acknowledgement - Final step only
"""

from datetime import datetime, timezone
from typing import Any, Dict

from api.core.events import SignalEvent, TradeExecutionEvent
from api.core.stream_logic import MessageProcessor, BackpressureController
from api.database import AsyncSessionFactory
from api.events.bus import PIPELINE_GROUP, STREAMS, EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available, has_processed, mark_processed
from api.services.agent_state import AgentStateRegistry
from api.services.trade_signal_filter import get_trade_signal_filter
from api.services.trade_engine import TradeEngine


class RefactoredEventPipeline:
    """Production-grade event pipeline with strict phase separation."""
    
    def __init__(
        self,
        bus: EventBus,
        broadcaster: Any,
        dlq: DLQManager,
        *,
        consumer_name: str = "pipeline",
        max_retries: int = 3,
        agent_state: AgentStateRegistry | None = None,
    ):
        self.bus = bus
        self.broadcaster = broadcaster
        self.dlq = dlq
        self.consumer_name = consumer_name
        self.max_retries = max_retries
        self.agent_state = agent_state
        self._running = False
        self._task = None
        self._recent_events = []
        self._recent_failures = []
        self._last_error = None
        
        # Phase-specific components
        self.message_processor = MessageProcessor()
        self.backpressure = BackpressureController()
        self.trade_filter = get_trade_signal_filter()
        
        # Trade engine (injected per session)
        self._trade_engine = None
    
    async def start(self) -> None:
        """Start pipeline with proper resource management."""
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"pipeline:{self.consumer_name}")
        log_structured("info", "pipeline_started", consumer=self.consumer_name)
    
    async def stop(self) -> None:
        """Stop pipeline with graceful shutdown."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log_structured("info", "pipeline_stopped", consumer=self.consumer_name)
    
    async def _run(self) -> None:
        """Main pipeline loop with proper error handling."""
        while self._running:
            try:
                messages = await self.bus.read_messages(
                    STREAMS,
                    self.consumer_name,
                    PIPELINE_GROUP,
                    count=10,
                    block_ms=5000,
                )
                
                if messages:
                    await self._process_messages(messages)
                else:
                    await asyncio.sleep(0.05)  # Throttle
                    
            except Exception as e:
                log_structured("error", "pipeline_loop_error", error=str(e), exc_info=True)
                await asyncio.sleep(1.0)  # Backoff on error
    
    async def _process_messages(self, messages: list[tuple[str, str, Dict[str, Any]]]) -> None:
        """Process batch of messages with proper session management."""
        async with AsyncSessionFactory() as session:
            self._trade_engine = TradeEngine(session)
            
            for stream, redis_id, event in messages:
                await self._process_single_message(stream, redis_id, event, session)
            
            # Commit all changes atomically
            await session.commit()
    
    async def _process_single_message(
        self, 
        stream: str, 
        redis_id: str, 
        event: Dict[str, Any], 
        session
    ) -> None:
        """Process single message through all phases."""
        try:
            # PHASE 1: Ingestion
            signal_event = await self._ingest_signal(stream, redis_id, event)
            if not signal_event:
                return
            
            # PHASE 2: Idempotency Gate
            if await self._check_idempotency(signal_event.signal_id):
                await self._acknowledge_safely(stream, redis_id)
                return
            
            # PHASE 3: Trade Execution
            execution = await self._execute_trade(signal_event)
            
            # PHASE 4: Persistence
            await self._persist_execution(execution, session)
            
            # PHASE 5: Broadcast
            await self._broadcast_execution(execution)
            
            # PHASE 6: Acknowledgement
            await self._acknowledge_safely(stream, redis_id)
            
            # Mark as processed AFTER all phases complete
            mark_processed(signal_event.signal_id)
            
        except Exception as e:
            await self._handle_processing_error(stream, redis_id, event, e)
    
    async def _ingest_signal(self, stream: str, redis_id: str, event: Dict[str, Any]) -> SignalEvent | None:
        """PHASE 1: Validate and normalize signal."""
        # Apply server-side guard first
        filter_result = self.trade_filter.filter_event(event)
        if filter_result["action"] != "process":
            log_structured(
                "debug",
                "pipeline_signal_filtered",
                action=filter_result["action"],
                reason=filter_result["reason"],
                stream=stream,
                redis_id=redis_id,
            )
            return None
        
        # Create canonical signal event
        signal_event = SignalEvent.from_redis_event(event)
        
        log_structured(
            "info",
            "pipeline_signal_ingested",
            signal_id=signal_event.signal_id,
            action=signal_event.action.value,
            symbol=signal_event.symbol,
            stream=stream,
        )
        
        return signal_event
    
    async def _check_idempotency(self, signal_id: str) -> bool:
        """PHASE 2: Check if signal already processed."""
        if has_processed(signal_id):
            log_structured(
                "debug",
                "pipeline_duplicate_skipped",
                signal_id=signal_id,
            )
            return True
        return False
    
    async def _execute_trade(self, signal: SignalEvent) -> TradeExecutionEvent:
        """PHASE 3: Execute trade with engine."""
        log_structured(
            "info",
            "pipeline_trade_execution",
            signal_id=signal.signal_id,
            action=signal.action.value,
            symbol=signal.symbol,
        )
        
        return await self._trade_engine.process_signal(signal)
    
    async def _persist_execution(self, execution: TradeExecutionEvent, session) -> None:
        """PHASE 4: Persist execution to database."""
        # This is handled by TradeEngine during execution
        # Session will be committed by caller
        log_structured(
            "info",
            "pipeline_trade_persisted",
            signal_id=execution.signal_id,
            trade_id=execution.trade_id,
            status=execution.status,
        )
    
    async def _broadcast_execution(self, execution: TradeExecutionEvent) -> None:
        """PHASE 5: Broadcast to WebSocket."""
        outbound = {
            "type": "trade_execution",
            "signal_id": execution.signal_id,
            "trade_id": execution.trade_id,
            "agent_id": execution.agent_id,
            "symbol": execution.symbol,
            "action": execution.action.value,
            "price": float(execution.entry_price or execution.exit_price or 0),
            "quantity": float(execution.quantity),
            "status": execution.status,
            "pnl_realized": float(execution.pnl_realized or 0),
            "execution_mode": execution.execution_mode,
            "timestamp": execution.timestamp.isoformat(),
        }
        
        await self.broadcaster.broadcast(outbound)
        
        log_structured(
            "info",
            "pipeline_trade_broadcast",
            signal_id=execution.signal_id,
            trade_id=execution.trade_id,
        )
    
    async def _acknowledge_safely(self, stream: str, redis_id: str) -> None:
        """PHASE 6: Acknowledge Redis message."""
        try:
            await self.bus.acknowledge(stream, PIPELINE_GROUP, redis_id)
            log_structured("debug", "pipeline_message_acked", stream=stream, redis_id=redis_id)
        except Exception as e:
            log_structured("error", "pipeline_ack_failed", error=str(e), stream=stream, redis_id=redis_id)
    
    async def _handle_processing_error(
        self, 
        stream: str, 
        redis_id: str, 
        event: Dict[str, Any], 
        error: Exception
    ) -> None:
        """Handle processing errors with DLQ routing."""
        error_msg = str(error)
        
        log_structured(
            "error",
            "pipeline_processing_error",
            error=error_msg,
            stream=stream,
            redis_id=redis_id,
            exc_info=True,
        )
        
        # Send to DLQ
        await self.dlq.push(
            stream=stream,
            event_id=event.get("msg_id", redis_id),
            payload=event,
            error=error_msg,
            retries=0,
        )
        
        # Acknowledge to prevent reprocessing
        await self._acknowledge_safely(stream, redis_id)
