#!/usr/bin/env python3
"""
Test suite for memory rule compliance.

Validates that memory rule files are properly structured
and contain required sections.
"""

import pytest
import re
from pathlib import Path
from typing import Dict, List, Any

class TestMemoryRules:
    """Test suite for memory rule files."""
    
    @pytest.fixture
    def memory_files(self) -> Dict[str, Path]:
        """Get all memory rule files."""
        project_root = Path(__file__).parent.parent
        rules_dir = project_root / ".claude" / "rules"
        
        return {
            "trading": rules_dir / "memory-trading.md",
            "agents": rules_dir / "memory-agents.md", 
            "logging": rules_dir / "memory-logging.md",
            "cicd": rules_dir / "memory-cicd.md"
        }
    
    def test_memory_files_exist(self, memory_files: Dict[str, Path]):
        """Test that all memory files exist."""
        for name, path in memory_files.items():
            assert path.exists(), f"Memory file {name} does not exist: {path}"
            assert path.is_file(), f"Memory path {name} is not a file: {path}"
    
    def test_version_headers(self, memory_files: Dict[str, Path]):
        """Test that all memory files have proper version headers."""
        version_pattern = r"^# .* Memory File: .*\n# Version: v\d+\.\d+\n# Last Updated: \d{4}-\d{2}-\d{2}"
        
        for name, path in memory_files.items():
            content = path.read_text()
            lines = content.split('\n')[:3]  # First 3 lines
            
            header_text = '\n'.join(lines)
            assert re.match(version_pattern, header_text, re.MULTILINE), \
                f"Memory file {name} missing proper version header. Got:\n{header_text}"
    
    def test_no_hardcoded_urls(self, memory_files: Dict[str, Path]):
        """Test that memory files don't contain hardcoded production URLs."""
        forbidden_patterns = [
            r'onrender\.com',
            r'vercel\.app', 
            r'localhost:8000',
            r'https://api\.alpaca\.markets'  # Should use paper URL
        ]
        
        for name, path in memory_files.items():
            content = path.read_text()
            
            for pattern in forbidden_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                assert not matches, \
                    f"Memory file {name} contains forbidden URL pattern '{pattern}': {matches}"
    
    def test_required_sections(self, memory_files: Dict[str, Path]):
        """Test that memory files contain required sections."""
        required_sections = {
            "trading": ["## Broker Configuration", "## Order Execution Rules"],
            "agents": ["## Agent Communication Rules", "## Trace ID Propagation"],
            "logging": ["## Structured Logging Requirements", "## Trace ID Lifecycle Management"],
            "cicd": ["## Critical CI/CD Commands", "## Common CI/CD Failure Patterns"]
        }
        
        for name, path in memory_files.items():
            content = path.read_text()
            
            for section in required_sections.get(name, []):
                assert section in content, \
                    f"Memory file {name} missing required section: {section}"
    
    def test_code_example_quality(self, memory_files: Dict[str, Path]):
        """Test that code examples follow project patterns."""
        for name, path in memory_files.items():
            content = path.read_text()
            
            # Find all code blocks
            code_blocks = re.findall(r'```python\n(.*?)\n```', content, re.DOTALL)
            
            for block in code_blocks:
                # Check for common anti-patterns in examples
                anti_patterns = [
                    r'logger\.',  # Should use log_structured
                    r'error=str\(',  # Should use exc_info=True
                    r'id="\$"',  # Redis keyword args
                    r'Depends\('  # Should use Annotated syntax
                ]
                
                for pattern in anti_patterns:
                    matches = re.findall(pattern, block)
                    assert not matches, \
                        f"Memory file {name} contains anti-pattern in code example: {pattern} in {matches}"
    
    def test_environment_variable_consistency(self, memory_files: Dict[str, Path]):
        """Test that environment variables are consistent with .env.example."""
        project_root = Path(__file__).parent.parent
        env_example = project_root / ".env.example"
        
        if not env_example.exists():
            pytest.skip("No .env.example file found")
        
        env_content = env_example.read_text()
        env_vars = set(re.findall(r'^([A-Z_]+)=', env_content, re.MULTILINE))
        
        for name, path in memory_files.items():
            content = path.read_text()
            
            # Find environment variable references
            referenced_vars = set(re.findall(r'[A-Z_]+', content))
            
            # Check if referenced vars exist in .env.example
            missing_vars = referenced_vars - env_vars
            if missing_vars:
                # Allow some vars that might be runtime-only
                allowed_missing = {
                    'TRACE_ID', 'SCHEMA_VERSION', 'SOURCE_NAME'
                }
                missing_vars -= allowed_missing
                
                assert not missing_vars, \
                    f"Memory file {name} references environment variables not in .env.example: {missing_vars}"
    
    def test_file_size_limits(self, memory_files: Dict[str, Path]):
        """Test that memory files don't exceed size limits."""
        max_lines = 500  # Recommended max lines per memory file
        
        for name, path in memory_files.items():
            lines = len(path.read_text().split('\n'))
            assert lines <= max_lines, \
                f"Memory file {name} exceeds size limit: {lines} > {max_lines} lines"
    
    def test_no_duplicate_rules(self, memory_files: Dict[str, Path]):
        """Test that there are no duplicate rules across files."""
        all_rules = {}
        
        for name, path in memory_files.items():
            content = path.read_text()
            
            # Extract rule headers (## sections)
            rules = re.findall(r'^## (.+)', content, re.MULTILINE)
            
            for rule in rules:
                if rule in all_rules:
                    pytest.fail(f"Duplicate rule '{rule}' found in {name} and {all_rules[rule]}")
                all_rules[rule] = name
    
    def test_trace_id_requirements(self, memory_files: Dict[str, Path]):
        """Test that trace ID requirements are properly documented."""
        trace_id_patterns = [
            r'trace_id',
            r'Trace ID',
            r'traceability'
        ]
        
        # At least 3 files should mention trace IDs
        trace_id_files = 0
        
        for name, path in memory_files.items():
            content = path.read_text()
            
            if any(re.search(pattern, content, re.IGNORECASE) for pattern in trace_id_patterns):
                trace_id_files += 1
        
        assert trace_id_files >= 3, \
            f"Trace ID requirements not sufficiently documented (found in {trace_id_files}/4 files)"
