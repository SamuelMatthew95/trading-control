"""
System metrics handler - LEGACY CODE (OBSOLETE)

⚠️  THIS CODE IS NO LONGER USED IN PRODUCTION
===============================================

This handler has been replaced by SystemMetricsConsumer.
Keeping this file only for backward compatibility with existing tests.

Active processing path:
SystemMetricsConsumer → SafeWriter.write_system_metric

This handler should NOT be used in new code.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from api.core.schemas import ProcessResult
from api.core.writer.safe_writer import SafeWriter
from api.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def handle_system_metric(
    msg_id: str, stream: str, data: Dict[str, Any], trace_id: str
) -> ProcessResult:
    """
    LEGACY: Handle system metric messages.
    
    ⚠️  DEPRECATED: Use SystemMetricsConsumer instead.
    This function is kept only for test compatibility.
    """
    logger.warning(
        f"LEGACY handle_system_metric called - this should be replaced by SystemMetricsConsumer. "
        f"msg_id={msg_id}, trace_id={trace_id}"
    )
    try:
        # Validate required fields
        if not data.get("metric_name"):
            return ProcessResult(
                success=False,
                retryable=False,
                message="Missing metric_name"
            )
        
        if "value" not in data:
            return ProcessResult(
                success=False,
                retryable=False,
                message="Missing value"
            )
        
        # Write to database using SafeWriter
        safe_writer = SafeWriter(AsyncSessionLocal)
        
        # Handle timestamp with fallback
        timestamp_str = data.get("timestamp")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)
        
        # Use new signature with explicit parameters
        await safe_writer.write_system_metric(
            msg_id=msg_id,
            metric_name=data["metric_name"],
            metric_value=float(data["value"]),
            metric_unit=data.get("unit"),
            tags=data.get("tags", {}),
            schema_version="v2",
            source="system_monitor",
            timestamp=timestamp,
        )
        
        logger.debug(f"Processed system metric: {data['metric_name']} = {data['value']}")
        
        return ProcessResult(
            success=True,
            retryable=False,
            message=f"Processed metric: {data['metric_name']}"
        )
        
    except Exception as e:
        logger.error(f"Error processing system metric {msg_id}: {e}")
        
        # ❗ Only retry true transient errors, NOT duplicates or logic bugs
        retryable = not any(
            keyword in str(e).lower()
            for keyword in [
                "duplicate",
                "already exists", 
                "already processed",
                "constraint",
                "unexpected keyword argument",
                "integrity error",
                "unique constraint",
                "msg_id is required",
                "metric_name is required",
                "metric_value is required",
            ]
        )
        
        return ProcessResult(
            success=False,
            retryable=retryable,
            message=f"Processing error: {str(e)}"
        )
