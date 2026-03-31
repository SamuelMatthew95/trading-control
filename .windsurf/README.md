# Windsurf Configuration

This directory configures Windsurf IDE settings for the trading-control project.

## Configuration

- **Project**: `trading-control` (Python)
- **Rules**: Located in `.windsurf/rules/` directory
- **Memory**: Uses Windsurf's internal memory system

## Rules Structure

Windsurf automatically discovers and applies rules from `.windsurf/rules/`:

- `cicd-patterns.md` - CI/CD pipeline requirements and common fixes
- `trading-rules.md` - Alpaca trading and order execution rules  
- `development-standards.md` - Project architecture and coding standards

## Rules Discovery

Windsurf automatically loads rules from:
- Current workspace `.windsurf/rules` directory
- Subdirectories up to git root
- All `.md` files with proper YAML frontmatter

## Integration Notes

- Rules are copied from `.claude/rules/` and formatted for Windsurf
- Each rule file includes YAML frontmatter for proper discovery
- Windsurf uses its own memory system (separate from `.claude/memory`)
- Hybrid approach: Windsurf for daily coding, Claude Code for deep dives
