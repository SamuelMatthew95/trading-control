"""
Stream Processing Logic - Pure business logic for testing.

Contains message processing logic separated from infrastructure concerns.
"""

from datetime import datetime, timezone
from typing import Any

from .schemas import ProcessResult


class MessageProcessor:
    """Pure message processing logic - no infrastructure dependencies."""

    def __init__(self):
        self.processed_count = 0
        self.error_count = 0

    def validate_message(self, data: dict[str, Any]) -> ProcessResult:
        """Validate message structure and required fields."""
        if not isinstance(data, dict):
            return ProcessResult(
                success=False, retryable=False, message="Message must be a dictionary"
            )

        required_fields = ["msg_id"]
        for field in required_fields:
            if field not in data:
                return ProcessResult(
                    success=False,
                    retryable=False,
                    message=f"Missing required field: {field}",
                )

        return ProcessResult(success=True, retryable=False)

    def process_order_message(self, msg_id: str, data: dict[str, Any]) -> ProcessResult:
        """Process order message - pure business logic."""
        validation = self.validate_message(data)
        if not validation.success:
            return validation

        # Business logic for order processing
        try:
            symbol = data.get("symbol")
            side = data.get("side")
            quantity = data.get("quantity")

            if not all([symbol, side, quantity]):
                return ProcessResult(
                    success=False,
                    retryable=False,
                    message="Missing order fields: symbol, side, or quantity",
                )

            # Validate order data
            if side not in ["buy", "sell"]:
                return ProcessResult(
                    success=False, retryable=False, message=f"Invalid side: {side}"
                )

            try:
                quantity = float(quantity)
                if quantity <= 0:
                    return ProcessResult(
                        success=False,
                        retryable=False,
                        message="Quantity must be positive",
                    )
            except (ValueError, TypeError):
                return ProcessResult(
                    success=False, retryable=False, message="Invalid quantity format"
                )

            self.processed_count += 1
            return ProcessResult(
                success=True,
                retryable=False,
                message=f"Order processed: {symbol} {side} {quantity}",
            )

        except Exception as e:
            self.error_count += 1
            return ProcessResult(
                success=False, retryable=True, message=f"Processing error: {str(e)}"
            )

    def process_execution_message(
        self, msg_id: str, data: dict[str, Any]
    ) -> ProcessResult:
        """Process execution message - pure business logic."""
        validation = self.validate_message(data)
        if not validation.success:
            return validation

        try:
            order_id = data.get("order_id")
            status = data.get("status")

            if not order_id:
                return ProcessResult(
                    success=False, retryable=False, message="Missing order_id"
                )

            if not status:
                return ProcessResult(
                    success=False, retryable=False, message="Missing status"
                )

            valid_statuses = ["pending", "filled", "cancelled", "rejected"]
            if status not in valid_statuses:
                return ProcessResult(
                    success=False, retryable=False, message=f"Invalid status: {status}"
                )

            self.processed_count += 1
            return ProcessResult(
                success=True,
                retryable=False,
                message=f"Execution processed: {order_id} {status}",
            )

        except Exception as e:
            self.error_count += 1
            return ProcessResult(
                success=False, retryable=True, message=f"Processing error: {str(e)}"
            )

    def create_dlq_entry(self, message: dict[str, Any], error: str) -> dict[str, Any]:
        """Create DLQ entry data - pure logic."""
        return {
            "original_stream": message.get("stream", "unknown"),
            "original_id": message.get("message_id", "unknown"),
            "data": message.get("data", {}),
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "processing_attempt": 1,
        }


class BackpressureController:
    """Pure backpressure logic - no infrastructure dependencies."""

    def __init__(self):
        self.error_count = 0
        self.consecutive_db_errors = 0
        self.backoff_seconds = 1.0
        self.max_backoff = 30.0
        self.circuit_breaker_threshold = 5

    def should_apply_backpressure(self, error: Exception) -> bool:
        """Determine if backpressure should be applied."""
        error_str = str(error).lower()
        return "connection" in error_str or "timeout" in error_str

    def record_error(self, error: Exception) -> float:
        """Record error and calculate backoff delay."""
        if self.should_apply_backpressure(error):
            self.consecutive_db_errors += 1
            self.backoff_seconds = min(self.backoff_seconds * 2, self.max_backoff)
        else:
            self.consecutive_db_errors = 0

        self.error_count += 1
        return self.backoff_seconds

    def is_circuit_breaker_open(self) -> bool:
        """Check if circuit breaker should open."""
        return self.consecutive_db_errors >= self.circuit_breaker_threshold

    def reset(self) -> None:
        """Reset error counters."""
        self.error_count = 0
        self.consecutive_db_errors = 0
        self.backoff_seconds = 1.0
