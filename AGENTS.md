# AGENTS.md - Production-Grade Agent Governance Constitution

## Overview

This constitution defines the strict governance rules for the high-scale trading agent system. All agent development and deployment must comply with these rules to ensure system reliability, scalability, and maintainability.

## Core Principles

### 1. Intelligence in Orchestration, Dumbness in Agents
- **Agents are stateless workers** - No internal state, no memory between executions
- **Narrow scope** - Each agent has one specific responsibility
- **Deterministic behavior** - Same input always produces same output
- **No business logic** - All reasoning lives in the supervisor orchestrator

### 2. 5-Agent Ceiling Enforcement
- **Maximum concurrent agents**: 5 per workflow
- **Hierarchical supervision** for complex tasks requiring more agents
- **Load balancing** enforced by supervisor
- **Resource limits** strictly enforced

### 3. Explicit State Management
- **No context window reliance** - Never use LLM memory
- **External state stores** - All state in databases/key-value stores
- **State snapshots** - Complete workflow state at each step
- **Deterministic replay** - Any workflow can be replayed exactly

## Agent Architecture Rules

### Agent Structure Requirements

```python
# Every agent must follow this structure:
class AgentName:
    def __init__(self):
        self.agent_id = "agent_name_worker"
        self.version = "1.0.0"
        # NO INTERNAL STATE ALLOWED
    
    async def execute(self, input_contract: InputModel) -> OutputModel:
        # Deterministic transformation only
        # No business logic or reasoning
        # Strict error handling with structured outputs
        pass
```

### Mandatory Components

#### Input/Output Contracts
- **Pydantic models** required for all I/O
- **JSON schemas** auto-generated from models
- **Strict validation** - no malformed data allowed
- **Versioned contracts** - backward compatibility enforced

#### Agent Metadata
```python
AGENT_METADATA = {
    "agent_id": "agent_name_worker",
    "version": "1.0.0",
    "scope": "specific_task_only",
    "stateless": True,
    "input_contract": "InputModel",
    "output_contract": "OutputModel",
    "permissions": ["specific_permissions_only"],
    "max_execution_time_ms": 5000,
    "retry_count": 2
}
```

### Forbidden Patterns

#### ❌ Anti-Patterns
- **Internal state storage** (no self.state = {})
- **Context window memory** (no "remember previous requests")
- **Business logic** (no if/else based on business rules)
- **Natural language outputs** (only structured data)
- **Database connections** (handled by supervisor)
- **Agent-to-agent communication** (only via supervisor)

#### ✅ Required Patterns
- **Pure functions** (same input → same output)
- **Structured error handling** (ValidationError, not Exception)
- **Input validation** (Pydantic models enforce this)
- **Performance monitoring** (execution time tracking)
- **Deterministic algorithms** (no randomness unless seeded)

## Supervisor Orchestrator Rules

### Workflow Design
- **Deterministic graphs** - No conditional branching based on LLM
- **Explicit state transitions** - Every step recorded
- **Error boundaries** - Each agent task isolated
- **Retry logic** - Handled by supervisor, not agents

### Decision Points
- **All decisions recorded** with reasoning
- **Confidence scoring** required for all decisions
- **Alternative paths tracked** for debugging
- **Business logic encapsulated** in supervisor only

### Performance Requirements
- **5-agent ceiling** strictly enforced
- **Execution time limits** per agent
- **Memory usage monitoring**
- **Concurrent workflow limits**

## I/O Contract Standards

### Input Contracts
```python
class StandardInput(BaseModel):
    # Required fields with validation
    required_field: str = Field(..., description="Required field")
    
    # Optional fields with defaults
    optional_field: int = Field(default=100, description="Optional field")
    
    # Strict type validation
    timestamp: datetime = Field(..., description="Event timestamp")
    
    @validator('required_field')
    def validate_field(cls, v):
        if len(v) < 3:
            raise ValueError('Field too short')
        return v
```

### Output Contracts
```python
class StandardOutput(BaseModel):
    success: bool = Field(..., description="Operation success")
    data: Dict[str, Any] = Field(..., description="Result data")
    errors: List[ErrorModel] = Field(default_factory=list, description="Errors")
    execution_time_ms: int = Field(..., description="Execution time")
    
    @validator('execution_time_ms')
    def validate_time(cls, v):
        if v < 0:
            raise ValueError('Execution time cannot be negative')
        return v
```

### Error Handling
- **Structured errors only** - No exception messages
- **Error categorization** - critical, warning, info
- **Retry indicators** - Should this error trigger retry
- **Context preservation** - Error includes full input context

## Observability Requirements

### Mandatory Tracing
- **Workflow start/end** events
- **Agent task start/end** events
- **Decision point** events with reasoning
- **Performance metrics** events
- **Error events** with full context

### Trace Data Structure
```python
{
    "workflow_id": "uuid",
    "correlation_id": "uuid", 
    "timestamp": "ISO datetime",
    "event_type": "agent_task_start|decision_point|error",
    "agent_id": "agent_name_worker",
    "input_data": {...},
    "output_data": {...},
    "execution_time_ms": 123,
    "reasoning": "Why this decision was made"
}
```

### Performance Monitoring
- **Agent execution time** tracked per agent
- **Workflow duration** tracked end-to-end
- **Error rates** calculated per agent/workflow
- **Resource utilization** monitored in real-time

## Security and Permissions

### Agent Permissions
```python
PERMISSION_LEVELS = {
    "read_market_data": ["market_data_worker"],
    "validate_data": ["data_validation_worker"],
    "analyze_technical": ["technical_analysis_worker"],
    "write_results": ["supervisor_orchestrator"],
    "access_database": ["supervisor_orchestrator"]
}
```

### Access Control
- **Principle of least privilege** - Agents get minimum required permissions
- **Permission auditing** - All access logged and auditable
- **Credential isolation** - No shared credentials between agents
- **Network segmentation** - Agents can only access required services

## Testing and Validation

### Unit Tests
- **Contract validation** - All I/O contracts tested
- **Deterministic behavior** - Same input produces same output
- **Error handling** - All error paths tested
- **Performance limits** - Execution time limits enforced

### Integration Tests
- **Workflow testing** - Complete workflows tested
- **Agent coordination** - Supervisor-agent interactions tested
- **Error recovery** - Failure scenarios tested
- **Load testing** - Performance under load tested

### Golden Tasks
- **Standardized test cases** - Known inputs/outputs
- **Regression testing** - Every change validated against golden tasks
- **Performance baselines** - Execution time baselines enforced
- **Quality gates** - No deployment without passing tests

## Deployment and Operations

### Version Management
- **Semantic versioning** - Major.Minor.Patch
- **Backward compatibility** - Maintained for minor versions
- **Contract versioning** - I/O contracts versioned separately
- **Rollback capability** - Instant rollback to previous version

### Monitoring and Alerting
- **Health checks** - Agent and supervisor health monitored
- **Performance alerts** - Degradation triggers alerts
- **Error rate alerts** - High error rates trigger incidents
- **Resource alerts** - Memory/CPU usage monitored

### Scaling Policies
- **Horizontal scaling** - More supervisor instances for load
- **Agent pool sizing** - Based on workload patterns
- **Auto-scaling rules** - Defined scaling triggers and limits
- **Capacity planning** - Resource requirements documented

## Compliance and Auditing

### Audit Requirements
- **Complete traceability** - Every decision auditable
- **Data lineage** - All data transformations tracked
- **Access logging** - All agent access logged
- **Change management** - All changes tracked and approved

### Regulatory Compliance
- **Data privacy** - No sensitive data in agent memory
- **Financial regulations** - Trading rules enforced
- **Record retention** - All traces retained for required period
- **Reporting** - Compliance reports generated automatically

## Enforcement Mechanisms

### Automated Validation
- **Contract validation** - Pydantic enforces I/O contracts
- **Architecture compliance** - Static analysis checks patterns
- **Performance monitoring** - Automated alerts for violations
- **Security scanning** - Automated permission validation

### Manual Review Process
- **Code review** - All agent changes reviewed
- **Architecture review** - Design changes reviewed
- **Security review** - Permission changes reviewed
- **Performance review** - Performance changes reviewed

### Violation Consequences
- **Block deployment** - Non-compliant code blocked
- **Automatic rollback** - Violating changes rolled back
- **Incident response** - Security violations trigger incidents
- **Performance degradation** - Violations trigger scaling issues

## Evolution and Maintenance

### Constitution Updates
- **Version control** - All changes tracked
- **Review process** - Changes reviewed by architecture team
- **Impact analysis** - Effects of changes analyzed
- **Communication** - Changes communicated to all teams

### Continuous Improvement
- **Metrics analysis** - System performance analyzed
- **Pattern identification** - Best practices identified
- **Rule refinement** - Rules refined based on experience
- **Technology updates** - New technologies evaluated

---

## Compliance Checklist

Before deploying any agent or workflow change, verify:

- [ ] Agent is completely stateless
- [ ] I/O contracts use Pydantic models
- [ ] No business logic in agents
- [ ] All decisions recorded with reasoning
- [ ] Performance limits enforced
- [ ] Error handling is structured
- [ ] Observability tracing implemented
- [ ] Permissions follow principle of least privilege
- [ ] Tests cover all scenarios
- [ ] Golden tasks pass
- [ ] Security review completed
- [ ] Architecture review completed

**Non-compliance will result in deployment block and immediate rollback.**
