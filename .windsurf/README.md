# Windsurf Configuration

This directory configures Windsurf IDE settings for the trading-control project.

## Configuration

- **Project**: `trading-control` (Python)
- **Rules**: Located in `.windsurf/rules/` directory (official location)
- **Memory**: Uses Windsurf's internal memory system

## Rules Structure

Windsurf automatically discovers and applies rules from `.windsurf/rules/`:

- `cicd-patterns.md` - CI/CD pipeline requirements and common fixes
- `trading-rules.md` - Alpaca trading and order execution rules  
- `development-standards.md` - Project architecture and coding standards

## Official Rules Discovery

Windsurf automatically loads rules from:
- `.windsurf/rules/*.md` files with proper YAML frontmatter
- Each rule file must have `---description:---` frontmatter
- Rules are applied automatically by Cascade

## Notes

- Rules follow official Windsurf documentation structure
- Each file includes proper YAML frontmatter for discovery
- Windsurf uses its own memory system (separate from `.claude/memory`)
- Content is maintained separately from `.claude/rules/` for clarity
