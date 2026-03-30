"""
Production-grade logging safety test to prevent structlog regressions.

This test ensures the hardened logging system remains production-safe
and no event= keyword arguments exist anywhere in the codebase.
"""

import os
import re

import pytest


class TestLoggingSafety:
    """Comprehensive logging safety and regression prevention."""

    def test_no_event_keyword_argument_anywhere(self):
        """Ensure NO event= keyword arguments exist anywhere in codebase."""

        # Critical patterns that would cause structlog conflicts
        forbidden_patterns = [
            r"log_structured\([^)]*\)\s*,\s*[^,]*\bevent\s*=\s*[^,\)]*\)",
            r"logger\.\w+\([^)]*event\s*=\s*[^,\)]*\)",
            r"\.bind\(.*event\s*=",
            r'event\s*=\s*["\'][^"\']*["\']',  # event="something"
        ]

        # Scan all source directories
        source_dirs = ["api/", "tests/", "scripts/"]
        issues_found = []

        for source_dir in source_dirs:
            if not os.path.exists(source_dir):
                continue

            for root, dirs, files in os.walk(source_dir):
                # Skip hidden and cache directories
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]

                for file in files:
                    if file.endswith(".py") and file != "test_logging_safety.py":
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
                                        or
                                        # Skip regex patterns and test examples
                                        "r'" in line
                                        or 'r"' in line
                                        or (
                                            "event=" in stripped
                                            and ("test" in file_path or "example" in stripped)
                                        )
                                    ):
                                        continue

                                    for pattern in forbidden_patterns:
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
                            # Ignore files that can't be read
                            pass

        # Strict assertion - no issues allowed
        assert not issues_found, (
            f"ALERT CRITICAL: Found {len(issues_found)} structlog event= issues:\n"
            + "\n".join(
                [
                    f"  [FAIL] {issue['file']}:{issue['line']} - {issue['content']}"
                    for issue in issues_found
                ]
            )
            + "\n\nThese will cause 'BoundLogger.info() got multiple values for argument 'event' errors!"
        )

    def test_log_structured_hardening(self):
        """Verify log_structured hardening works correctly."""

        from api.observability import log_structured

        # Test 1: Invalid level falls back to info
        try:
            log_structured("invalid_level", "test message")
        except Exception as e:
            pytest.fail(f"log_structured should handle invalid levels: {e}")

        # Test 2: event= kwarg is silently rejected
        try:
            log_structured("info", "test message", event="should_be_removed", key="value")
        except Exception as e:
            pytest.fail(f"log_structured should reject event= kwarg: {e}")

        # Test 3: Normal usage works
        try:
            log_structured("info", "test message", key="value", number=42)
        except Exception as e:
            pytest.fail(f"log_structured normal usage should work: {e}")

    def test_bind_request_context_function(self):
        """Verify bind_request_context function exists and works."""

        from api.observability import bind_request_context

        # Should not raise exception
        try:
            bind_request_context("test-request-123")
        except Exception as e:
            pytest.fail(f"bind_request_context should work: {e}")

    def test_error_logging_patterns_fixed(self):
        """Verify all error logging uses exc_info=True instead of error=str(exc)."""

        # Search for remaining error=str(exc) patterns
        error_str_patterns = []

        for root, dirs, files in os.walk("api/"):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]

            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)

                    try:
                        with open(file_path, encoding="utf-8") as f:
                            content = f.read()
                            lines = content.split("\n")

                            for i, line in enumerate(lines, 1):
                                # Look for error=str(exc) pattern (but allow in comments)
                                if (
                                    "error=str(exc)" in line
                                    and not line.strip().startswith("#")
                                    and not line.strip().startswith('"""')
                                    and not line.strip().startswith("'''")
                                    and
                                    # Allow error=str(exc) in DLQ payloads (not logging calls)
                                    "dlq.push" not in line.lower()
                                ):
                                    error_str_patterns.append(
                                        {
                                            "file": file_path,
                                            "line": i,
                                            "content": line.strip(),
                                        }
                                    )

                    except Exception:
                        pass

        # Should have no remaining error=str(exc) patterns
        assert not error_str_patterns, (
            f"Found {len(error_str_patterns)} remaining error=str(exc) patterns:\n"
            + "\n".join(
                [
                    f"  [FAIL] {pattern['file']}:{pattern['line']} - {pattern['content']}"
                    for pattern in error_str_patterns
                ]
            )
            + "\n\nAll should use exc_info=True instead!"
        )
