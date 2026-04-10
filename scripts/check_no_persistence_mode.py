#!/usr/bin/env python3
"""
CI check to ensure PERSISTENCE_MODE is never reintroduced.
This script scans the codebase for any PERSISTENCE_MODE references that shouldn't exist.
"""

import ast
import os
import sys
from pathlib import Path


def check_file_for_persistence_mode(file_path):
    """Check a single file for problematic PERSISTENCE_MODE references."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return False
    
    issues = []
    lines = content.split('\n')
    
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        
        # Skip comments and docstrings
        if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        
        # Check for problematic patterns
        problematic_patterns = [
            "settings.PERSISTENCE_MODE",
            "app.state.persistence_mode",
            "PERSISTENCE_MODE:",
            "PERSISTENCE_MODE =",
            "def validate_persistence_mode",
            "@field_validator(\"PERSISTENCE_MODE\")",
        ]
        
        for pattern in problematic_patterns:
            if pattern in line:
                issues.append(f"{file_path}:{i}: {pattern} found in: {line.strip()}")
    
    # Check AST for field definitions
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "PERSISTENCE_MODE":
                    issues.append(f"{file_path}: PERSISTENCE_MODE field definition found")
            
            if isinstance(node, ast.FunctionDef) and "persistence_mode" in node.name.lower():
                if "validate" in node.name.lower():
                    issues.append(f"{file_path}: {node.name} function found")
    except SyntaxError:
        # Skip files that can't be parsed (likely not Python)
        pass
    
    return issues


def main():
    """Main CI check function."""
    print("Checking for PERSISTENCE_MODE references...")
    
    # Files to check (exclude test files and scripts)
    python_files = []
    for root, dirs, files in os.walk('.'):
        # Skip hidden directories and common exclusions
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__' and d != 'node_modules' and d != 'scripts']
        
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                # Skip test files and this script
                if ('test_' in file or 
                    '_test.py' in file or 
                    'tests/' in file_path or 
                    file_path.startswith('./tests/') or
                    'check_no_persistence_mode.py' in file_path):
                    continue
                python_files.append(file_path)
    
    all_issues = []
    
    for file_path in python_files:
        issues = check_file_for_persistence_mode(file_path)
        all_issues.extend(issues)
    
    if all_issues:
        print("ERROR: Found PERSISTENCE_MODE references that should not exist:")
        for issue in all_issues:
            print(f"  {issue}")
        print("\nThese references must be removed to prevent regression.")
        sys.exit(1)
    else:
        print("SUCCESS: No problematic PERSISTENCE_MODE references found.")
        sys.exit(0)


if __name__ == "__main__":
    main()
