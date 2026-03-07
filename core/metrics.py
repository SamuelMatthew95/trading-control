"""
System Metrics - Simple metrics collection and tracking
"""

from datetime import datetime
from typing import Any, Dict

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    logger = None


class SystemMetrics:
    """Simple system metrics collector"""

    def __init__(self) -> None:
        self.metrics = {
            "total_tasks_processed": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "total_duration_ms": 0.0,
            "average_task_duration": 0.0,
            "success_rate": 0.0,
            "agents_active": 0,
            "data_freshness_ms": 0,
            "system_load": 0.0,
            "last_updated": datetime.now().isoformat(),
        }

    def record_task_completion(self, success: bool, duration_ms: float) -> None:
        """Record a task completion"""
        self.metrics["total_tasks_processed"] += 1

        if success:
            self.metrics["successful_tasks"] += 1
        else:
            self.metrics["failed_tasks"] += 1

        self.metrics["total_duration_ms"] += duration_ms

        # Update averages
        if self.metrics["total_tasks_processed"] > 0:
            self.metrics["average_task_duration"] = (
                self.metrics["total_duration_ms"]
                / self.metrics["total_tasks_processed"]
            )
            self.metrics["success_rate"] = (
                self.metrics["successful_tasks"] / self.metrics["total_tasks_processed"]
            )

        self.metrics["last_updated"] = datetime.now().isoformat()

    def update(
        self,
        total_tasks_processed: int,
        average_task_duration: float,
        success_rate: float,
        agents_active: int,
        data_freshness_ms: int,
        system_load: float,
    ) -> None:
        """Update metrics"""
        self.metrics.update(
            {
                "total_tasks_processed": total_tasks_processed,
                "average_task_duration": average_task_duration,
                "success_rate": success_rate,
                "agents_active": agents_active,
                "data_freshness_ms": data_freshness_ms,
                "system_load": system_load,
                "last_updated": datetime.now().isoformat(),
            }
        )

    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all metrics"""
        return self.metrics.copy()

    def get_system_load(self) -> float:
        """Get current system load"""
        return self.metrics.get("system_load", 0.0)

    def get_success_rate(self) -> float:
        """Get current success rate"""
        return self.metrics.get("success_rate", 0.0)

    def get_average_duration(self) -> float:
        """Get average task duration"""
        return self.metrics.get("average_task_duration", 0.0)
