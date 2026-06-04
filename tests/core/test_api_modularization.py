from pathlib import Path


def test_modular_api_structure_exists():
    expected = [
        Path("api/main.py"),
        Path("api/routes/trades.py"),
        Path("api/core/models/__init__.py"),
    ]
    assert all(path.exists() for path in expected)


def test_dead_orchestrator_cluster_removed():
    """The pre-event-driven manual-orchestrator cluster stays removed.

    See docs/troubleshooting/system-routes.md: /analyze 500'd on every call
    and feedback/performance were non-importable fossils. Re-adding any of
    these (or re-registering the analyze router) must fail CI.
    """
    removed = [
        Path("api/routes/analyze.py"),
        Path("api/routes/feedback.py"),
        Path("api/routes/performance.py"),
        Path("api/main_state.py"),
        Path("api/services/trading.py"),
        Path("api/services/multi_agent_orchestrator.py"),
    ]
    assert not any(path.exists() for path in removed), (
        "A removed manual-orchestrator module reappeared: "
        f"{[str(p) for p in removed if p.exists()]}"
    )
    main_src = Path("api/main.py").read_text(encoding="utf-8")
    assert "analyze_router" not in main_src


def test_readme_contains_core_sections():
    with open("README.md", encoding="utf-8") as readme_file:
        content = readme_file.read()

    assert "Quick Start" in content
    assert "Configuration" in content
    assert "Testing" in content
    assert "Agent Pipeline" in content
    assert "Architecture" in content
