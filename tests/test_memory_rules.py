#!/usr/bin/env python3
"""
Test suite for memory rule compliance.

Validates that memory rule files are properly structured
and contain required sections.
"""

import re
from pathlib import Path

import pytest


class TestMemoryRules:
    """Test suite for memory rule files."""

    @pytest.fixture
    def memory_files(self) -> dict[str, Path]:
        """Get all memory rule files."""
        project_root = Path(__file__).parent.parent
        rules_dir = project_root / ".claude" / "rules"

        return {
            "trading": rules_dir / "memory-trading.md",
            "agents": rules_dir / "memory-agents.md",
            "logging": rules_dir / "memory-logging.md",
            "cicd": rules_dir / "memory-cicd.md",
        }

    def test_memory_files_exist(self, memory_files: dict[str, Path]):
        """Test that all memory files exist."""
        for name, path in memory_files.items():
            assert path.exists(), f"Memory file {name} does not exist: {path}"
            assert path.is_file(), f"Memory path {name} is not a file: {path}"

    def test_version_headers(self, memory_files: dict[str, Path]):
        """Test that all memory files have proper version headers."""
        version_pattern = (
            r"# Memory File: .*\n# Version: v\d+\.\d+\n# Last Updated: \d{4}-\d{2}-\d{2}"
        )

        for name, path in memory_files.items():
            content = path.read_text()
            lines = content.split("\n")[:4]  # First 4 lines

            header_text = "\n".join(lines)
            assert re.search(version_pattern, header_text), (
                f"Memory file {name} missing proper version header. Got:\n{header_text}"
            )

    def test_required_sections(self, memory_files: dict[str, Path]):
        """Test that memory files contain required sections."""
        required_sections = {
            "trading": ["## Broker Configuration", "## Order Execution Rules"],
            "agents": ["## Agent Communication Rules", "## Trace ID Propagation"],
            "logging": ["## Structured Logging Requirements", "## Trace ID Lifecycle Management"],
            "cicd": ["## Critical CI/CD Commands", "## Common CI/CD Failure Patterns"],
        }

        for name, path in memory_files.items():
            content = path.read_text()

            for section in required_sections.get(name, []):
                assert section in content, f"Memory file {name} missing required section: {section}"

    def test_file_size_limits(self, memory_files: dict[str, Path]):
        """Test that memory files don't exceed size limits."""
        max_lines = 500  # Recommended max lines per memory file

        for name, path in memory_files.items():
            lines = len(path.read_text().split("\n"))
            assert lines <= max_lines, (
                f"Memory file {name} exceeds size limit: {lines} > {max_lines} lines"
            )

    def test_trace_id_requirements(self, memory_files: dict[str, Path]):
        """Test that trace ID requirements are properly documented."""
        trace_id_patterns = [r"trace_id", r"Trace ID", r"traceability"]

        # At least 3 files should mention trace IDs
        trace_id_files = 0

        for _name, path in memory_files.items():
            content = path.read_text()

            if any(re.search(pattern, content, re.IGNORECASE) for pattern in trace_id_patterns):
                trace_id_files += 1

        assert trace_id_files >= 3, (
            f"Trace ID requirements not sufficiently documented (found in {trace_id_files}/4 files)"
        )

    def test_no_production_secrets(self, memory_files: dict[str, Path]):
        """Test that no production secrets or keys are in memory files."""
        forbidden_patterns = [
            r"sk-[a-zA-Z0-9]{48}",  # OpenAI API keys
            r"ghp_[a-zA-Z0-9]{36}",  # GitHub personal access tokens
            r"AKIA[0-9A-Z]{16}",  # AWS access keys
        ]

        for name, path in memory_files.items():
            content = path.read_text()

            for pattern in forbidden_patterns:
                matches = re.findall(pattern, content)
                assert not matches, (
                    f"Memory file {name} contains potential secret: {pattern} in {matches}"
                )
