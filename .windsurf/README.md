# Windsurf Configuration

This directory configures Windsurf IDE settings for the trading-control project.

## Configuration

- **Project**: `trading-control` (Python)
- **Rules**: Primary rules in `.claude/rules/` (referenced via `.windsurfrules`)
- **Memory**: Uses Windsurf's internal memory system
- **Bridge**: `.windsurfrules` file at project root

## Integration Strategy

Windsurf uses `.windsurfrules` at project root to reference Claude Code rules:
- Points to `.claude/rules/` for primary project standards
- Maintains hybrid approach: Windsurf for UI coding, Claude Code for deep dives
- No duplication - Windsurf reads directly from existing Claude structure

## Project Structure

- `.windsurfrules` - Bridge file pointing to Claude rules
- `.windsurf/config.json` - Basic project metadata
- `.claude/rules/` - Primary source of truth for project rules
- `.claude/memory/` - Claude Code memory system
- `.claude/tasks/` - Claude Code task definitions
