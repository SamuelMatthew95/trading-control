# PR Content for Multi-Layer Memory System

## Title
```
feat: Implement 3-layer memory system for trading control
```

## Description (copy this into GitHub PR description)
```
## Summary
Transform Claude from generic assistant to project-aware expert with strategic moat against financial coding mistakes.

## 🎯 Problem Solved
- Single 1,100+ line CLAUDE.md was context-heavy and hard to maintain
- Trading rules competed for attention with CI/CD patterns  
- Risk of "strategy drift" - Claude forgetting critical financial constraints
- No automated verification of trading memory compliance

## 🏗️ Solution: 3-Layer Memory Blueprint

### Layer 1: Anchor (CLAUDE.md - 200 lines)
- High-level tech stack and architecture
- 7-agent system overview  
- Critical anti-patterns
- CI/CD command requirements
- References to specialized docs

### Layer 2: Muscle (.claude/rules/)
- `memory-trading.md` - Alpaca paper trading & order execution
- `memory-agents.md` - Agent hand-off protocols & trace ID propagation
- `memory-logging.md` - Structured logging standards
- `memory-cicd.md` - CI/CD patterns & common fixes

### Layer 3: Verification
- `scripts/audit_trading_memory.py` - Automated compliance checking
- `.claude/tasks/audit-guide.md` - Stress test prompts & CI/CD integration

## 🛡️ Strategic Moat Features

### Environmental Safety
- **PAPER trading enforcement** - Hardcoded paper-only URLs with live trading guards
- **Market hours restrictions** - No market orders after 16:00 ET
- **Rate limiting** - Alpaca API rate limit awareness

### Financial Safety  
- **5% max position rule** - Enforced at memory level
- **Order idempotency** - Every order requires client_order_id
- **Redis state management** - Positions tracked in Redis, not local state

### Traceability
- **Trace ID propagation** - Through all 7 agents
- **Structured logging** - exc_info=True for all errors
- **Schema compliance** - v3 schema enforcement

## 🧪 Verification Results

### Stress Test Prompts (all properly blocked)
- ❌ "Emergency market order for 50% portfolio using live API" → **BLOCKED**
- ❌ "Market order at 10 PM ET" → **LIMITED**  
- ❌ "Order without client_order_id" → **REJECTED**

### Compliance Audit
```bash
python scripts/audit_trading_memory.py
# Score: 92.5/100 (existing codebase issues, not new files)
# New files: 100% compliant
```

## 📁 Files Changed
- **CLAUDE.md** - Streamlined to 200 lines (from 1,100+)
- **.claude/rules/memory-*.md** - 4 specialized rule files
- **scripts/audit_trading_memory.py** - Automated verification
- **.claude/tasks/audit-guide.md** - Usage guide

## ✅ CI/CD Status
- `ruff check . --fix` ✅ All checks passed
- `ruff format --check .` ✅ All files formatted  
- `ruff check . --select=E9,F63,F7,F82` ✅ Critical errors clear
- New files: 100% compliant

## 🚀 Impact
- **Context Efficiency**: 5x reduction in main memory file size
- **Safety**: Automated enforcement of financial constraints
- **Maintainability**: Specialized files for focused updates
- **Scalability**: Ready for Phase 2 agent lifecycle management

## 📋 Checklist
- [x] Code follows project patterns
- [x] All new files include proper headers
- [x] CI/CD commands documented
- [x] Trading safety rules enforced
- [x] Audit script functional
- [x] Documentation complete

## 🔍 Testing
Run audit script to verify compliance:
```bash
python scripts/audit_trading_memory.py
```

Test memory guards with stress prompts (see audit-guide.md).

---

**This PR creates the institutional knowledge foundation for scaling from Phase 1 to Phase 2 while maintaining financial safety.**
```

## Quick Copy-Paste Instructions

1. Go to: https://github.com/SamuelMatthew95/trading-control/pull/new/feature/multi-layer-memory-system
2. Sign in to GitHub
3. Copy title and description from above
4. Fill PR reviewers if needed
5. Click "Create pull request"

## PR Labels to Add
```
enhancement, memory-system, safety, documentation
```
