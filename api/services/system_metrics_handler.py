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
    # 🚫 HARD DISABLE - CRITICAL FIX
    raise RuntimeError("LEGACY_HANDLER_SHOULD_NOT_BE_USED - Use SystemMetricsConsumer instead")
