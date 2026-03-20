"""
Custom exceptions for the trading bot system.
"""


class TradingBotError(Exception):
    """Base exception for all trading bot errors."""
    pass


class SchemaNotInitialisedError(TradingBotError):
    """Raised when database schema is not properly initialized."""
    pass


class KillSwitchActiveError(TradingBotError):
    """Raised when kill switch is active and operations should stop."""
    pass


class StrategyNotFoundError(TradingBotError):
    """Raised when a strategy name cannot be resolved to a UUID."""
    pass


class InsufficientCashError(TradingBotError):
    """Raised when insufficient cash for order execution."""
    pass


class LockAcquisitionError(TradingBotError):
    """Raised when unable to acquire Redis lock for order processing."""
    pass


class BudgetExceededError(TradingBotError):
    """Raised when LLM token budget is exceeded."""
    pass


class BrokerError(TradingBotError):
    """Raised when broker operations fail."""
    pass


class DLQError(TradingBotError):
    """Raised when dead letter queue operations fail."""
    pass


class OrderIdempotencyError(TradingBotError):
    """Raised when duplicate order detection fails."""
    pass
