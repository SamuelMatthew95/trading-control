"""
Utility Functions for Trading Control Platform
Common helper functions and utilities
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar, Union

from logger import get_logger

logger = get_logger(__name__)

# Type variables for generic functions
T = TypeVar("T")
R = TypeVar("R")


# ============================================================================
# ID Generation Functions
# ============================================================================


def generate_entity_id(prefix: str) -> str:
    """Generate a unique entity ID with prefix"""
    timestamp = int(time.time())
    short_uuid = uuid.uuid4().hex[:8]
    return f"{prefix}_{timestamp}_{short_uuid}"


def generate_id() -> str:
    """Generate a simple unique ID"""
    return uuid.uuid4().hex


# ============================================================================
# Validation Functions
# ============================================================================


def validate_score(score: float, field_name: str = "score") -> float:
    """Validate that a score is between 0.0 and 1.0"""
    if not (0.0 <= score <= 1.0):
        raise ValueError(f"{field_name} must be between 0.0 and 1.0, got {score}")
    return score


def validate_percentage(percentage: float, field_name: str = "percentage") -> float:
    """Validate that a percentage is between 0.0 and 100.0"""
    if not (0.0 <= percentage <= 100.0):
        raise ValueError(
            f"{field_name} must be between 0.0 and 100.0, got {percentage}"
        )
    return percentage


def validate_price(
    price: Union[str, float, Decimal], field_name: str = "price"
) -> Decimal:
    """Validate and convert price to Decimal"""
    try:
        decimal_price = Decimal(str(price))
        if decimal_price <= 0:
            raise ValueError(f"{field_name} must be positive, got {price}")
        return decimal_price
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"Invalid {field_name} value: {price}") from e


def is_valid_symbol(symbol: Optional[str]) -> bool:
    """Validate stock symbol format"""
    if not symbol or not isinstance(symbol, str):
        return False
    
    # Check length (1-10 characters)
    if len(symbol) < 1 or len(symbol) > 10:
        return False
    
    # Check for allowed characters (letters, numbers, dot, hyphen)
    if not re.match(r'^[A-Za-z0-9.\-]+$', symbol):
        return False
    
    # Check if it starts with a letter
    if not re.match(r'^[A-Za-z]', symbol):
        return False
    
    return True


def is_valid_email(email: Optional[str]) -> bool:
    """Validate email format"""
    if not email or not isinstance(email, str):
        return False
    
    # Basic email regex
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def is_valid_url(url: Optional[str]) -> bool:
    """Validate URL format"""
    if not url or not isinstance(url, str):
        return False
    
    # Basic URL regex for http/https
    pattern = r'^https?://[^\s/$.?#].[^\s]*$'
    return bool(re.match(pattern, url))


def is_positive_number(value: Any) -> bool:
    """Check if value is a positive number"""
    try:
        num_value = float(value)
        return num_value > 0
    except (ValueError, TypeError):
        return False


def validate_quantity(
    quantity: Union[int, float, str], field_name: str = "quantity"
) -> int:
    """Validate and convert quantity to positive integer"""
    try:
        int_quantity = int(quantity)
        if int_quantity <= 0:
            raise ValueError(f"{field_name} must be positive integer, got {quantity}")
        return int_quantity
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid {field_name} value: {quantity}") from e


def validate_symbol(symbol: str) -> str:
    """Validate trading symbol format"""
    if not symbol or not symbol.isalnum():
        raise ValueError("Symbol cannot be empty and must be alphanumeric")
    if len(symbol) > 10:
        raise ValueError("Symbol cannot exceed 10 characters")
    return symbol.upper()


# ============================================================================
# Safe Type Conversion Functions
# ============================================================================


def safe_decimal(value: Union[str, float, int, Decimal]) -> Decimal:
    """Safely convert value to Decimal"""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as e:
        raise ValueError(f"Invalid decimal value: {value}") from e


def safe_json_serialize(data: Any) -> str:
    """Safely serialize data to JSON"""
    try:
        return json.dumps(data, default=str)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Cannot serialize data to JSON: {data}") from e


def safe_json_deserialize(json_str: str) -> Any:
    """Safely deserialize JSON string"""
    try:
        return json.loads(json_str)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid JSON string: {json_str}") from e


# ============================================================================
# Calculation Functions
# ============================================================================


def calculate_win_rate(wins: int, total: int) -> float:
    """Calculate win rate with safe division"""
    if total == 0:
        return 0.0
    return wins / total


def calculate_percentage_change(old_value: float, new_value: float) -> float:
    """Calculate percentage change"""
    if old_value == 0:
        return float("inf") if new_value > 0 else 0.0
    return ((new_value - old_value) / old_value) * 100


def moving_average(values: List[float], window: int) -> List[float]:
    """Calculate moving average"""
    if not values or window <= 0:
        return []

    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        end = i + 1
        avg = sum(values[start:end]) / (end - start)
        result.append(avg)

    return result


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value between min and max"""
    return max(min_val, min(value, max_val))


# ============================================================================
# Time Functions
# ============================================================================


def format_timestamp(timestamp: datetime) -> str:
    """Format timestamp for display"""
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def parse_timestamp(timestamp_str: str) -> datetime:
    """Parse timestamp string to datetime"""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(timestamp_str, fmt)
        except ValueError:
            continue

    raise ValueError(f"Invalid timestamp format: {timestamp_str}")


def is_within_last_hours(timestamp: datetime, hours: int) -> bool:
    """Check if timestamp is within last N hours"""
    cutoff = datetime.now() - timedelta(hours=hours)
    return timestamp >= cutoff


def is_within_last_days(timestamp: datetime, days: int) -> bool:
    """Check if timestamp is within last N days"""
    cutoff = datetime.now() - timedelta(days=days)
    return timestamp >= cutoff


def get_time_range_hours_ago(hours: int) -> tuple[datetime, datetime]:
    """Get time range for N hours ago"""
    end = datetime.now()
    start = end - timedelta(hours=hours)
    return start, end


def get_time_range_days_ago(days: int) -> tuple[datetime, datetime]:
    """Get time range for N days ago"""
    end = datetime.now()
    start = end - timedelta(days=days)
    return start, end


# ============================================================================
# String Functions
# ============================================================================


def truncate_string(text: str, max_length: int, suffix: str = "...", ellipsis: bool = True) -> str:
    """Truncate string to max length"""
    if len(text) <= max_length:
        return text
    
    if ellipsis:
        return text[: max_length - len(suffix)] + suffix
    else:
        return text[:max_length]


def sanitize_string(text: str) -> str:
    """Sanitize string by removing potentially dangerous content"""
    # Basic XSS protection - remove script tags and dangerous content
    sanitized = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    # Remove control characters except common whitespace
    sanitized = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", sanitized)
    return sanitized


def format_currency(amount: Union[int, float, Decimal]) -> str:
    """Format amount as currency"""
    try:
        decimal_amount = Decimal(str(amount))
        return f"${decimal_amount:.2f}"
    except (InvalidOperation, ValueError):
        return f"${amount:.2f}"


def format_percentage(value: Union[int, float]) -> str:
    """Format value as percentage"""
    try:
        decimal_value = Decimal(str(value))
        return f"{(decimal_value * 100):.2f}%"
    except (InvalidOperation, ValueError):
        return f"{(value * 100):.2f}%"


def flatten_dict(
    d: Dict[str, Any], parent_key: str = "", sep: str = "."
) -> Dict[str, Any]:
    """Flatten nested dictionary"""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def chunk_list(lst: List[T], chunk_size: int) -> List[List[T]]:
    """Split list into chunks"""
    return [lst[i : i + chunk_size] for i in range(0, len(lst), chunk_size)]


# ============================================================================
# Decorators
# ============================================================================


def retry_async(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Async retry decorator with exponential backoff"""

    def decorator(func: Callable[..., R]) -> Callable[..., R]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> R:
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt == max_attempts - 1:
                        break
                    wait_time = delay * (backoff**attempt)
                    logger.warning(
                        f"Attempt {attempt + 1} failed for {func.__name__}, retrying in {wait_time}s: {e}"
                    )
                    await asyncio.sleep(wait_time)
            raise last_exception

        return wrapper

    return decorator


def timeit(func: Callable[..., R]) -> Callable[..., R]:
    """Decorator to time function execution"""

    @wraps(func)
    def wrapper(*args, **kwargs) -> R:
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            end_time = time.time()
            duration = end_time - start_time
            logger.debug(f"{func.__name__} executed in {duration:.3f}s")

    return wrapper


def async_timeit(func: Callable[..., R]) -> Callable[..., R]:
    """Decorator to time async function execution"""

    @wraps(func)
    async def wrapper(*args, **kwargs) -> R:
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            return result
        finally:
            end_time = time.time()
            duration = end_time - start_time
            logger.debug(f"{func.__name__} executed in {duration:.3f}s")

    return wrapper


# ============================================================================
# Context Managers
# ============================================================================


@contextmanager
def PerformanceTimer(operation_name: str):
    """Context manager for timing operations"""

    class Timer:
        def __init__(self):
            self.start_time: Optional[float] = None
            self.end_time: Optional[float] = None
            self.duration: Optional[float] = None

        def __enter__(self):
            self.start_time = time.time()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.end_time = time.time()
            if self.start_time:
                self.duration = self.end_time - self.start_time

    timer = Timer()
    with timer:
        yield timer
    if timer.duration is not None:
        logger.debug(f"Operation '{operation_name}' completed in {timer.duration:.3f}s")


# ============================================================================
# Utility Classes
# ============================================================================


class CircularBuffer(Generic[T]):
    """Circular buffer with fixed size"""

    def __init__(self, max_size: int):
        self.max_size = max_size
        self.buffer: deque[T] = deque(maxlen=max_size)

    def append(self, item: T) -> None:
        """Add item to buffer"""
        self.buffer.append(item)

    def get_all(self) -> List[T]:
        """Get all items in buffer"""
        return list(self.buffer)

    def clear(self) -> None:
        """Clear buffer"""
        self.buffer.clear()

    def __len__(self) -> int:
        return len(self.buffer)


class RateLimiter:
    """Simple rate limiter"""

    def __init__(self, max_calls: int, time_window: timedelta):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls: List[datetime] = []

    def can_call(self) -> bool:
        """Check if call is allowed"""
        now = datetime.now()
        # Remove old calls
        self.calls = [
            call_time for call_time in self.calls if now - call_time < self.time_window
        ]

        if len(self.calls) < self.max_calls:
            self.calls.append(now)
            return True
        return False


# ============================================================================
# Hashing Functions
# ============================================================================


def hash_string(text: str, algorithm: str = "sha256") -> str:
    """Hash string using specified algorithm"""
    try:
        hasher = hashlib.new(algorithm)
        hasher.update(text.encode("utf-8"))
        return hasher.hexdigest()
    except ValueError as e:
        raise ValueError(f"Unsupported hash algorithm: {algorithm}") from e


# ============================================================================
# Data Validation Utilities
# ============================================================================


def validate_email(email: str) -> bool:
    """Validate email format"""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(pattern, email) is not None


def validate_url(url: str) -> bool:
    """Validate URL format"""
    pattern = r"^https?://(?:[-\w.])+(?:\:[0-9]+)?(?:/(?:[\w/_.])*(?:\?(?:[\w&=%.])*)?(?:#(?:\w*))?)?$"
    return re.match(pattern, url) is not None


# ============================================================================
# Math Utilities
# ============================================================================


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safe division with default value for division by zero"""
    if denominator == 0:
        return default
    return numerator / denominator


def round_to_nearest(value: float, nearest: float) -> float:
    """Round value to nearest multiple"""
    return round(value / nearest) * nearest


# ============================================================================
# Collection Utilities
# ============================================================================


def deep_merge_dicts(dict1: Dict[str, Any], dict2: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries"""
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def filter_dict_by_keys(
    d: Dict[str, Any], keys: List[str], include: bool = True
) -> Dict[str, Any]:
    """Filter dictionary by keys"""
    if include:
        return {k: v for k, v in d.items() if k in keys}
    else:
        return {k: v for k, v in d.items() if k not in keys}


# ============================================================================
# Async Utilities
# ============================================================================


def gather_with_errors(*coros, return_exceptions: bool = False) -> List[Any]:
    """Gather coroutines with error handling"""
    results = []
    for coro in coros:
        try:
            # Note: This function should be called within an async context
            result = coro  # Remove await for synchronous context
            results.append(result)
        except Exception as e:
            if return_exceptions:
                results.append(e)
            else:
                logger.error(f"Error in coroutine: {e}")
                results.append(None)
    return results


# ============================================================================
# Performance Monitoring
# ============================================================================


class PerformanceMonitor:
    """Simple performance monitoring"""

    def __init__(self):
        self.metrics: Dict[str, List[float]] = defaultdict(list)

    def record(self, metric_name: str, value: float) -> None:
        """Record metric value"""
        self.metrics[metric_name].append(value)
        # Keep only last 1000 values
        if len(self.metrics[metric_name]) > 1000:
            self.metrics[metric_name] = self.metrics[metric_name][-1000:]

    def get_stats(self, metric_name: str) -> Dict[str, float]:
        """Get statistics for metric"""
        values = self.metrics.get(metric_name, [])
        if not values:
            return {}

        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "latest": values[-1],
        }

    def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        """Get statistics for all metrics"""
        return {name: self.get_stats(name) for name in self.metrics.keys()}


# ============================================================================
# Configuration Utilities
# ============================================================================


def get_env_var(key: str, default: str = "", required: bool = False) -> str:
    """Get environment variable with optional default and requirement"""
    import os

    value = os.getenv(key, default)
    if required and not value:
        raise ValueError(f"Required environment variable {key} is not set")
    return value


def parse_bool(value: Union[str, bool, int]) -> bool:
    """Parse boolean value from various types"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return False


# ============================================================================
# Error Handling Utilities
# ============================================================================


class TradingControlError(Exception):
    """Base exception for trading control platform"""

    pass


class ValidationError(TradingControlError):
    """Validation error"""

    pass


class BusinessLogicError(TradingControlError):
    """Business logic error"""

    pass


def handle_errors(func: Callable[..., R]) -> Callable[..., R]:
    """Decorator for consistent error handling"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except TradingControlError:
            raise  # Re-raise our custom exceptions
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {e}")
            raise TradingControlError(f"An unexpected error occurred: {e}") from e

    return wrapper


# ============================================================================
# Logging Utilities
# ============================================================================


def log_function_call(func: Callable[..., R]) -> Callable[..., R]:
    """Decorator to log function calls"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.debug(f"Calling {func.__name__} with args={args}, kwargs={kwargs}")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"{func.__name__} completed successfully")
            return result
        except Exception as e:
            logger.error(f"{func.__name__} failed with error: {e}")
            raise

    return wrapper


# ============================================================================
# Data Transformation Utilities
# ============================================================================


def normalize_text(text: str) -> str:
    """Normalize text by removing extra whitespace and converting to lowercase"""
    return " ".join(text.lower().split())


def extract_numbers(text: str) -> List[float]:
    """Extract all numbers from text"""
    return [float(num) for num in re.findall(r"-?\d+\.?\d*", text)]


def extract_urls(text: str) -> List[str]:
    """Extract all URLs from text"""
    url_pattern = r"https?://(?:[-\w.])+(?:\:[0-9]+)?(?:/(?:[\w/_.])*(?:\?(?:[\w&=%.])*)?(?:#(?:\w*))?)?"
    return re.findall(url_pattern, text)


# ============================================================================
# Memory Management Utilities
# ============================================================================


def get_object_size(obj: Any) -> int:
    """Get approximate object size in bytes"""
    import sys

    return sys.getsizeof(obj)


def monitor_memory_usage(func: Callable[..., R]) -> Callable[..., R]:
    """Decorator to monitor memory usage"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        import os

        import psutil

        process = psutil.Process(os.getpid())
        memory_before = process.memory_info().rss

        try:
            result = func(*args, **kwargs)
            return result
        finally:
            memory_after = process.memory_info().rss
            memory_diff = memory_after - memory_before
            logger.debug(
                f"{func.__name__} memory usage: {memory_diff / 1024 / 1024:.2f} MB"
            )

    return wrapper


# ============================================================================
# Testing Utilities
# ============================================================================


def create_mock_data(count: int, factory: Callable[[], T]) -> List[T]:
    """Create mock data for testing"""
    return [factory() for _ in range(count)]


def assert_valid_email(email: str) -> None:
    """Assert that email is valid"""
    if not validate_email(email):
        raise ValueError(f"Invalid email: {email}")


def assert_valid_url(url: str) -> None:
    """Assert that URL is valid"""
    if not validate_url(url):
        raise ValueError(f"Invalid URL: {url}")


# ============================================================================
# Export all utilities
# ============================================================================

__all__ = [
    # ID generation
    "generate_entity_id",
    "generate_id",
    # Validation
    "validate_score",
    "validate_percentage",
    "validate_price",
    "validate_quantity",
    "validate_symbol",
    # Type conversion
    "safe_decimal",
    "safe_json_serialize",
    "safe_json_deserialize",
    # Calculations
    "calculate_win_rate",
    "calculate_percentage_change",
    "moving_average",
    "clamp",
    # Time
    "format_timestamp",
    "parse_timestamp",
    "is_within_last_hours",
    "is_within_last_days",
    "get_time_range_hours_ago",
    "get_time_range_days_ago",
    # String utilities
    "truncate_string",
    "sanitize_string",
    "flatten_dict",
    "chunk_list",
    # Decorators
    "retry_async",
    "timeit",
    "async_timeit",
    "handle_errors",
    "log_function_call",
    # Context managers
    "PerformanceTimer",
    # Classes
    "CircularBuffer",
    "RateLimiter",
    "PerformanceMonitor",
    # Hashing
    "hash_string",
    # Validation
    "validate_email",
    "validate_url",
    # Math
    "safe_divide",
    "round_to_nearest",
    # Collections
    "deep_merge_dicts",
    "filter_dict_by_keys",
    # Async
    "gather_with_errors",
    # Configuration
    "get_env_var",
    "parse_bool",
    # Errors
    "TradingControlError",
    "ValidationError",
    "BusinessLogicError",
    # Data transformation
    "normalize_text",
    "extract_numbers",
    "extract_urls",
    # Memory
    "get_object_size",
    "monitor_memory_usage",
    # Testing
    "create_mock_data",
    "assert_valid_email",
    "assert_valid_url",
]
