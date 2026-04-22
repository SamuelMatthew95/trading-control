"""
Agent-level idempotency checking to prevent duplicate signal processing.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

IDEMPOTENCY:
- Double-layer protection (agent + pipeline)
- Memory-efficient tracking
- Automatic cleanup
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.observability import log_structured


class AgentIdempotencyTracker:
    """Tracks processed signal IDs at agent level."""

    def __init__(self, session: AsyncSession, max_tracked: int = 10000):
        self.session = session
        self.max_tracked = max_tracked
        self._cleanup_interval = timedelta(hours=1)
        self._last_cleanup = datetime.now(timezone.utc)

    async def is_signal_processed(self, agent_id: str, signal_id: str) -> bool:
        """Check if agent already processed this signal."""
        try:
            stmt = select(self._processed_signal_table).where(
                self._processed_signal_table.c.agent_id == agent_id,
                self._processed_signal_table.c.signal_id == signal_id,
            )

            result = await self.session.execute(stmt)
            return result.scalar_one_or_none() is not None

        except Exception as e:
            log_structured(
                "error",
                "agent_idempotency_check_error",
                agent_id=agent_id,
                signal_id=signal_id,
                error=str(e),
            )
            return False

    async def mark_signal_processed(self, agent_id: str, signal_id: str) -> None:
        """Mark signal as processed by this agent."""
        try:
            # Clean up old entries periodically
            await self._cleanup_old_entries()

            # Insert new processed signal record
            stmt = self._processed_signal_table.insert().values(
                agent_id=agent_id,
                signal_id=signal_id,
                processed_at=datetime.now(timezone.utc),
            )

            await self.session.execute(stmt)
            await self.session.flush()

            log_structured(
                "debug",
                "agent_signal_processed",
                agent_id=agent_id,
                signal_id=signal_id,
            )

        except Exception as e:
            log_structured(
                "error",
                "agent_idempotency_mark_error",
                agent_id=agent_id,
                signal_id=signal_id,
                error=str(e),
            )

    async def _cleanup_old_entries(self) -> None:
        """Clean up old processed signal entries."""
        if datetime.now(timezone.utc) - self._last_cleanup < self._cleanup_interval:
            return

        try:
            # Delete entries older than cleanup interval
            cutoff_time = datetime.now(timezone.utc) - self._cleanup_interval

            stmt = delete(self._processed_signal_table).where(
                self._processed_signal_table.c.processed_at < cutoff_time
            )

            result = await self.session.execute(stmt)
            deleted_count = result.rowcount

            self._last_cleanup = datetime.now(timezone.utc)

            if deleted_count > 0:
                log_structured(
                    "info",
                    "agent_idempotency_cleanup",
                    deleted_count=deleted_count,
                    cutoff_time=cutoff_time.isoformat(),
                )

        except Exception as e:
            log_structured(
                "error",
                "agent_idempotency_cleanup_error",
                error=str(e),
            )

    @property
    def _processed_signal_table(self):
        """Get the processed signal table model."""
        from sqlalchemy import Column, DateTime, String, Table

        return Table(
            'agent_processed_signals',
            self._metadata,
            Column('agent_id', String, primary_key=True),
            Column('signal_id', String, primary_key=True),
            Column('processed_at', DateTime, nullable=False),
        )

    @property
    def _metadata(self):
        """Get SQLAlchemy metadata."""
        from sqlalchemy import MetaData
        return MetaData()
