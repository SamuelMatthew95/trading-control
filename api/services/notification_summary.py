"""Shared notification summary computation for DB and in-memory snapshots."""

from __future__ import annotations

from typing import Any


def compute_notification_summary(notifications: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a stable, UI-ready summary object for notification panels."""
    by_severity = {
        "success": sum(1 for n in notifications if str(n.get("severity", "")).lower() == "success"),
        "info": sum(
            1 for n in notifications if str(n.get("severity", "")).lower() in {"info", "urgent"}
        ),
        "warning": sum(1 for n in notifications if str(n.get("severity", "")).lower() == "warning"),
        "critical": sum(
            1 for n in notifications if str(n.get("severity", "")).lower() in {"critical", "error"}
        ),
    }
    total = len(notifications)
    open_count = sum(1 for n in notifications if str(n.get("state", "open")).lower() != "resolved")
    resolved_count = total - open_count

    return {
        "summary_version": 1,
        "counts": {
            "total": total,
            "open": open_count,
            "resolved": resolved_count,
        },
        "severity_counts": [
            {"severity": "success", "count": by_severity["success"]},
            {"severity": "info", "count": by_severity["info"]},
            {"severity": "warning", "count": by_severity["warning"]},
            {"severity": "critical", "count": by_severity["critical"]},
        ],
        # Backward-compatible fields:
        "total": total,
        "open": open_count,
        "resolved": resolved_count,
        "by_severity": by_severity,
    }
