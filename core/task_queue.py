"""
Simple task queue for testing
"""

from enum import Enum
from typing import Any, Dict


class TaskStatus(Enum):
    """Task status"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskPriority(Enum):
    """Task priority levels"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Task:
    """Simple task for testing"""

    def __init__(self, task_id: str) -> None:
        self.id = task_id


class TaskQueue:
    """Simple task queue for testing"""

    def __init__(self, max_size: int = 1000) -> None:
        self.max_size = max_size
        self.tasks = {}
        self.total_completed = 0

    def add_task(
        self, task_type: str, symbol: str, priority: str, data: Dict[str, Any]
    ) -> str:
        """Add a task to the queue"""
        import uuid

        task_id = str(uuid.uuid4())
        self.tasks[task_id] = Task(task_id)
        return task_id

    def get_total_completed(self) -> int:
        """Get total completed tasks"""
        return self.total_completed

    def mark_task_completed(
        self, task_id: str, success: bool, duration_ms: float
    ) -> None:
        """Mark a task as completed"""
        self.total_completed += 1
