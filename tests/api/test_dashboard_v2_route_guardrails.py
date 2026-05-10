from pathlib import Path


def test_core_read_routes_do_not_do_source_selection_inline():
    content = Path("api/routes/dashboard_v2.py").read_text()
    for route in [
        "/snapshot",
        "/pnl",
        "/agents",
        "/orders",
        "/state",
        "/prices",
        "/trade-feed",
        "/system/metrics",
        "/system-metrics",
        "/positions",
        "/portfolio",
        "/lifecycle",
        "/agent-runs",
        "/notifications",
        "/learning/grades",
        "/learning/ic-weights",
        "/learning/proposals",
        "/learning/reflections",
        "/learning/loop",
        "/learning/loop/status",
        "/pnl/paired",
        "/agents/status",
        "/events/recent",
        "/history/events",
        "/trace/{trace_id}",
        "/performance-trends",
        "/agent-instances",
        "/stream-lag",
        "/system-health",
        "/flow-status",
        "/challengers",
    ]:
        idx = content.find(f'@router.get("{route}")')
        assert idx != -1
        block = content[idx : idx + 700]
        assert "get_runtime_store()" not in block
        assert "is_db_available()" not in block
