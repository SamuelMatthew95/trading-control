from pathlib import Path


def test_modular_api_structure_exists():
    expected = [
        Path("api/main.py"),
        Path("api/routes/analyze.py"),
        Path("api/routes/trades.py"),
        Path("api/routes/performance.py"),
        Path("api/services/trading.py"),
        Path("api/core/models.py"),
    ]
    assert all(path.exists() for path in expected)


def test_readme_mentions_db_backed_persistent_memory():
    content = Path("README.md").read_text(encoding="utf-8")
    assert "Persistent Memory" in content
    assert "Agent-level performance tracking" in content
