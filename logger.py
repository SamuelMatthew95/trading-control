"""
Centralized Logging Configuration
Standard logging setup with structured formatting and no print statements
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


class ColoredFormatter(logging.Formatter):
    """Colored log formatter without emojis"""

    COLORS = {
        logging.DEBUG: "\033[36m",  # Cyan
        logging.INFO: "\033[32m",  # Green
        logging.WARNING: "\033[33m",  # Yellow
        logging.ERROR: "\033[31m",  # Red
        logging.CRITICAL: "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def __init__(self, fmt=None, datefmt=None, use_colors=True):
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors

    def format(self, record):
        if self.use_colors and record.levelno in self.COLORS:
            # Add color to levelname only
            original_levelname = record.levelname
            record.levelname = (
                f"{self.COLORS[record.levelno]}{record.levelname}{self.RESET}"
            )

        formatted = super().format(record)

        # Restore original levelname to avoid issues
        if self.use_colors and record.levelno in self.COLORS:
            record.levelname = original_levelname

        return formatted


def setup_logging(
    level: str = "INFO", log_file: Optional[str] = None, enable_colors: bool = True
) -> None:
    """Setup centralized logging configuration

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        enable_colors: Whether to enable colored console output
    """
    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))

    if enable_colors:
        console_formatter = ColoredFormatter()
    else:
        console_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-15s | %(lineno)3d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(logging.DEBUG)  # Log everything to file

        file_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-15s | %(lineno)3d | %(funcName)-20s | %(message)s | %(exc_info)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    # Configure specific loggers
    configure_specific_loggers()


def configure_specific_loggers() -> None:
    """Configure logging levels for specific modules"""

    # Third-party libraries (usually too verbose)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # Application modules
    app_loggers = [
        "services",
        "models",
        "utils",
        "config",
        "api.routes",
        "main_refactored",
    ]

    for logger_name in app_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)  # Allow debug messages for app code


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the specified name

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


# Context manager for logging performance
class LogPerformance:
    """Context manager for logging execution time"""

    def __init__(self, operation_name: str, logger: Optional[logging.Logger] = None):
        self.operation_name = operation_name
        self.logger = logger or logging.getLogger(__name__)
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def __enter__(self) -> LogPerformance:
        self.start_time = datetime.now().timestamp()
        self.logger.debug(f"Starting operation: {self.operation_name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.end_time = datetime.now().timestamp()

        if self.start_time and self.end_time:
            duration = self.end_time - self.start_time
            if exc_type is None:
                self.logger.info(
                    f"Completed operation: {self.operation_name} in {duration:.3f}s"
                )
            else:
                self.logger.error(
                    f"Failed operation: {self.operation_name} after {duration:.3f}s - {exc_val}"
                )
        else:
            self.logger.error(
                f"Failed to measure timing for operation: {self.operation_name}"
            )


# Function decorator for logging function calls
def log_function_calls(logger: Optional[logging.Logger] = None):
    """Decorator to log function entry and exit

    Args:
        logger: Logger instance to use (defaults to module logger)
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            func_logger = logger or logging.getLogger(func.__module__)
            func_name = f"{func.__module__}.{func.__name__}"

            # Log function entry
            func_logger.debug(f"Entering function: {func_name}")

            try:
                result = func(*args, **kwargs)
                func_logger.debug(f"Exiting function: {func_name} successfully")
                return result
            except Exception as e:
                func_logger.error(f"Error in function: {func_name} - {e}")
                raise

        return wrapper

    return decorator


# Structured logging helper
def log_structured(
    logger: logging.Logger, level: int, message: str, **kwargs: Any
) -> None:
    """Log structured data with additional context

    Args:
        logger: Logger instance
        level: Logging level
        message: Log message
        **kwargs: Additional structured data
    """
    # Format structured data
    structured_data = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    full_message = f"{message} | {structured_data}" if structured_data else message

    logger.log(level, full_message)


def _format_message(record: logging.LogRecord) -> str:
    """Format log message without emojis"""
    level = record.levelname
    name = record.name
    message = record.getMessage()

    # Add context if available
    context = getattr(record, "context", {})
    if context:
        context_str = " | ".join([f"{k}={v}" for k, v in context.items()])
        return f"[{level}] {name}: {message} | {context_str}"

    return f"[{level}] {name}: {message}"


# Performance monitoring decorator
def monitor_performance(threshold_ms: float = 100.0):
    """Decorator to monitor function performance

    Args:
        threshold_ms: Performance threshold in milliseconds
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = logging.getLogger(func.__module__)
            start_time = datetime.now().timestamp()

            try:
                result = func(*args, **kwargs)
                return result
            finally:
                end_time = datetime.now().timestamp()
                duration_ms = (end_time - start_time) * 1000

                if duration_ms > threshold_ms:
                    logger.warning(
                        f"Performance warning: {func.__name__} took {duration_ms:.2f}ms "
                        f"(threshold: {threshold_ms:.2f}ms)"
                    )
                else:
                    logger.debug(
                        f"Performance: {func.__name__} took {duration_ms:.2f}ms"
                    )

        return wrapper

    return decorator


# Initialize logging on import
setup_logging(level="INFO", enable_colors=True)
