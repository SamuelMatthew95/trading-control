"""System metrics handler - processes system_metrics stream."""

import logging
from typing import Dict, Any

from api.core.schemas import ProcessResult
from api.core.writer.safe_writer import SafeWriter
from api.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def handle_system_metric(
    msg_id: str, stream: str, data: Dict[str, Any], trace_id: str
) -> ProcessResult:
    """Handle system metric messages."""
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
        
        # Transform data to match SafeWriter expectations
        metric_data = {
            "schema_version": "v2",
            "source": "system_monitor",
            "metric_name": data["metric_name"],
            "value": data["value"]
        }
        
        await safe_writer.write_system_metric(msg_id, stream, metric_data)
        
        logger.debug(f"Processed system metric: {data['metric_name']} = {data['value']}")
        
        return ProcessResult(
            success=True,
            retryable=False,
            message=f"Processed metric: {data['metric_name']}"
        )
        
    except Exception as e:
        logger.error(f"Error processing system metric {msg_id}: {e}")
        return ProcessResult(
            success=False,
            retryable=True,  # Retry on transient errors
            message=f"Processing error: {str(e)}"
        )
