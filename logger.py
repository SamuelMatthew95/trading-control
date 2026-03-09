"""
Centralized Logging Module
Provides structured logging with performance monitoring
"""

import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class ColoredFormatter(logging.Formatter):
    """Colored log formatter for console output"""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def __init__(self, fmt=None):
        super().__init__(
            fmt or "%(asctime)s | %(name)s | %(levelname)s | %(message)s (%(lineno)d)"
        )

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)


class LogPerformance:
    """Context manager for logging performance"""

    def __init__(self, logger: logging.Logger, operation: str):
        self.logger = logger
        self.operation = operation
        self.start_time = None
        self.end_time = None
        self.duration = None

    def __enter__(self):
        from datetime import datetime

        self.start_time = datetime.now().timestamp()
        self.logger.debug(f"Starting {self.operation}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        from datetime import datetime

        self.end_time = datetime.now().timestamp()
        self.duration = self.end_time - self.start_time
        self.logger.debug(f"Completed {self.operation} in {self.duration:.3f}s")


def setup_logging(
    level: str = "INFO", log_file: Optional[str] = None, enable_colors: bool = True
) -> None:
    """Setup logging configuration"""
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        filename=log_file,
    )

    # If log_file is specified, ensure it's created by writing a test message
    if log_file:
        import os
        from pathlib import Path

        log_path = Path(log_file)
        os.makedirs(log_path.parent, exist_ok=True)

        # Create the file manually to ensure it exists
        log_path.touch()

        # Write a test message to ensure file is created
        logger = logging.getLogger(__name__)
        logger.info("Logging initialized")

        # Force flush to ensure file is written
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.flush()

    # Set specific logger levels
    configure_specific_loggers()


def configure_specific_loggers() -> None:
    """Configure specific loggers for different components"""
    # Set third-party loggers to WARNING level
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # Set application loggers to DEBUG level
    logging.getLogger("services").setLevel(logging.DEBUG)
    logging.getLogger("core").setLevel(logging.DEBUG)
    logging.getLogger("agent").setLevel(logging.DEBUG)


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance"""
    logger = logging.getLogger(name)

    if not logger.handlers:
        # Create console handler
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            ColoredFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

        logger.addHandler(handler)
        # Only set level if root logger hasn't been configured
        root_logger = logging.getLogger()
        if len(root_logger.handlers) == 0:
            logger.setLevel(logging.INFO)

    return logger


def log_structured(logger: logging.Logger, level, message: str, **kwargs) -> None:
    """Log structured data with additional context"""
    log_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "message": message,
        **kwargs,
    }

    # Handle both string and integer level inputs
    if isinstance(level, str):
        level_name = level.lower()
    else:
        level_name = logging.getLevelName(level).lower()

    getattr(logger, level_name)(f"{message} | Context: {log_data}")


def monitor_performance(threshold_ms=None):
    """Decorator to monitor function performance"""

    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            with LogPerformance(logger, f"{func.__name__} execution"):
                result = func(*args, **kwargs)
                # Check threshold if provided
                if threshold_ms and hasattr(LogPerformance, "duration"):
                    duration_ms = LogPerformance.duration * 1000
                    if duration_ms > threshold_ms:
                        logger.warning(
                            f"Function {func.__name__} exceeded threshold: {duration_ms:.2f}ms > {threshold_ms}ms"
                        )
                return result

        return wrapper

    return decorator
