"""
System Monitoring - Health monitoring and performance metrics
Extracted from observability/ for system-monitoring skill
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class HealthChecker:
    """System health monitoring and checking"""

    def __init__(self):
        self.checker_id = "health_checker"
        self.last_check: Optional[datetime] = None
        self.health_history: List[Dict[str, Any]] = []

    async def check_system_health(self) -> Dict[str, Any]:
        """Perform comprehensive system health check"""
        check_time = datetime.now()
        self.last_check = check_time

        try:
            # Simulate health checks
            checks = {
                "database": await self._check_database_health(),
                "api": await self._check_api_health(),
                "memory": await self._check_memory_health(),
                "cpu": await self._check_cpu_health(),
            }

            # Calculate overall health score
            health_scores = [check["score"] for check in checks.values()]
            overall_score = sum(health_scores) / len(health_scores)
            
            health_status = "healthy" if overall_score >= 80 else "degraded" if overall_score >= 60 else "unhealthy"

            health_result = {
                "timestamp": check_time.isoformat(),
                "overall_score": overall_score,
                "status": health_status,
                "checks": checks,
                "alerts": self._generate_alerts(checks),
            }

            # Store in history (keep last 100)
            self.health_history.append(health_result)
            if len(self.health_history) > 100:
                self.health_history.pop(0)

            return health_result

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "timestamp": check_time.isoformat(),
                "overall_score": 0,
                "status": "error",
                "checks": {},
                "alerts": [{"type": "error", "message": f"Health check failed: {e}"}],
            }

    async def _check_database_health(self) -> Dict[str, Any]:
        """Check database connectivity and performance"""
        # Simulate database health check
        return {
            "score": 95,
            "status": "healthy",
            "response_time_ms": 25,
            "connection_pool": {"active": 5, "idle": 15, "total": 20},
        }

    async def _check_api_health(self) -> Dict[str, Any]:
        """Check API endpoints and response times"""
        # Simulate API health check
        return {
            "score": 88,
            "status": "healthy",
            "response_time_ms": 120,
            "endpoints_checked": 12,
            "success_rate": 0.98,
        }

    async def _check_memory_health(self) -> Dict[str, Any]:
        """Check memory usage and availability"""
        # Simulate memory health check
        return {
            "score": 82,
            "status": "healthy",
            "usage_percent": 65,
            "available_gb": 8.2,
            "total_gb": 16.0,
        }

    async def _check_cpu_health(self) -> Dict[str, Any]:
        """Check CPU usage and performance"""
        # Simulate CPU health check
        return {
            "score": 79,
            "status": "degraded",
            "usage_percent": 78,
            "load_average": [1.2, 1.5, 1.8],
        }

    def _generate_alerts(self, checks: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate alerts based on health check results"""
        alerts = []

        for component, check in checks.items():
            if check["score"] < 80:
                alerts.append({
                    "type": "warning" if check["score"] >= 60 else "critical",
                    "component": component,
                    "message": f"{component.title()} health degraded: {check['score']}%",
                    "score": check["score"],
                })

        return alerts

    def get_health_summary(self) -> Dict[str, Any]:
        """Get summary of recent health checks"""
        if not self.health_history:
            return {
                "last_check": None,
                "current_status": "unknown",
                "recent_trend": "stable",
                "average_score": 0,
            }

        recent_checks = self.health_history[-10:]  # Last 10 checks
        current_status = self.health_history[-1]["status"]
        average_score = sum(check["overall_score"] for check in recent_checks) / len(recent_checks)

        # Determine trend
        if len(recent_checks) >= 3:
            recent_scores = [check["overall_score"] for check in recent_checks[-3:]]
            if recent_scores[-1] > recent_scores[0]:
                trend = "improving"
            elif recent_scores[-1] < recent_scores[0]:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            "last_check": self.health_history[-1]["timestamp"],
            "current_status": current_status,
            "recent_trend": trend,
            "average_score": round(average_score, 1),
            "checks_analyzed": len(recent_checks),
        }
