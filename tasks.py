"""
Task Model - Explicit Task Contracts for OpenClaw
Structured execution contracts with no dynamic string-based routing
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

# ============================================================================
# EXPLICIT TASK TYPE ENUM
# ============================================================================


class TaskType(Enum):
    """Explicit task types for deterministic routing - NO DYNAMIC STRINGS"""

    # MARKET ANALYSIS TASKS
    SCAN_MARKET = "scan_market"
    ANALYZE_SYMBOL = "analyze_symbol"
    GENERATE_SIGNAL = "generate_signal"

    # TECHNICAL ANALYSIS TASKS
    CALCULATE_RSI = "calculate_rsi"
    CALCULATE_MACD = "calculate_macd"
    CALCULATE_BOLLINGER = "calculate_bollinger"
    CALCULATE_MOVING_AVERAGE = "calculate_moving_average"
    CALCULATE_VOLATILITY = "calculate_volatility"

    # FUNDAMENTAL ANALYSIS TASKS
    ANALYZE_FUNDAMENTALS = "analyze_fundamentals"
    VALUATION_DCF = "valuation_dcf"
    VALUATION_PE = "valuation_pe"
    INDUSTRY_COMPARISON = "industry_comparison"
    EARNINGS_ANALYSIS = "earnings_analysis"

    # SENTIMENT ANALYSIS TASKS
    ANALYZE_SENTIMENT = "analyze_sentiment"
    ANALYZE_NEWS_SENTIMENT = "analyze_news_sentiment"
    ANALYZE_SOCIAL_SENTIMENT = "analyze_social_sentiment"
    MARKET_SENTIMENT = "market_sentiment"

    # RISK MANAGEMENT TASKS
    ASSESS_RISK = "assess_risk"
    CALCULATE_POSITION_SIZE = "calculate_position_size"
    VALIDATE_SIGNAL = "validate_signal"
    CALCULATE_STOP_LOSS = "calculate_stop_loss"

    # PERFORMANCE & LEARNING TASKS
    GRADE_TRADE = "grade_trade"
    ANALYZE_PERFORMANCE = "analyze_performance"
    CALIBRATE_CONFIDENCE = "calibrate_confidence"
    LEARN_FROM_FEEDBACK = "learn_from_feedback"

    # VALIDATION TASKS
    VALIDATE_DATA = "validate_data"
    DETECT_ANOMALIES = "detect_anomalies"
    CROSS_VALIDATE = "cross_validate"

    # SYSTEM TASKS
    HEALTH_CHECK = "health_check"
    PERFORMANCE_REPORT = "performance_report"
    CLEANUP = "cleanup"
    BACKUP = "backup"


# ============================================================================
# TASK PRIORITY ENUM
# ============================================================================


class TaskPriority(Enum):
    """Task priority levels"""

    LOW = 1
    MEDIUM = 2
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4
    URGENT = 5


# ============================================================================
# TASK STATUS ENUM
# ============================================================================


class TaskStatus(Enum):
    """Task execution status"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ============================================================================
# DATA MODELS
# ============================================================================


@dataclass(frozen=True)
class TaskInput:
    """Structured task input with validation"""

    task_type: TaskType
    parameters: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> bool:
        """Validate input against constraints"""
        for param, constraint in self.constraints.items():
            if param not in self.parameters:
                return False

            value = self.parameters[param]

            # Type validation
            if "type" in constraint:
                expected_type = constraint["type"]
                if expected_type == "str" and not isinstance(value, str):
                    return False
                elif expected_type == "int" and not isinstance(value, int):
                    return False
                elif expected_type == "float" and not isinstance(value, (int, float)):
                    return False
                elif expected_type == "list" and not isinstance(value, list):
                    return False
                elif expected_type == "dict" and not isinstance(value, dict):
                    return False

            # Range validation
            if "min" in constraint and value < constraint["min"]:
                return False
            if "max" in constraint and value > constraint["max"]:
                return False
            if "enum" in constraint and value not in constraint["enum"]:
                return False

        return True


@dataclass(frozen=True)
class TaskOutput:
    """Structured task output with validation"""

    task_type: TaskType
    result: Dict[str, Any]
    confidence: float  # 0.0 to 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time_ms: float = 0.0
    tokens_used: int = 0
    cost_usd: float = 0.0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def validate(self) -> bool:
        """Validate output structure"""
        # Basic validation
        if not 0.0 <= self.confidence <= 1.0:
            return False
        if self.execution_time_ms < 0:
            return False
        if self.tokens_used < 0:
            return False
        if self.cost_usd < 0:
            return False

        # Task-specific validation
        if self.task_type == TaskType.GENERATE_SIGNAL:
            required_fields = [
                "ticker",
                "direction",
                "entry",
                "stop_loss",
                "take_profit",
                "reasoning",
            ]
            for field in required_fields:
                if field not in self.result:
                    return False

        return True


@dataclass(frozen=True)
class Task:
    """Explicit task with structured contract"""

    task_id: str
    task_type: TaskType
    input: TaskInput
    priority: TaskPriority
    status: TaskStatus
    timeout_seconds: int
    created_at: datetime
    scheduled_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    assigned_agent: Optional[str]
    parent_task_id: Optional[str]
    child_task_ids: List[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    trace_id: Optional[str] = None

    def __post_init__(self):
        """Generate trace_id if not provided"""
        if self.trace_id is None:
            # This would normally be handled by the dataclass __init__
            # but since it's frozen, we need to ensure it's set
            object.__setattr__(self, "trace_id", str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "input": {
                "task_type": self.input.task_type.value,
                "parameters": self.input.parameters,
                "metadata": self.input.metadata,
                "constraints": self.input.constraints,
            },
            "priority": self.priority.value,
            "status": self.status.value,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at.isoformat(),
            "scheduled_at": (
                self.scheduled_at.isoformat() if self.scheduled_at else None
            ),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "assigned_agent": self.assigned_agent,
            "parent_task_id": self.parent_task_id,
            "child_task_ids": self.child_task_ids,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Create Task from dictionary"""
        return cls(
            task_id=data["task_id"],
            task_type=TaskType(data["task_type"]),
            input=TaskInput(
                task_type=TaskType(data["input"]["task_type"]),
                parameters=data["input"]["parameters"],
                metadata=data["input"]["metadata"],
                constraints=data["input"]["constraints"],
            ),
            priority=TaskPriority(data["priority"]),
            status=TaskStatus(data["status"]),
            timeout_seconds=data["timeout_seconds"],
            created_at=datetime.fromisoformat(data["created_at"]),
            scheduled_at=(
                datetime.fromisoformat(data["scheduled_at"])
                if data.get("scheduled_at")
                else None
            ),
            started_at=(
                datetime.fromisoformat(data["started_at"])
                if data.get("started_at")
                else None
            ),
            completed_at=(
                datetime.fromisoformat(data["completed_at"])
                if data.get("completed_at")
                else None
            ),
            assigned_agent=data.get("assigned_agent"),
            parent_task_id=data.get("parent_task_id"),
            child_task_ids=data.get("child_task_ids", []),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            trace_id=data.get("trace_id"),
        )


@dataclass(frozen=True)
class TaskResult:
    """Task execution result"""

    task_id: str
    task_type: TaskType
    status: TaskStatus
    output: Optional[TaskOutput]
    error_message: Optional[str]
    execution_time_ms: float
    tokens_used: int
    cost_usd: float
    agent_id: str
    trace_id: str
    started_at: datetime
    completed_at: datetime
    retry_count: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "status": self.status.value,
            "output": self.output.to_dict() if self.output else None,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "agent_id": self.agent_id,
            "trace_id": self.trace_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "retry_count": self.retry_count,
        }


# ============================================================================
# LEGACY COMPATIBILITY CLASSES (for test compatibility)
# ============================================================================


@dataclass(frozen=True)
class AgentTask:
    """Legacy AgentTask class for backward compatibility"""

    task_id: str
    task_type: TaskType
    input_data: Dict[str, Any]
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    timeout_seconds: int = 60
    max_retries: int = 3
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    assigned_agent: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "input_data": self.input_data,
            "priority": self.priority.value,
            "status": self.status.value,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "assigned_agent": self.assigned_agent,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class AgentResult:
    """Legacy AgentResult class for backward compatibility"""

    task_id: str
    agent_id: str
    success: bool
    output_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    execution_time_ms: float = 0.0
    tokens_used: int = 0
    cost_usd: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "success": self.success,
            "output_data": self.output_data,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "metrics": self.metrics,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
        }


# ============================================================================
# TASK CONTRACTS (VALIDATION SCHEMAS)
# ============================================================================


class TaskContracts:
    """Task contract definitions with validation schemas"""

    @staticmethod
    def get_contract(task_type: TaskType) -> Dict[str, Any]:
        """Get task contract for a task type"""
        contracts = {
            TaskType.SCAN_MARKET: {
                "description": "Scan market for trading opportunities",
                "required_parameters": ["symbols"],
                "optional_parameters": {
                    "scan_type": "technical",
                    "timeframe": "1d",
                    "filter_criteria": {},
                },
                "parameter_constraints": {
                    "symbols": {"type": "list", "min_length": 1, "max_length": 100}
                },
                "output_schema": {
                    "required_fields": [
                        "scanned_symbols",
                        "market_status",
                        "opportunities",
                    ],
                    "confidence_required": False,
                },
            },
            TaskType.ANALYZE_SYMBOL: {
                "description": "Analyze a specific symbol",
                "required_parameters": ["symbol"],
                "optional_parameters": {
                    "timeframe": "1d",
                    "indicators": ["rsi", "macd", "bollinger"],
                    "fundamentals": False,
                },
                "parameter_constraints": {
                    "symbol": {
                        "type": "str",
                        "min_length": 1,
                        "max_length": 10,
                        "pattern": "^[A-Z0-9.]+$",
                    }
                },
                "output_schema": {
                    "required_fields": ["symbol", "analysis", "indicators"],
                    "confidence_required": True,
                },
            },
            TaskType.GENERATE_SIGNAL: {
                "description": "Generate trading signal",
                "required_parameters": ["symbol", "analysis_data"],
                "optional_parameters": {
                    "signal_type": "directional",
                    "risk_tolerance": "medium",
                },
                "parameter_constraints": {
                    "symbol": {"type": "str", "min_length": 1, "max_length": 10},
                    "analysis_data": {"type": "dict"},
                },
                "output_schema": {
                    "required_fields": [
                        "ticker",
                        "direction",
                        "entry",
                        "stop_loss",
                        "take_profit",
                        "confidence",
                        "reasoning",
                    ],
                    "confidence_required": True,
                },
            },
            TaskType.VALIDATE_SIGNAL: {
                "description": "Validate trading signal",
                "required_parameters": ["signal"],
                "optional_parameters": {
                    "validation_level": "standard",
                    "risk_checks": True,
                },
                "parameter_constraints": {"signal": {"type": "dict"}},
                "output_schema": {
                    "required_fields": ["valid", "validation_score", "issues"],
                    "confidence_required": True,
                },
            },
            TaskType.CALCULATE_RSI: {
                "description": "Calculate RSI indicator",
                "required_parameters": ["prices"],
                "optional_parameters": {"period": 14, "overbought": 70, "oversold": 30},
                "parameter_constraints": {
                    "prices": {"type": "list", "min_length": 15},
                    "period": {"type": "int", "min": 2, "max": 100},
                },
                "output_schema": {
                    "required_fields": ["rsi", "signal", "values"],
                    "confidence_required": True,
                },
            },
            TaskType.CALCULATE_MACD: {
                "description": "Calculate MACD indicator",
                "required_parameters": ["prices"],
                "optional_parameters": {
                    "fast_period": 12,
                    "slow_period": 26,
                    "signal_period": 9,
                },
                "parameter_constraints": {"prices": {"type": "list", "min_length": 26}},
                "output_schema": {
                    "required_fields": ["macd", "signal", "histogram"],
                    "confidence_required": True,
                },
            },
            TaskType.ANALYZE_FUNDAMENTALS: {
                "description": "Analyze fundamental data",
                "required_parameters": ["symbol"],
                "optional_parameters": {
                    "metrics": ["pe_ratio", "roe", "debt_to_equity"],
                    "period": "quarterly",
                },
                "parameter_constraints": {
                    "symbol": {"type": "str", "min_length": 1, "max_length": 10}
                },
                "output_schema": {
                    "required_fields": ["symbol", "fundamentals", "valuation"],
                    "confidence_required": True,
                },
            },
            TaskType.ANALYZE_SENTIMENT: {
                "description": "Analyze market sentiment",
                "required_parameters": ["symbol"],
                "optional_parameters": {
                    "sources": ["news", "social"],
                    "timeframe": "7d",
                },
                "parameter_constraints": {
                    "symbol": {"type": "str", "min_length": 1, "max_length": 10}
                },
                "output_schema": {
                    "required_fields": ["symbol", "sentiment", "sources"],
                    "confidence_required": True,
                },
            },
            TaskType.ASSESS_RISK: {
                "description": "Assess trading risk",
                "required_parameters": ["signal"],
                "optional_parameters": {"risk_model": "standard", "timeframe": "1d"},
                "parameter_constraints": {"signal": {"type": "dict"}},
                "output_schema": {
                    "required_fields": ["risk_score", "risk_level", "factors"],
                    "confidence_required": True,
                },
            },
            TaskType.GRADE_TRADE: {
                "description": "Grade completed trade",
                "required_parameters": ["trade_id"],
                "optional_parameters": {
                    "grading_model": "standard",
                    "include_recommendations": True,
                },
                "parameter_constraints": {"trade_id": {"type": "str"}},
                "output_schema": {
                    "required_fields": ["grade", "scores", "recommendations"],
                    "confidence_required": True,
                },
            },
        }

        return contracts.get(
            task_type,
            {
                "description": f"Unknown task type: {task_type.value}",
                "required_parameters": [],
                "optional_parameters": {},
                "parameter_constraints": {},
                "output_schema": {"required_fields": [], "confidence_required": False},
            },
        )

    @staticmethod
    def validate_task_input(task_type: TaskType, parameters: Dict[str, Any]) -> bool:
        """Validate task input against contract"""
        contract = TaskContracts.get_contract(task_type)

        # Check required parameters
        for param in contract["required_parameters"]:
            if param not in parameters:
                return False

        # Check parameter constraints
        for param, constraint in contract["parameter_constraints"].items():
            if param in parameters:
                value = parameters[param]

                # Type validation
                if "type" in constraint:
                    expected_type = constraint["type"]
                    if expected_type == "str" and not isinstance(value, str):
                        return False
                    elif expected_type == "int" and not isinstance(value, int):
                        return False
                    elif expected_type == "float" and not isinstance(
                        value, (int, float)
                    ):
                        return False
                    elif expected_type == "list" and not isinstance(value, list):
                        return False
                    elif expected_type == "dict" and not isinstance(value, dict):
                        return False

                # Range validation
                if "min_length" in constraint and len(value) < constraint["min_length"]:
                    return False
                if "max_length" in constraint and len(value) > constraint["max_length"]:
                    return False
                if "min" in constraint and value < constraint["min"]:
                    return False
                if "max" in constraint and value > constraint["max"]:
                    return False
                if "pattern" in constraint:
                    import re

                    if not re.match(constraint["pattern"], value):
                        return False

        return True

    @staticmethod
    def validate_task_output(task_type: TaskType, output: Dict[str, Any]) -> bool:
        """Validate task output against contract"""
        contract = TaskContracts.get_contract(task_type)

        # Check required fields
        for field in contract["output_schema"]["required_fields"]:
            if field not in output:
                return False

        # Check confidence requirement
        if contract["output_schema"]["confidence_required"]:
            if "confidence" not in output or not isinstance(
                output["confidence"], (int, float)
            ):
                return False
            if not 0.0 <= output["confidence"] <= 1.0:
                return False

        return True


# ============================================================================
# TASK FACTORY
# ============================================================================


class TaskFactory:
    """Factory for creating standardized tasks"""

    def __init__(self):
        self.task_creators = {
            task_type: self._create_generic_task for task_type in TaskType
        }

    def create_task(self, task_type: TaskType, input_data: Dict[str, Any]) -> AgentTask:
        """Create a task of the specified type"""
        if task_type not in self.task_creators:
            raise ValueError(f"Unknown task type: {task_type}")

        if not isinstance(input_data, dict):
            raise TypeError(f"Input data must be a dictionary, got {type(input_data)}")

        if input_data is None:
            raise ValueError("Input data cannot be None")

        # Check for empty dict (missing required fields)
        if not input_data:
            raise ValueError("Input data cannot be empty")

        return self.task_creators[task_type](task_type, input_data)

    def get_supported_task_types(self) -> List[TaskType]:
        """Get list of supported task types"""
        return list(self.task_creators.keys())

    def _create_generic_task(
        self, task_type: TaskType, input_data: Dict[str, Any]
    ) -> AgentTask:
        """Create a generic task"""
        return AgentTask(
            task_id=f"task_{task_type.value}_{uuid.uuid4().hex[:8]}",
            task_type=task_type,
            input_data=input_data,
        )

    @staticmethod
    def create_market_scan_task(
        symbols: List[str], priority: TaskPriority = TaskPriority.NORMAL
    ) -> Task:
        """Create market scanning task"""
        return Task(
            task_id=str(uuid.uuid4()),
            task_type=TaskType.SCAN_MARKET,
            input=TaskInput(
                task_type=TaskType.SCAN_MARKET,
                parameters={"symbols": symbols},
                constraints=TaskContracts.get_contract(TaskType.SCAN_MARKET)[
                    "parameter_constraints"
                ],
            ),
            priority=priority,
            status=TaskStatus.PENDING,
            timeout_seconds=600,  # 10 minutes
            created_at=datetime.now(),
        )

    @staticmethod
    def create_symbol_analysis_task(
        symbol: str, priority: TaskPriority = TaskPriority.NORMAL
    ) -> Task:
        """Create symbol analysis task"""
        return Task(
            task_id=str(uuid.uuid4()),
            task_type=TaskType.ANALYZE_SYMBOL,
            input=TaskInput(
                task_type=TaskType.ANALYZE_SYMBOL,
                parameters={"symbol": symbol},
                constraints=TaskContracts.get_contract(TaskType.ANALYZE_SYMBOL)[
                    "parameter_constraints"
                ],
            ),
            priority=priority,
            status=TaskStatus.PENDING,
            timeout_seconds=300,  # 5 minutes
            created_at=datetime.now(),
        )

    @staticmethod
    def create_signal_generation_task(
        symbol: str,
        analysis_data: Dict[str, Any],
        priority: TaskPriority = TaskPriority.HIGH,
    ) -> Task:
        """Create signal generation task"""
        return Task(
            task_id=str(uuid.uuid4()),
            task_type=TaskType.GENERATE_SIGNAL,
            input=TaskInput(
                task_type=TaskType.GENERATE_SIGNAL,
                parameters={"symbol": symbol, "analysis_data": analysis_data},
                constraints=TaskContracts.get_contract(TaskType.GENERATE_SIGNAL)[
                    "parameter_constraints"
                ],
            ),
            priority=priority,
            status=TaskStatus.PENDING,
            timeout_seconds=180,  # 3 minutes
            created_at=datetime.now(),
        )

    @staticmethod
    def create_rsi_calculation_task(
        prices: List[float],
        period: int = 14,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> Task:
        """Create RSI calculation task"""
        return Task(
            task_id=str(uuid.uuid4()),
            task_type=TaskType.CALCULATE_RSI,
            input=TaskInput(
                task_type=TaskType.CALCULATE_RSI,
                parameters={"prices": prices, "period": period},
                constraints=TaskContracts.get_contract(TaskType.CALCULATE_RSI)[
                    "parameter_constraints"
                ],
            ),
            priority=priority,
            status=TaskStatus.PENDING,
            timeout_seconds=60,  # 1 minute
            created_at=datetime.now(),
        )

    @staticmethod
    def create_macd_calculation_task(
        prices: List[float], priority: TaskPriority = TaskPriority.NORMAL
    ) -> Task:
        """Create MACD calculation task"""
        return Task(
            task_id=str(uuid.uuid4()),
            task_type=TaskType.CALCULATE_MACD,
            input=TaskInput(
                task_type=TaskType.CALCULATE_MACD,
                parameters={"prices": prices},
                constraints=TaskContracts.get_contract(TaskType.CALCULATE_MACD)[
                    "parameter_constraints"
                ],
            ),
            priority=priority,
            status=TaskStatus.PENDING,
            timeout_seconds=60,  # 1 minute
            created_at=datetime.now(),
        )

    @staticmethod
    def create_fundamental_analysis_task(
        symbol: str, priority: TaskPriority = TaskPriority.NORMAL
    ) -> Task:
        """Create fundamental analysis task"""
        return Task(
            task_id=str(uuid.uuid4()),
            task_type=TaskType.ANALYZE_FUNDAMENTALS,
            input=TaskInput(
                task_type=TaskType.ANALYZE_FUNDAMENTALS,
                parameters={"symbol": symbol},
                constraints=TaskContracts.get_contract(TaskType.ANALYZE_FUNDAMENTALS)[
                    "parameter_constraints"
                ],
            ),
            priority=priority,
            status=TaskStatus.PENDING,
            timeout_seconds=300,  # 5 minutes
            created_at=datetime.now(),
        )

    @staticmethod
    def create_sentiment_analysis_task(
        symbol: str, sources: List[str], priority: TaskPriority = TaskPriority.NORMAL
    ) -> Task:
        """Create sentiment analysis task"""
        return Task(
            task_id=str(uuid.uuid4()),
            task_type=TaskType.ANALYZE_SENTIMENT,
            input=TaskInput(
                task_type=TaskType.ANALYZE_SENTIMENT,
                parameters={"symbol": symbol, "sources": sources},
                constraints=TaskContracts.get_contract(TaskType.ANALYZE_SENTIMENT)[
                    "parameter_constraints"
                ],
            ),
            priority=priority,
            status=TaskStatus.PENDING,
            timeout_seconds=240,  # 4 minutes
            created_at=datetime.now(),
        )

    @staticmethod
    def create_risk_assessment_task(
        signal_data: Dict[str, Any], priority: TaskPriority = TaskPriority.HIGH
    ) -> Task:
        """Create risk assessment task"""
        return Task(
            task_id=str(uuid.uuid4()),
            task_type=TaskType.ASSESS_RISK,
            input=TaskInput(
                task_type=TaskType.ASSESS_RISK,
                parameters={"signal_data": signal_data},
                constraints=TaskContracts.get_contract(TaskType.ASSESS_RISK)[
                    "parameter_constraints"
                ],
            ),
            priority=priority,
            status=TaskStatus.PENDING,
            timeout_seconds=120,  # 2 minutes
            created_at=datetime.now(),
        )

    @staticmethod
    def create_trade_grading_task(
        trade_id: str, priority: TaskPriority = TaskPriority.NORMAL
    ) -> Task:
        """Create trade grading task"""
        return Task(
            task_id=str(uuid.uuid4()),
            task_type=TaskType.GRADE_TRADE,
            input=TaskInput(
                task_type=TaskType.GRADE_TRADE,
                parameters={"trade_id": trade_id},
                constraints=TaskContracts.get_contract(TaskType.GRADE_TRADE)[
                    "parameter_constraints"
                ],
            ),
            priority=priority,
            status=TaskStatus.PENDING,
            timeout_seconds=180,  # 3 minutes
            created_at=datetime.now(),
        )

    @staticmethod
    def create_validation_task(
        data: Dict[str, Any],
        data_type: str = "general",
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> Task:
        """Create data validation task"""
        return Task(
            task_id=str(uuid.uuid4()),
            task_type=TaskType.VALIDATE_DATA,
            input=TaskInput(
                task_type=TaskType.VALIDATE_DATA,
                parameters={"data": data, "data_type": data_type},
                constraints={},
            ),
            priority=priority,
            status=TaskStatus.PENDING,
            timeout_seconds=60,  # 1 minute
            created_at=datetime.now(),
        )


# ============================================================================
# TASK ROUTER (DETERMINISTIC)
# ============================================================================


class TaskRouter:
    """Deterministic task-to-agent routing - NO DYNAMIC STRINGS"""

    # Explicit routing mapping
    ROUTING_MAP = {
        # Market Analysis Tasks
        TaskType.SCAN_MARKET: ["technical_analyst", "business_analyst"],
        TaskType.ANALYZE_SYMBOL: ["technical_analyst"],
        TaskType.GENERATE_SIGNAL: ["technical_analyst"],
        TaskType.VALIDATE_SIGNAL: ["risk_analyst", "technical_analyst"],
        # Technical Analysis Tasks
        TaskType.CALCULATE_RSI: ["technical_analyst"],
        TaskType.CALCULATE_MACD: ["technical_analyst"],
        TaskType.CALCULATE_BOLLINGER: ["technical_analyst"],
        TaskType.CALCULATE_MOVING_AVERAGE: ["technical_analyst"],
        TaskType.CALCULATE_VOLATILITY: ["technical_analyst"],
        # Fundamental Analysis Tasks
        TaskType.ANALYZE_FUNDAMENTALS: ["business_analyst"],
        TaskType.VALUATION_DCF: ["business_analyst"],
        TaskType.VALUATION_PE: ["business_analyst"],
        TaskType.INDUSTRY_COMPARISON: ["business_analyst"],
        TaskType.EARNINGS_ANALYSIS: ["business_analyst"],
        # Sentiment Analysis Tasks
        TaskType.ANALYZE_SENTIMENT: ["sentiment_analyst"],
        TaskType.ANALYZE_NEWS_SENTIMENT: ["sentiment_analyst"],
        TaskType.ANALYZE_SOCIAL_SENTIMENT: ["sentiment_analyst"],
        TaskType.MARKET_SENTIMENT: ["sentiment_analyst"],
        # Risk Management Tasks
        TaskType.ASSESS_RISK: ["risk_analyst", "technical_analyst"],
        TaskType.CALCULATE_POSITION_SIZE: ["risk_analyst"],
        TaskType.VALIDATE_SIGNAL: ["risk_analyst", "technical_analyst"],
        TaskType.CALCULATE_STOP_LOSS: ["risk_analyst"],
        # Performance & Learning Tasks
        TaskType.GRADE_TRADE: ["supervisor"],
        TaskType.ANALYZE_PERFORMANCE: ["supervisor"],
        TaskType.CALIBRATE_CONFIDENCE: ["supervisor"],
        TaskType.LEARN_FROM_FEEDBACK: ["supervisor"],
        # Validation Tasks
        TaskType.VALIDATE_DATA: ["validator"],
        TaskType.DETECT_ANOMALIES: ["validator"],
        TaskType.CROSS_VALIDATE: ["validator"],
        # System Tasks
        TaskType.HEALTH_CHECK: ["system_monitor"],
        TaskType.PERFORMANCE_REPORT: ["system_monitor"],
        TaskType.CLEANUP: ["system_monitor"],
        TaskType.BACKUP: ["system_monitor"],
    }

    @classmethod
    def route_task(cls, task_type: TaskType) -> List[str]:
        """Route task to appropriate agent types"""
        return cls.ROUTING_MAP.get(task_type, ["technical_analyst"])  # Default fallback

    @classmethod
    def can_agent_handle_task(cls, agent_type: str, task_type: TaskType) -> bool:
        """Check if agent can handle task type"""
        return agent_type in cls.ROUTING_MAP.get(task_type, [])

    @classmethod
    def get_tasks_for_agent(cls, agent_type: str) -> List[TaskType]:
        """Get all task types that an agent can handle"""
        return [
            task_type
            for task_type, agents in cls.ROUTING_MAP.items()
            if agent_type in agents
        ]

    @classmethod
    def get_primary_agent(cls, task_type: TaskType) -> str:
        """Get primary agent for task type"""
        agents = cls.ROUTING_MAP.get(task_type, ["technical_analyst"])
        return agents[0] if agents else "technical_analyst"


# ============================================================================
# TASK VALIDATOR
# ============================================================================


class TaskValidator:
    """Task validation with contract enforcement"""

    @staticmethod
    def validate_task(task: Task) -> bool:
        """Validate complete task structure"""
        # Basic validation
        if not task.task_id:
            return False
        if not isinstance(task.task_type, TaskType):
            return False
        if not isinstance(task.priority, TaskPriority):
            return False
        if not isinstance(task.status, TaskStatus):
            return False
        if task.timeout_seconds <= 0:
            return False
        if task.max_retries < 0:
            return False
        if task.retry_count < 0:
            return False

        # Validate input
        if not TaskContracts.validate_task_input(task.task_type, task.input.parameters):
            return False

        return True

    @staticmethod
    def validate_task_result(task_type: TaskType, result: Dict[str, Any]) -> bool:
        """Validate task result against contract"""
        return TaskContracts.validate_task_output(task_type, result)

    @staticmethod
    def validate_task_creation(task_type: TaskType, parameters: Dict[str, Any]) -> bool:
        """Validate task creation parameters"""
        return TaskContracts.validate_task_input(task_type, parameters)


# ============================================================================
# TASK EXECUTOR CONTEXT
# ============================================================================


@dataclass
class TaskExecutionContext:
    """Context for task execution"""

    task_id: str
    trace_id: str
    agent_id: str
    execution_id: str
    started_at: datetime
    parent_context: Optional["TaskExecutionContext"] = None

    def create_child_context(self, task_id: str) -> "TaskExecutionContext":
        """Create child context for sub-tasks"""
        return TaskExecutionContext(
            task_id=task_id,
            trace_id=self.trace_id,
            agent_id=self.agent_id,
            execution_id=f"{self.execution_id}_{task_id}",
            started_at=datetime.now(),
            parent_context=self,
        )


# ============================================================================
# TASK QUEUE MANAGEMENT
# ============================================================================


class TaskQueue:
    """Task queue management with priority and scheduling"""

    def __init__(self):
        self._pending_tasks: List[Task] = []
        self._running_tasks: Dict[str, Task] = {}
        self._completed_tasks: List[Task] = []
        self._failed_tasks: List[Task] = []

        # Legacy compatibility attributes
        self.queue: List[AgentTask] = []
        self.processing_tasks: List[AgentTask] = []
        self.completed_tasks: List[AgentResult] = []

    def enqueue(self, task: Task) -> bool:
        """Enqueue task for execution"""
        if not TaskValidator.validate_task(task):
            return False

        self._pending_tasks.append(task)
        # Sort by priority (higher first)
        self._pending_tasks.sort(key=lambda t: t.priority.value, reverse=True)
        return True

    def dequeue(self) -> Optional[Task]:
        """Dequeue next task for execution"""
        if not self._pending_tasks:
            return None

        task = self._pending_tasks.pop(0)
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        self._running_tasks[task.task_id] = task
        return task

    # Legacy compatibility methods
    def add_task(self, task: AgentTask) -> None:
        """Add task to queue (legacy method)"""
        self.queue.append(task)
        # Sort by priority (higher first)
        self.queue.sort(key=lambda t: t.priority.value, reverse=True)

    def get_next_task(self) -> Optional[AgentTask]:
        """Get next task from queue (legacy method)"""
        if not self.queue:
            return None

        task = self.queue.pop(0)
        self.processing_tasks.append(task)
        return task

    def complete_task(self, task_id: str, result: AgentResult) -> None:
        """Complete a task (legacy method)"""
        # Remove from processing tasks
        for i, task in enumerate(self.processing_tasks):
            if task.task_id == task_id:
                self.processing_tasks.pop(i)
                self.completed_tasks.append(result)
                break

    def clear_queue(self) -> None:
        """Clear all tasks (legacy method)"""
        self.queue.clear()
        self.processing_tasks.clear()
        self.completed_tasks.clear()

    def get_queue_status(self) -> Dict[str, int]:
        """Get queue status (legacy method)"""
        return {
            "queued_tasks": len(self.queue),
            "processing_tasks": len(self.processing_tasks),
            "completed_tasks": len(self.completed_tasks),
            "total_tasks": len(self.queue)
            + len(self.processing_tasks)
            + len(self.completed_tasks),
        }

    def fail_task(self, task_id: str, error_message: str) -> bool:
        """Mark task as failed"""
        if task_id not in self._running_tasks:
            return False

        task = self._running_tasks.pop(task_id)
        task.status = TaskStatus.FAILED
        task.completed_at = datetime.now()

        # Check if should retry
        if task.retry_count < task.max_retries:
            task.retry_count += 1
            task.status = TaskStatus.PENDING
            task.started_at = None
            self._pending_tasks.append(task)
            self._pending_tasks.sort(key=lambda t: t.priority.value, reverse=True)

        self._failed_tasks.append(task)
        return True

    def get_task_status(self, task_id: str) -> Optional[Task]:
        """Get current task status"""
        for task in self._pending_tasks:
            if task.task_id == task_id:
                return task
        for task in self._running_tasks.values():
            if task.task_id == task_id:
                return task
        for task in self._completed_tasks:
            if task.task_id == task_id:
                return task
        for task in self._failed_tasks:
            if task.task_id == task_id:
                return task
        return None

    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        return {
            "pending_tasks": len(self._pending_tasks),
            "running_tasks": len(self._running_tasks),
            "completed_tasks": len(self._completed_tasks),
            "failed_tasks": len(self._failed_tasks),
            "total_tasks": len(self._pending_tasks)
            + len(self._running_tasks)
            + len(self._completed_tasks)
            + len(self._failed_tasks),
        }

    def dequeue(self) -> Optional[Task]:
        """Dequeue next task for execution"""
        if not self._pending_tasks:
            return None

        task = self._pending_tasks.pop(0)
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        self._running_tasks[task.task_id] = task
        return task

    def fail_task(self, task_id: str, error_message: str) -> bool:
        """Mark task as failed"""
        if task_id not in self._running_tasks:
            return False

        task = self._running_tasks.pop(task_id)
        task.status = TaskStatus.FAILED
        task.completed_at = datetime.now()

        # Check if should retry
        if task.retry_count < task.max_retries:
            task.retry_count += 1
            task.status = TaskStatus.PENDING
            task.started_at = None
            self._pending_tasks.append(task)
            self._pending_tasks.sort(key=lambda t: t.priority.value, reverse=True)

        self._failed_tasks.append(task)
        return True

    def get_task_status(self, task_id: str) -> Optional[Task]:
        """Get current task status"""
        for task in self._pending_tasks:
            if task.task_id == task_id:
                return task
        for task in self._running_tasks.values():
            if task.task_id == task_id:
                return task
        for task in self._completed_tasks:
            if task.task_id == task_id:
                return task
        for task in self._failed_tasks:
            if task.task_id == task_id:
                return task
        return None

    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        return {
            "pending_tasks": len(self._pending_tasks),
            "running_tasks": len(self._running_tasks),
            "completed_tasks": len(self._completed_tasks),
            "failed_tasks": len(self._failed_tasks),
            "total_tasks": len(self._pending_tasks)
            + len(self._running_tasks)
            + len(self._completed_tasks)
            + len(self._failed_tasks),
        }


# ============================================================================
# GLOBAL TASK QUEUE INSTANCE
# ============================================================================

_task_queue: Optional[TaskQueue] = None


def get_task_queue() -> TaskQueue:
    """Get global task queue instance"""
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue()
    return _task_queue


def initialize_tasks() -> None:
    """Initialize task system"""
    # Initialize global task queue
    get_task_queue()
    # Can add more initialization logic here if needed
    pass
