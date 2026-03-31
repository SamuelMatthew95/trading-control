# Memory Rules - Contributing Guidelines

## Overview
This directory contains specialized memory files for Claude Code's 3-layer memory system. Each file focuses on specific domains to maintain context relevance and prevent information bloat.

## File Structure

```
.claude/rules/
├── memory-trading.md     # Alpaca trading, order execution, risk management
├── memory-agents.md      # Agent hand-off protocols, trace ID propagation
├── memory-logging.md     # Structured logging standards
├── memory-cicd.md       # CI/CD patterns and common fixes
└── README.md            # This file
```

## When to Create New Rule Files

### Create a new file when:
- Domain has 5+ specific rules that don't fit existing files
- Rules need path-scoping (specific directories)
- Existing files become >500 lines
- New domain is frequently accessed (e.g., frontend, database)

### File naming convention:
- `memory-{domain}.md` (e.g., `memory-frontend.md`, `memory-database.md`)
- Use lowercase, hyphen-separated names
- Keep names descriptive and concise

## How to Update Existing Rules

### Before making changes:
1. **Run audit script**: `python scripts/audit_trading_memory.py`
2. **Check for conflicts**: Search existing files for similar rules
3. **Test locally**: Verify changes don't break existing patterns

### Update process:
1. **Add version header** if not present:
   ```markdown
   # Memory File: {Domain}
   # Version: v1.1
   # Last Updated: 2026-03-31
   ```

2. **Make changes** with clear commit messages
3. **Update version** if breaking changes
4. **Test changes**:
   ```bash
   # Test memory loading
   /memory
   
   # Run compliance audit
   python scripts/audit_trading_memory.py
   ```

5. **Update tests** if applicable

## Rule Writing Guidelines

### DO:
- ✅ Use specific, actionable rules
- ✅ Include code examples for patterns
- ✅ Add "❌ WRONG" vs "✅ RIGHT" comparisons
- ✅ Reference related files with `@./path/to/file.md`
- ✅ Include environment variable requirements
- ✅ Add trace ID requirements for operations

### DON'T:
- ❌ Write generic advice ("write good code")
- ❌ Include outdated or deprecated patterns
- ❌ Mix multiple domains in one file
- ❌ Use ambiguous language ("consider", "maybe")
- ❌ Forget to update version headers

## Path-Scoped Rules

For domain-specific rules, use frontmatter path scoping:

```markdown
---
paths:
  - "api/services/agents/**"
  - "api/routes/trading/**"
---

# Agent-Specific Rules
Only applies to files in matching paths.
```

## Testing Rule Changes

### Local verification:
```bash
# 1. Check memory loading
/memory

# 2. Run compliance audit
python scripts/audit_trading_memory.py

# 3. Test specific patterns
grep -r "pattern_to_test" api/ --include="*.py"

# 4. Verify CI/CD compliance
ruff check . --fix && ruff format --check .
```

### Automated tests:
```bash
# Run memory rule tests
pytest tests/test_memory_rules.py -v

# Test specific rule file
pytest tests/test_memory_rules.py::test_trading_memory -v
```

## Version Management

### Version format: `v{major}.{minor}`
- **Major**: Breaking changes, removed rules
- **Minor**: Added rules, clarifications, typo fixes

### When to bump version:
- **v1.0 → v1.1**: Add new rules, fix examples
- **v1.1 → v2.0**: Remove deprecated rules, change requirements

### Version tracking:
- Update header in each file
- Add changelog entry to this file
- Tag releases if needed

## Common Patterns

### Error handling rules:
```python
# ❌ WRONG
except Exception as e:
    raise HTTPException(str(e))

# ✅ RIGHT  
except Exception as e:
    log_structured("error", "operation failed", exc_info=True)
    raise HTTPException(str(e)) from None
```

### Database rules:
```python
# ❌ WRONG
await session.execute(INSERT INTO orders VALUES (...))

# ✅ RIGHT
await writer.write(
    table="orders",
    data=data,
    schema_version="v3",
    source="service_name"
)
```

### Redis rules:
```python
# ❌ WRONG
await redis.xgroup_create(stream, group, id="$", mkstream=True)

# ✅ RIGHT
await redis.xgroup_create(stream, group, "$", mkstream=True)
```

## Troubleshooting

### Rules not applying:
1. Check file priority: local > project > user > managed
2. Verify path scoping if used
3. Run `/memory` to see loaded files
4. Check for syntax errors in markdown

### Conflicting rules:
1. Search all memory files for the pattern
2. Check which file has higher priority
3. Consolidate or specify domain

### Audit script issues:
1. Verify script is executable: `chmod +x scripts/audit_trading_memory.py`
2. Check Python version: `python3 --version`
3. Install dependencies if needed

## Review Process

### Before submitting PR:
1. [ ] All new rules have version headers
2. [ ] Audit script passes with >90% compliance
3. [ ] No conflicts with existing rules
4. [ ] Code examples are tested
5. [ ] Documentation is updated

### PR review checklist:
- [ ] Rules are specific and actionable
- [ ] Code examples follow project patterns
- [ ] Version numbers are updated correctly
- [ ] Files are properly named and organized
- [ ] No duplicate or redundant rules

## Changelog

### v1.0 (2026-03-31)
- Initial memory system implementation
- Added trading, agents, logging, CI/CD rule files
- Created audit script and contributing guidelines
