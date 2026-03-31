# Windsurf Configuration

This directory configures Windsurf IDE settings for the trading-control project.

## Configuration

- **Memory Path**: `.claude/` - Contains project memory and context
- **Rules Path**: `.claude/rules/` - Contains coding standards and guidelines  
- **Tasks Path**: `.claude/tasks/` - Contains project task management

## IDE Integration

Windsurf will automatically use the `.claude` folder for:
- Project memory and context
- Coding rules and standards
- Task management and workflows

## Notes

- This configuration points Windsurf to use your existing `.claude` folder structure
- No duplicate data - Windsurf reads directly from your Claude memory system
- Empty `plans/` directory is reserved for future IDE-specific planning features
