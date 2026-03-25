"""
Production-safe database startup verification.

NEVER create tables in app runtime - only verify connection and schema.
"""

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
import logging

logger = logging.getLogger(__name__)

def ensure_database_ready(engine):
    """Verify database is properly migrated before starting application."""
    try:
        inspector = inspect(engine)
        
        # Critical tables that must exist
        required_tables = [
            'strategies',
            'orders', 
            'positions',
            'agent_pool',
            'agent_runs',
            'agent_logs',
            'events',
            'vector_memory',
            'trade_performance'
        ]
        
        missing_tables = []
        for table in required_tables:
            if not inspector.has_table(table):
                missing_tables.append(table)
        
        if missing_tables:
            error_msg = f"Database not properly migrated. Missing tables: {missing_tables}. Run 'alembic upgrade head'"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # Verify critical indexes exist
        critical_indexes = [
            ('orders', 'idx_orders_strategy_status'),
            ('positions', 'idx_positions_strategy_symbol'),
            ('trade_performance', 'idx_trade_unique'),
            ('agent_logs', 'idx_agent_logs_trace'),
            ('events', 'idx_events_entity_created')
        ]
        
        missing_indexes = []
        for table, index_name in critical_indexes:
            if not inspector.has_index(table, index_name):
                missing_indexes.append(f"{table}.{index_name}")
        
        if missing_indexes:
            error_msg = f"Critical indexes missing: {missing_indexes}. Run 'alembic upgrade head'"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        logger.info("Database schema verification passed")
        return True
        
    except SQLAlchemyError as e:
        error_msg = f"Database connection failed: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)


def analyze_vector_table(engine):
    """Run ANALYZE on vector_memory table for index performance."""
    try:
        with engine.connect() as conn:
            conn.execute("ANALYZE vector_memory;")
            logger.info("Vector table analyzed for optimal index performance")
    except SQLAlchemyError as e:
        logger.warning(f"Failed to analyze vector table: {e}")


# Production startup guard
def safe_startup(engine):
    """Complete production-safe startup verification."""
    ensure_database_ready(engine)
    analyze_vector_table(engine)
    logger.info("Production startup verification complete")
