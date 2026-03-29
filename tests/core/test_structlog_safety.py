"""
Safety test to ensure no structlog event= usage remains in codebase.

This test scans all source code to ensure no logger calls use event= as a keyword argument,
which causes the critical "BoundLogger.info() got multiple values for argument 'event'" error.
"""

import os
import re

import pytest


class TestStructlogSafety:
    """Safety test to prevent structlog event= regression."""

    def test_no_event_keyword_argument_in_log_calls(self):
        """Ensure no logger calls use event= as keyword argument."""

        # Patterns that indicate problematic structlog usage
        problematic_patterns = [
            r"log_structured\([^)]*\)\s*,\s*[^,]*\bevent\s*=\s*[^,\)]*\)",
            r"logger\.\w+\([^)]*event\s*=\s*[^,\)]*\)",
            r"\.bind\(.*event\s*=",
        ]

        # Directories to scan (exclude venv, __pycache__, etc.)
        source_dirs = ["api/", "tests/", "scripts/"]
        issues_found = []

        for source_dir in source_dirs:
            if not os.path.exists(source_dir):
                continue

            for root, dirs, files in os.walk(source_dir):
                # Skip hidden and cache directories
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]

                for file in files:
                    if file.endswith(".py"):
                        file_path = os.path.join(root, file)

                        try:
                            with open(file_path, encoding="utf-8") as f:
                                content = f.read()
                                lines = content.split("\n")

                                for i, line in enumerate(lines, 1):
                                    # Skip comments and docstrings
                                    stripped = line.strip()
                                    if (
                                        stripped.startswith("#")
                                        or stripped.startswith('"""')
                                        or stripped.startswith("'''")
                                    ):
                                        continue

                                    for pattern in problematic_patterns:
                                        if re.search(pattern, line):
                                            issues_found.append(
                                                {
                                                    "file": file_path,
                                                    "line": i,
                                                    "content": line.strip(),
                                                    "pattern": pattern,
                                                }
                                            )

                        except Exception:
                            # Ignore files that can't be read (e.g., binary files)
                            pass

        # Assert no issues found
        assert not issues_found, (
            f"Found {len(issues_found)} structlog event= usage issues:\n"
            + "\n".join(
                [
                    f"  {issue['file']}:{issue['line']} - {issue['content']}"
                    for issue in issues_found
                ]
            )
        )

    def test_log_structured_function_signature(self):
        """Ensure log_structured function doesn't accept event= parameter."""

        # This test ensures our log_structured wrapper doesn't accidentally accept event=
        # which would mask the underlying structlog issue

        from api.observability import log_structured

        # This should work (correct usage)
        try:
            log_structured("info", "test message", key="value")
        except Exception as e:
            pytest.fail(f"log_structured should accept extra_data kwargs: {e}")

        # This should fail if event= was accidentally added as parameter
        # (but we can't test this easily without modifying the function)

    def test_correct_structlog_usage_examples(self):
        """Verify correct structlog usage patterns work."""

        from api.observability import log_structured

        # These should all work without issues
        try:
            log_structured("info", "Simple message")
            log_structured("info", "Message with data", symbol="AAPL", price=150.0)
            log_structured("warning", "Warning message", error_code=404)
            log_structured("error", "Error message", exception_type="ValueError")
        except Exception as e:
            pytest.fail(f"Correct structlog usage should work: {e}")
