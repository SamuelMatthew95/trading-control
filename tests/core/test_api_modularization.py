from pathlib import Path


def test_modular_api_structure_exists():
    expected = [
        Path("api/main.py"),
        Path("api/routes/analyze.py"),
        Path("api/routes/trades.py"),
        Path("api/routes/performance.py"),
        Path("api/services/trading.py"),
        Path("api/core/models/__init__.py"),
    ]
    assert all(path.exists() for path in expected)


def test_readme_contains_core_sections():
    with open("README.md", "r", encoding="utf-8") as readme_file:
        content = readme_file.read()

    assert "## Installation" in content
    assert "## Configuration" in content
    assert "## Run Tests" in content
