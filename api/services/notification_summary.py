"""Shared notification summary computation for DB and in-memory snapshots."""

from __future__ import annotations

from typing import Any

from api.constants import FieldName


def compute_notification_summary(notifications: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a stable, UI-ready summary object for notification panels."""
    by_severity = {
        FieldName.SUCCESS: sum(
            1 for n in notifications if str(n.get(FieldName.SEVERITY, "")).lower() == "success"
        ),
        FieldName.INFO: sum(
            1
            for n in notifications
            if str(n.get(FieldName.SEVERITY, "")).lower() in {"info", "urgent"}
        ),
        FieldName.WARNING: sum(
            1 for n in notifications if str(n.get(FieldName.SEVERITY, "")).lower() == "warning"
        ),
        FieldName.CRITICAL: sum(
            1
            for n in notifications
            if str(n.get(FieldName.SEVERITY, "")).lower() in {"critical", "error"}
        ),
    }
    total = len(notifications)
    open_count = sum(
        1 for n in notifications if str(n.get(FieldName.STATE, "open")).lower() != "resolved"
    )
    resolved_count = total - open_count

    return {
        FieldName.SUMMARY_VERSION: 1,
        FieldName.COUNTS: {
            FieldName.TOTAL: total,
            FieldName.OPEN: open_count,
            FieldName.RESOLVED: resolved_count,
        },
        FieldName.SEVERITY_COUNTS: [
            {FieldName.SEVERITY: "success", FieldName.COUNT: by_severity[FieldName.SUCCESS]},
            {FieldName.SEVERITY: "info", FieldName.COUNT: by_severity[FieldName.INFO]},
            {FieldName.SEVERITY: "warning", FieldName.COUNT: by_severity[FieldName.WARNING]},
            {FieldName.SEVERITY: "critical", FieldName.COUNT: by_severity[FieldName.CRITICAL]},
        ],
        # Backward-compatible fields:
        FieldName.TOTAL: total,
        FieldName.OPEN: open_count,
        FieldName.RESOLVED: resolved_count,
        FieldName.BY_SEVERITY: by_severity,
    }
