"""
Regression test - prevents id=unknown forever.
"""

import pytest
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_write_system_metric_logs_real_id(caplog, safe_writer):
    """Prevents regression of id=unknown bug."""
    msg_id = "test-123-abc"
    
    await safe_writer.write_system_metric(
        msg_id=msg_id,
        metric_name="test",
        metric_value=1.0,
        metric_unit=None,
        tags={},
        schema_version="v2",
        source="test",
        timestamp=datetime.now(timezone.utc),
    )
    
    assert f"id={msg_id}" in caplog.text
    assert "id=unknown" not in caplog.text
