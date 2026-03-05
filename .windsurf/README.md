# Windsurf Rules Index

This directory contains specialized rules files for different aspects of the trading control platform development.

## Available Rules Files

### Core Rules
- **`../.windsurfrules`** - Main Python development standards
- **`config.toml`** - Rules configuration and mapping

### Specialized Rules
- **`api.md`** - API development standards (FastAPI, REST, OpenAPI)
- **`database.md`** - Database development standards (SQLAlchemy, migrations)
- **`testing.md`** - Testing standards (pytest, coverage, TDD)
- **`security.md`** - Security standards (authentication, authorization, data protection)
- **`performance.md`** - Performance standards (profiling, optimization, monitoring)
- **`config.md`** - Configuration management standards (environment variables, validation)
- **`debugging.md`** - Debugging standards (logging, tools, remote debugging)

## Rule Application

The `config.toml` file defines how these rules are applied based on:

1. **File Patterns** - Different rules for different file types
2. **Directory Patterns** - Rules for entire directories
3. **Conditions** - Environment-based rule application
4. **Priority** - Rule priority when multiple rules apply
5. **Exclusions** - Files and directories to exclude

## Usage

Windsurf will automatically apply the appropriate rules based on:

- The file you're currently editing
- The directory structure
- Environment variables
- Project configuration

## Rule Hierarchy

Rules are applied in order of priority (higher number = higher priority):

1. Security (100) - Always applied in production
2. Performance (90) - Applied when performance is critical
3. Testing (80) - Applied to test files
4. API (70) - Applied to API-related files
5. Database (60) - Applied to database-related files
6. General (50) - Applied to all Python files
7. Configuration (40) - Applied to configuration files
8. Debugging (30) - Applied in development environment

## Customization

You can customize rule application by:

1. Modifying `config.toml` for different file patterns
2. Adding new rule files for specific needs
3. Adjusting priority levels
4. Setting environment-specific conditions
5. Adding exclusions for specific files or directories

## Examples

### API Development
When working on `api/routes.py`, the following rules apply:
- General Python rules (50)
- API rules (70)
- Testing rules (80) if in test environment
- Security rules (100) if in production

### Database Models
When working on `models.py`, the following rules apply:
- General Python rules (50)
- Database rules (60)
- Testing rules (80) if in test environment

### Test Files
When working on `tests/test_services.py`, the following rules apply:
- General Python rules (50)
- Testing rules (80)
- Debugging rules (30) if in development

## Rule Enforcement

Windsurf enforces these rules through:

1. **Real-time analysis** - As you type
2. **Code completion** - Context-aware suggestions
3. **Error detection** - Immediate feedback on violations
4. **Refactoring assistance** - Automated fixes where possible
5. **Documentation generation** - Auto-generate from code

## Getting Help

For help with specific rules:

1. Check the relevant rule file in this directory
2. Review the main `.windsurfrules` file for general standards
3. Consult the `config.toml` for rule application logic
4. Check the project documentation for implementation examples
