"""
Replay and recovery system for deterministic rebuild.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

REPLAY SYSTEM:
- Event replay from Redis stream
- Deterministic rebuild from ledger
- Recovery from partial failures
- State reconstruction capabilities
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.core.models.trade_ledger import TradeLedger
from api.observability import log_structured


class ReplayMode(Enum):
    REDIS_STREAM = "redis_stream"
    LEDGER_REBUILD = "ledger_rebuild"
    INCREMENTAL_REPLAY = "incremental_replay"


class ReplayCheckpoint(BaseModel):
    """Replay checkpoint for recovery."""
    checkpoint_id: str = Field(..., description="Checkpoint identifier")
    mode: ReplayMode = Field(..., description="Replay mode")
    timestamp: datetime = Field(..., description="Checkpoint timestamp")
    last_processed_id: str | None = Field(None, description="Last processed signal ID")
    total_processed: int = Field(..., description="Total signals processed")
    system_state: dict[str, Any] = Field(default_factory=dict, description="System state snapshot")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Checkpoint creation time")

    @property
    def is_redis_stream_checkpoint(self) -> bool:
        return self.mode == ReplayMode.REDIS_STREAM

    @property
    def is_ledger_rebuild_checkpoint(self) -> bool:
        return self.mode == ReplayMode.LEDGER_REBUILD


class ReplayManager:
    """Manages replay and recovery operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._checkpoints: dict[str, ReplayCheckpoint] = {}

    async def create_checkpoint(
        self,
        mode: ReplayMode,
        last_processed_id: str | None = None,
        total_processed: int = 0,
        system_state: dict[str, Any] | None = None,
    ) -> ReplayCheckpoint:
        """Create replay checkpoint."""
        checkpoint = ReplayCheckpoint(
            checkpoint_id=str(uuid.uuid4()),
            mode=mode,
            timestamp=datetime.now(timezone.utc),
            last_processed_id=last_processed_id,
            total_processed=total_processed,
            system_state=system_state or {},
        )

        self._checkpoints[checkpoint.checkpoint_id] = checkpoint

        log_structured(
            "info",
            "replay_checkpoint_created",
            checkpoint_id=checkpoint.checkpoint_id,
            mode=mode.value,
            total_processed=total_processed,
        )

        return checkpoint

    async def replay_from_redis_stream(
        self,
        stream_name: str,
        consumer_group: str,
        checkpoint_id: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Replay events from Redis stream."""
        try:
            # Get checkpoint if provided
            checkpoint = None
            if checkpoint_id and checkpoint_id in self._checkpoints:
                checkpoint = self._checkpoints[checkpoint_id]

            # Connect to Redis
            redis = await self._get_redis_connection()

            # Determine starting point
            start_id = checkpoint.last_processed_id if checkpoint else "0"

            # Read stream messages
            messages = await redis.xread(
                {stream_name: start_id},
                consumer=consumer_group,
                count=limit or 1000,
            )

            processed_events = []
            last_id = start_id

            for _stream, event_messages in messages:
                for event_id, fields in event_messages:
                    try:
                        # Process event
                        processed_event = await self._process_redis_event(fields)
                        processed_events.append(processed_event)
                        last_id = event_id

                    except Exception as e:
                        log_structured(
                            "error",
                            "replay_event_processing_error",
                            event_id=event_id,
                            error=str(e),
                            exc_info=True,
                        )

            # Create new checkpoint
            new_checkpoint = await self.create_checkpoint(
                mode=ReplayMode.REDIS_STREAM,
                last_processed_id=last_id,
                total_processed=len(processed_events),
                system_state={"last_stream_id": last_id},
            )

            return {
                "success": True,
                "mode": ReplayMode.REDIS_STREAM.value,
                "stream_name": stream_name,
                "consumer_group": consumer_group,
                "processed_events": len(processed_events),
                "last_event_id": last_id,
                "checkpoint_id": new_checkpoint.checkpoint_id,
                "replay_timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            log_structured(
                "error",
                "redis_stream_replay_failed",
                stream_name=stream_name,
                consumer_group=consumer_group,
                error=str(e),
                exc_info=True,
            )

            return {
                "success": False,
                "mode": ReplayMode.REDIS_STREAM.value,
                "error": str(e),
                "replay_timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def rebuild_from_ledger(
        self,
        agent_id: str | None = None,
        symbol: str | None = None,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        """Rebuild system state from trade ledger."""
        try:
            # Query ledger for rebuild
            stmt = select(TradeLedger).options(selectinload(TradeLedger.parent_trade))

            conditions = []
            if agent_id:
                conditions.append(TradeLedger.agent_id == agent_id)
            if symbol:
                conditions.append(TradeLedger.symbol == symbol)
            if from_timestamp:
                conditions.append(TradeLedger.created_at >= from_timestamp)
            if to_timestamp:
                conditions.append(TradeLedger.created_at <= to_timestamp)

            if conditions:
                stmt = stmt.where(and_(*conditions))

            stmt = stmt.order_by(TradeLedger.created_at)

            result = await self.session.execute(stmt)
            trades = result.scalars().all()

            # Rebuild state
            rebuilt_state = await self._rebuild_state_from_trades(trades)

            # Create checkpoint
            checkpoint = await self.create_checkpoint(
                mode=ReplayMode.LEDGER_REBUILD,
                total_processed=len(trades),
                system_state=rebuilt_state,
            )

            return {
                "success": True,
                "mode": ReplayMode.LEDGER_REBUILD.value,
                "trades_processed": len(trades),
                "rebuilt_state": rebuilt_state,
                "checkpoint_id": checkpoint.checkpoint_id,
                "rebuild_timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            log_structured(
                "error",
                "ledger_rebuild_failed",
                agent_id=agent_id,
                symbol=symbol,
                error=str(e),
                exc_info=True,
            )

            return {
                "success": False,
                "mode": ReplayMode.LEDGER_REBUILD.value,
                "error": str(e),
                "rebuild_timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def incremental_replay(
        self,
        from_checkpoint_id: str,
        new_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Incremental replay from checkpoint."""
        try:
            # Get checkpoint
            if from_checkpoint_id not in self._checkpoints:
                raise ValueError(f"Checkpoint not found: {from_checkpoint_id}")

            checkpoint = self._checkpoints[from_checkpoint_id]

            # Process new events
            processed_events = []
            for event_data in new_events:
                try:
                    processed_event = await self._process_redis_event(event_data)
                    processed_events.append(processed_event)
                except Exception as e:
                    log_structured(
                        "error",
                        "incremental_replay_event_error",
                        event_id=event_data.get("msg_id", "unknown"),
                        error=str(e),
                        exc_info=True,
                    )

            # Update checkpoint
            updated_checkpoint = await self.create_checkpoint(
                mode=ReplayMode.INCREMENTAL_REPLAY,
                last_processed_id=checkpoint.last_processed_id,
                total_processed=checkpoint.total_processed + len(processed_events),
                system_state=checkpoint.system_state,
            )

            return {
                "success": True,
                "mode": ReplayMode.INCREMENTAL_REPLAY.value,
                "from_checkpoint_id": from_checkpoint_id,
                "new_events_processed": len(processed_events),
                "total_processed": checkpoint.total_processed + len(processed_events),
                "new_checkpoint_id": updated_checkpoint.checkpoint_id,
                "replay_timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            log_structured(
                "error",
                "incremental_replay_failed",
                from_checkpoint_id=from_checkpoint_id,
                error=str(e),
                exc_info=True,
            )

            return {
                "success": False,
                "mode": ReplayMode.INCREMENTAL_REPLAY.value,
                "error": str(e),
                "replay_timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def _process_redis_event(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """Process single Redis event."""
        try:
            # Extract event type and payload
            event_type = event_data.get("type", "unknown")
            payload = event_data.get("payload", {})
            msg_id = event_data.get("msg_id", "")

            # Process based on event type
            if event_type == "TRADE_SIGNAL":
                return await self._process_trade_signal(payload, msg_id)
            if event_type == "MARKET_EVENT":
                return await self._process_market_event(payload, msg_id)
            return {
                "event_type": event_type,
                "msg_id": msg_id,
                "status": "skipped",
                "reason": "Unsupported event type",
            }

        except Exception as e:
            return {
                "event_type": event_data.get("type", "unknown"),
                "msg_id": event_data.get("msg_id", ""),
                "status": "error",
                "error": str(e),
            }

    async def _process_trade_signal(self, payload: dict[str, Any], msg_id: str) -> dict[str, Any]:
        """Process trade signal event."""
        # Extract signal data
        signal_id = payload.get("signal_id", "")
        agent_id = payload.get("agent_id", "")
        symbol = payload.get("symbol", "")
        action = payload.get("action", "")
        price = payload.get("price", 0)
        quantity = payload.get("quantity", 0)

        return {
            "event_type": "TRADE_SIGNAL",
            "msg_id": msg_id,
            "signal_id": signal_id,
            "agent_id": agent_id,
            "symbol": symbol,
            "action": action,
            "price": price,
            "quantity": quantity,
            "status": "processed",
        }

    async def _process_market_event(self, payload: dict[str, Any], msg_id: str) -> dict[str, Any]:
        """Process market event."""
        # Extract market data
        symbol = payload.get("symbol", "")
        price = payload.get("price", 0)
        volume = payload.get("volume", 0)

        return {
            "event_type": "MARKET_EVENT",
            "msg_id": msg_id,
            "symbol": symbol,
            "price": price,
            "volume": volume,
            "status": "processed",
        }

    async def _rebuild_state_from_trades(self, trades: list[TradeLedger]) -> dict[str, Any]:
        """Rebuild system state from trades."""
        # Calculate portfolio state
        open_positions = {}
        closed_trades = []
        total_pnl = Decimal("0")

        for trade in trades:
            if trade.status == "OPEN":
                if trade.symbol not in open_positions:
                    open_positions[trade.symbol] = []
                open_positions[trade.symbol].append({
                    "trade_id": str(trade.trade_id),
                    "agent_id": trade.agent_id,
                    "quantity": float(trade.quantity),
                    "entry_price": float(trade.entry_price),
                    "opened_at": trade.created_at.isoformat(),
                })
            elif trade.status == "CLOSED" and trade.pnl_realized:
                closed_trades.append({
                    "trade_id": str(trade.trade_id),
                    "symbol": trade.symbol,
                    "agent_id": trade.agent_id,
                    "pnl": float(trade.pnl_realized),
                    "closed_at": trade.created_at.isoformat(),
                })
                total_pnl += trade.pnl_realized

        return {
            "open_positions": open_positions,
            "closed_trades": closed_trades,
            "total_pnl": float(total_pnl),
            "total_trades": len(trades),
            "rebuilt_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _get_redis_connection(self):
        """Get Redis connection."""
        # Mock implementation - would use actual Redis client
        class MockRedis:
            async def xread(self, streams, consumer=None, count=None):
                return []

        return MockRedis()

    async def get_checkpoint(self, checkpoint_id: str) -> ReplayCheckpoint | None:
        """Get checkpoint by ID."""
        return self._checkpoints.get(checkpoint_id)

    async def list_checkpoints(self, mode: ReplayMode | None = None) -> list[ReplayCheckpoint]:
        """List all checkpoints."""
        checkpoints = list(self._checkpoints.values())

        if mode:
            checkpoints = [cp for cp in checkpoints if cp.mode == mode]

        return sorted(checkpoints, key=lambda x: x.timestamp, reverse=True)

    async def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete checkpoint."""
        if checkpoint_id in self._checkpoints:
            del self._checkpoints[checkpoint_id]

            log_structured(
                "info",
                "replay_checkpoint_deleted",
                checkpoint_id=checkpoint_id,
            )

            return True

        return False
