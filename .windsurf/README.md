# Windsurf Configuration

This directory configures Windsurf IDE settings for the trading-control project.

## Configuration

- **Project**: `trading-control` (Python)
- **Rules**: Located in `.windsurf/rules/` directory
- **Memory**: Uses Windsurf's internal memory system

## Rules Structure

- `cicd-patterns.md` - CI/CD pipeline requirements and common fixes
- `trading-rules.md` - Alpaca trading and order execution rules

## IDE Integration

Windsurf automatically discovers and applies rules from:
- Current workspace `.windsurf/rules` directory
- Subdirectories up to git root

## Notes

- Rules are copied from `.claude/rules/` and formatted for Windsurf
- Windsurf uses its own memory system - `.claude/memory` is not used
- Configuration focuses on project metadata only
