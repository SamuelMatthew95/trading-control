"""
DB-level idempotency guarantee.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

CONSTRAINTS:
- UNIQUE signal_id constraint prevents duplicate trades
- Single open position per symbol/agent
- Valid trade lifecycle enforcement
- Performance indexes for efficient queries
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.observability import log_structured


class DBConstraintsManager:
    """Manages database constraints for idempotency."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_constraints(self) -> dict[str, Any]:
        """Create all database constraints."""
        try:
            constraints_created = []

            # Constraint 1: UNIQUE signal_id
            signal_id_constraint = await self._create_unique_signal_id_constraint()
            constraints_created.append(signal_id_constraint)

            # Constraint 2: Single open position per symbol/agent
            position_constraint = await self._create_single_open_position_constraint()
            constraints_created.append(position_constraint)

            # Constraint 3: Valid trade lifecycle
            lifecycle_constraint = await self._create_lifecycle_constraint()
            constraints_created.append(lifecycle_constraint)

            # Constraint 4: Valid parent-child relationships
            relationship_constraint = await self._create_relationship_constraint()
            constraints_created.append(relationship_constraint)

            # Create performance indexes
            indexes = await self._create_performance_indexes()
            constraints_created.extend(indexes)

            log_structured(
                "info",
                "db_constraints_created",
                total_constraints=len(constraints_created),
                constraints=[c["name"] for c in constraints_created],
            )

            return {
                "success": True,
                "constraints_created": constraints_created,
                "total_created": len(constraints_created),
            }

        except Exception as e:
            log_structured(
                "error",
                "db_constraints_creation_failed",
                error=str(e),
                exc_info=True,
            )

            return {
                "success": False,
                "error": str(e),
                "constraints_created": [],
            }

    async def _create_unique_signal_id_constraint(self) -> dict[str, Any]:
        """Create UNIQUE constraint on signal_id."""
        constraint_sql = """
        ALTER TABLE trade_ledger
        ADD CONSTRAINT IF NOT EXISTS unique_signal_id
        UNIQUE (trace_id, agent_id);
        """

        try:
            await self.session.execute(text(constraint_sql))
            await self.session.commit()

            return {
                "name": "unique_signal_id",
                "type": "UNIQUE",
                "description": "Prevents duplicate signals per agent",
                "status": "created",
            }

        except Exception as e:
            await self.session.rollback()

            return {
                "name": "unique_signal_id",
                "type": "UNIQUE",
                "description": "Prevents duplicate signals per agent",
                "status": "failed",
                "error": str(e),
            }

    async def _create_single_open_position_constraint(self) -> dict[str, Any]:
        """Create constraint for single open position per symbol/agent."""
        constraint_sql = """
        CREATE UNIQUE INDEX IF NOT EXISTS single_open_position_idx
        ON trade_ledger (agent_id, symbol, status)
        WHERE status = 'OPEN';
        """

        try:
            await self.session.execute(text(constraint_sql))
            await self.session.commit()

            return {
                "name": "single_open_position_idx",
                "type": "UNIQUE INDEX",
                "description": "Single open position per symbol/agent",
                "status": "created",
            }

        except Exception as e:
            await self.session.rollback()

            return {
                "name": "single_open_position_idx",
                "type": "UNIQUE INDEX",
                "description": "Single open position per symbol/agent",
                "status": "failed",
                "error": str(e),
            }

    async def _create_lifecycle_constraint(self) -> dict[str, Any]:
        """Create constraint for valid trade lifecycle."""
        constraint_sql = """
        ALTER TABLE trade_ledger
        ADD CONSTRAINT IF NOT EXISTS valid_lifecycle
        CHECK (
            (trade_type = 'BUY' AND status IN ('OPEN', 'CLOSED')) OR
            (trade_type = 'SELL' AND status = 'CLOSED')
        );
        """

        try:
            await self.session.execute(text(constraint_sql))
            await self.session.commit()

            return {
                "name": "valid_lifecycle",
                "type": "CHECK",
                "description": "Valid trade lifecycle enforcement",
                "status": "created",
            }

        except Exception as e:
            await self.session.rollback()

            return {
                "name": "valid_lifecycle",
                "type": "CHECK",
                "description": "Valid trade lifecycle enforcement",
                "status": "failed",
                "error": str(e),
            }

    async def _create_relationship_constraint(self) -> dict[str, Any]:
        """Create constraint for valid parent-child relationships."""
        constraint_sql = """
        ALTER TABLE trade_ledger
        ADD CONSTRAINT IF NOT EXISTS valid_parent_child
        CHECK (
            (trade_type = 'BUY' AND parent_trade_id IS NULL) OR
            (trade_type = 'SELL' AND parent_trade_id IS NOT NULL)
        );
        """

        try:
            await self.session.execute(text(constraint_sql))
            await self.session.commit()

            return {
                "name": "valid_parent_child",
                "type": "CHECK",
                "description": "Valid parent-child relationships",
                "status": "created",
            }

        except Exception as e:
            await self.session.rollback()

            return {
                "name": "valid_parent_child",
                "type": "CHECK",
                "description": "Valid parent-child relationships",
                "status": "failed",
                "error": str(e),
            }

    async def _create_performance_indexes(self) -> list[dict[str, Any]]:
        """Create performance indexes."""
        indexes = []

        # Index 1: Agent performance
        agent_index_sql = """
        CREATE INDEX IF NOT EXISTS agent_performance_idx
        ON trade_ledger (agent_id, created_at DESC);
        """

        try:
            await self.session.execute(text(agent_index_sql))
            await self.session.commit()

            indexes.append(
                {
                    "name": "agent_performance_idx",
                    "type": "INDEX",
                    "description": "Agent performance queries",
                    "status": "created",
                }
            )

        except Exception as e:
            await self.session.rollback()

            indexes.append(
                {
                    "name": "agent_performance_idx",
                    "type": "INDEX",
                    "description": "Agent performance queries",
                    "status": "failed",
                    "error": str(e),
                }
            )

        # Index 2: Symbol queries
        symbol_index_sql = """
        CREATE INDEX IF NOT EXISTS symbol_queries_idx
        ON trade_ledger (symbol, status, created_at DESC);
        """

        try:
            await self.session.execute(text(symbol_index_sql))
            await self.session.commit()

            indexes.append(
                {
                    "name": "symbol_queries_idx",
                    "type": "INDEX",
                    "description": "Symbol-based queries",
                    "status": "created",
                }
            )

        except Exception as e:
            await self.session.rollback()

            indexes.append(
                {
                    "name": "symbol_queries_idx",
                    "type": "INDEX",
                    "description": "Symbol-based queries",
                    "status": "failed",
                    "error": str(e),
                }
            )

        # Index 3: Signal ID lookup
        signal_id_index_sql = """
        CREATE INDEX IF NOT EXISTS signal_id_lookup_idx
        ON trade_ledger (trace_id, agent_id);
        """

        try:
            await self.session.execute(text(signal_id_index_sql))
            await self.session.commit()

            indexes.append(
                {
                    "name": "signal_id_lookup_idx",
                    "type": "INDEX",
                    "description": "Signal ID lookup",
                    "status": "created",
                }
            )

        except Exception as e:
            await self.session.rollback()

            indexes.append(
                {
                    "name": "signal_id_lookup_idx",
                    "type": "INDEX",
                    "description": "Signal ID lookup",
                    "status": "failed",
                    "error": str(e),
                }
            )

        return indexes

    async def validate_constraints(self) -> dict[str, Any]:
        """Validate all constraints are active."""
        try:
            validation_results = []

            # Check 1: Unique signal_id constraint
            unique_check = await self._check_unique_signal_id_constraint()
            validation_results.append(unique_check)

            # Check 2: Single open position constraint
            position_check = await self._check_single_open_position_constraint()
            validation_results.append(position_check)

            # Check 3: Lifecycle constraint
            lifecycle_check = await self._check_lifecycle_constraint()
            validation_results.append(lifecycle_check)

            # Check 4: Relationship constraint
            relationship_check = await self._check_relationship_constraint()
            validation_results.append(relationship_check)

            # Check 5: Performance indexes
            index_check = await self._check_performance_indexes()
            validation_results.extend(index_check)

            active_constraints = [r for r in validation_results if r.get("status") == "active"]
            failed_constraints = [r for r in validation_results if r.get("status") == "failed"]

            log_structured(
                "info",
                "db_constraints_validated",
                total_constraints=len(validation_results),
                active=len(active_constraints),
                failed=len(failed_constraints),
            )

            return {
                "success": len(failed_constraints) == 0,
                "validation_results": validation_results,
                "active_constraints": len(active_constraints),
                "failed_constraints": len(failed_constraints),
            }

        except Exception as e:
            log_structured(
                "error",
                "db_constraints_validation_failed",
                error=str(e),
                exc_info=True,
            )

            return {
                "success": False,
                "error": str(e),
                "validation_results": [],
            }

    async def _check_unique_signal_id_constraint(self) -> dict[str, Any]:
        """Check unique signal_id constraint."""
        check_sql = """
        SELECT COUNT(*) as constraint_exists
        FROM information_schema.table_constraints
        WHERE table_name = 'trade_ledger'
        AND constraint_name = 'unique_signal_id';
        """

        result = await self.session.execute(text(check_sql))
        count = result.scalar() or 0

        return {
            "name": "unique_signal_id",
            "type": "UNIQUE",
            "status": "active" if count > 0 else "missing",
            "description": "Prevents duplicate signals per agent",
        }

    async def _check_single_open_position_constraint(self) -> dict[str, Any]:
        """Check single open position constraint."""
        check_sql = """
        SELECT COUNT(*) as index_exists
        FROM pg_indexes
        WHERE indexname = 'single_open_position_idx';
        """

        result = await self.session.execute(text(check_sql))
        count = result.scalar() or 0

        return {
            "name": "single_open_position_idx",
            "type": "UNIQUE INDEX",
            "status": "active" if count > 0 else "missing",
            "description": "Single open position per symbol/agent",
        }

    async def _check_lifecycle_constraint(self) -> dict[str, Any]:
        """Check lifecycle constraint."""
        check_sql = """
        SELECT COUNT(*) as constraint_exists
        FROM information_schema.table_constraints
        WHERE table_name = 'trade_ledger'
        AND constraint_name = 'valid_lifecycle';
        """

        result = await self.session.execute(text(check_sql))
        count = result.scalar() or 0

        return {
            "name": "valid_lifecycle",
            "type": "CHECK",
            "status": "active" if count > 0 else "missing",
            "description": "Valid trade lifecycle enforcement",
        }

    async def _check_relationship_constraint(self) -> dict[str, Any]:
        """Check relationship constraint."""
        check_sql = """
        SELECT COUNT(*) as constraint_exists
        FROM information_schema.table_constraints
        WHERE table_name = 'trade_ledger'
        AND constraint_name = 'valid_parent_child';
        """

        result = await self.session.execute(text(check_sql))
        count = result.scalar() or 0

        return {
            "name": "valid_parent_child",
            "type": "CHECK",
            "status": "active" if count > 0 else "missing",
            "description": "Valid parent-child relationships",
        }

    async def _check_performance_indexes(self) -> list[dict[str, Any]]:
        """Check performance indexes."""
        index_names = ["agent_performance_idx", "symbol_queries_idx", "signal_id_lookup_idx"]
        results = []

        for index_name in index_names:
            check_sql = f"""
            SELECT COUNT(*) as index_exists
            FROM pg_indexes
            WHERE indexname = '{index_name}';
            """

            result = await self.session.execute(text(check_sql))
            count = result.scalar() or 0

            results.append(
                {
                    "name": index_name,
                    "type": "INDEX",
                    "status": "active" if count > 0 else "missing",
                    "description": f"Performance index: {index_name}",
                }
            )

        return results
