# Claude Skills Project Constitution

## Overview
This document defines the principles and structure for refactoring the OpenClaw Trading Control Platform to align with Claude Skills architecture patterns.

## Required Folder Structure

### Mandatory Structure
```
skill-name/
├── SKILL.md          # Required: Main skill definition with YAML frontmatter
├── scripts/          # Optional: Executable code and implementations
├── references/       # Optional: Documentation and reference materials
└── assets/          # Optional: Static assets, images, templates
```

### Critical Rules
- **Folder Naming**: MUST be `kebab-case` (lowercase with hyphens)
- **Main File**: MUST be named `SKILL.md` (case-sensitive)
- **Forbidden Files**: NO `README.md` files in skill folders
- **YAML Security**: Frontmatter MUST NOT contain XML angle brackets (`< >`)

## YAML Frontmatter Requirements

### Required Format
```yaml
---
name: Skill Name
description: Clear description of what the skill does
---
```

### Security Constraints
- NO XML angle brackets in frontmatter
- Proper YAML syntax only
- Must be at the very top of SKILL.md

## Design Principles

### 3-Level Progressive Disclosure
1. **Level 1**: High-level overview and purpose
2. **Level 2**: Implementation details and patterns
3. **Level 3**: Technical specifics and code examples

### Design Approaches

#### Pattern-First Approach
- Start with user interaction patterns
- Define workflows and user journeys
- Implement tools to support patterns

#### Tool-First Approach
- Start with available tools and capabilities
- Build patterns around tool combinations
- Focus on technical capabilities

## OpenClaw Trading Platform - Skill Mapping

### Current Code Analysis
- **Core Logic**: `orchestrator.py`, `tools.py`, `agents/`
- **API Layer**: `api/`, `routes/`
- **Data Management**: `memory.py`, `tasks.py`
- **Configuration**: `config.py`, `main.py`

### Potential Skill Categories

#### 1. Market Analysis Skill
- Purpose: Real-time market data analysis and technical indicators
- Current Location: `tools.py` (market-related tools)
- Target Structure: `market-analysis/`

#### 2. Agent Coordination Skill
- Purpose: Multi-agent communication and consensus building
- Current Location: `orchestrator.py`, `agent/`
- Target Structure: `agent-coordination/`

#### 3. Trading Strategy Skill
- Purpose: Strategy execution and trade management
- Current Location: `tools.py` (trading tools)
- Target Structure: `trading-strategy/`

#### 4. System Monitoring Skill
- Purpose: Health monitoring and performance metrics
- Current Location: `monitoring/`, `observability/`
- Target Structure: `system-monitoring/`

## Refactoring Strategy

### Phase 1: Analysis
- Identify cohesive logic blocks
- Map current files to skill categories
- Define skill boundaries and interfaces

### Phase 2: Structure Creation
- Create skill directories with proper naming
- Set up SKILL.md files with correct frontmatter
- Establish scripts/references/assets subdirectories

### Phase 3: Logic Migration
- Move relevant code to appropriate skill folders
- Update imports and dependencies
- Maintain backward compatibility

### Phase 4: Validation
- Test all functionality remains intact
- Verify import paths are correct
- Ensure skill independence

## Implementation Guidelines

### Code Organization
- **scripts/**: Contains executable Python code
- **references/**: Contains documentation, API specs, architectural notes
- **assets/**: Contains configuration files, templates, static resources

### Import Management
- Use relative imports within skills
- Maintain clear interfaces between skills
- Avoid circular dependencies

### Testing Strategy
- Preserve existing test structure
- Add skill-specific tests where needed
- Maintain test coverage requirements

## Quality Standards

### Code Quality
- Follow existing PEP 8 standards
- Maintain type annotations
- Preserve docstring formats

### Documentation
- Update SKILL.md with clear descriptions
- Include usage examples
- Document interfaces and dependencies

### Security
- No hardcoded secrets in skill files
- Proper environment variable usage
- Follow existing security patterns
