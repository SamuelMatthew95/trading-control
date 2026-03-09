"""
Core package for trading system
"""

from .config import get_settings
from .logger import get_logger
from .main import main
from .models import BaseModel
from .stateful_logging_system import (
    AgentStatus,
    DatabaseManager,
    EventType,
    LogLevel,
    PerformanceMetric,
    StatefulLogger,
    TestDatabaseManager,
    create_stateful_logging_system,
)

__all__ = [
    # Logging system
    "DatabaseManager",
    "StatefulLogger",
    "TestDatabaseManager",
    "LogLevel",
    "EventType",
    "AgentStatus",
    "PerformanceMetric",
    "create_stateful_logging_system",
    # Core utilities
    "get_settings",
    "get_logger",
    "BaseModel",
    "main",
]
