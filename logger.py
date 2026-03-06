"""
Centralized Logging Module
Provides structured logging with performance monitoring
"""

import logging
import sys
import time
from datetime import datetime
from typing import Any, Dict, Optional
from pathlib import Path


class ColoredFormatter(logging.Formatter):
    """Colored log formatter for console output"""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'
    
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
        
    def __enter__(self):
        self.start_time = time.time()
        self.logger.debug(f"Starting {self.operation}")
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        self.logger.debug(f"Completed {self.operation} in {duration:.3f}s")


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """Setup logging configuration"""
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        filename=log_file
    )
    
    # Set specific logger levels
    configure_specific_loggers()


def configure_specific_loggers() -> None:
    """Configure specific loggers for different components"""
    pass


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance"""
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        # Create console handler
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(ColoredFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    
    return logger


def log_structured(logger: logging.Logger, level: str, message: str, **kwargs) -> None:
    """Log structured data with additional context"""
    log_data = {
        'timestamp': datetime.utcnow().isoformat(),
        'message': message,
        **kwargs
    }
    
    getattr(logger, level.lower())(f"{message} | Context: {log_data}")


def monitor_performance(func):
    """Decorator to monitor function performance"""
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        with LogPerformance(logger, f"{func.__name__} execution"):
            return func(*args, **kwargs)
    return wrapper


# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
