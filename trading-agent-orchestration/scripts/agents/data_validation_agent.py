"""
Stateless Data Validation Agent
Narrow scope: Validate trading data against quality rules
Intelligence lives in orchestration, not here
"""

from __future__ import annotations
import json
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, validator
from datetime import datetime


class ValidationInput(BaseModel):
    """Strict input contract for validation agent"""
    data: Dict[str, Any] = Field(..., description="Data to validate")
    validation_rules: list[str] = Field(default=["numeric_fields", "required_fields"], description="Validation rules to apply")
    source: str = Field(..., description="Data source identifier")


class ValidationError(BaseModel):
    """Structured error information"""
    field: str = Field(..., description="Field with error")
    error_type: str = Field(..., description="Type of error")
    message: str = Field(..., description="Error message")
    severity: str = Field(..., description="Error severity")
    
    @validator('severity')
    def validate_severity(cls, v):
        allowed = ['critical', 'warning', 'info']
        if v not in allowed:
            raise ValueError(f'severity must be one of {allowed}')
        return v


class ValidationOutput(BaseModel):
    """Strict output contract for validation agent"""
    is_valid: bool = Field(..., description="Overall validation result")
    validated_fields: list[str] = Field(..., description="Fields that passed validation")
    errors: List[ValidationError] = Field(..., description="Validation errors found")
    quality_score: float = Field(..., description="Data quality score 0-100")
    processing_time_ms: int = Field(..., description="Time taken to validate")
    
    @validator('quality_score')
    def validate_score(cls, v):
        if not 0 <= v <= 100:
            raise ValueError('quality_score must be between 0 and 100')
        return v


class DataValidationAgent:
    """Stateless data validation worker agent"""
    
    def __init__(self):
        self.agent_id = "data_validation_worker"
        self.version = "1.0.0"
        # No internal state - completely stateless
    
    async def execute(self, input_data: ValidationInput) -> ValidationOutput:
        """
        Execute data validation with strict I/O contracts
        No internal reasoning - just rule-based validation
        """
        start_time = datetime.now()
        
        try:
            # Apply validation rules deterministically
            validation_results = []
            validated_fields = []
            errors = []
            
            for rule in input_data.validation_rules:
                if rule == "numeric_fields":
                    result = self._validate_numeric_fields(input_data.data)
                    validation_results.append(result)
                elif rule == "required_fields":
                    result = self._validate_required_fields(input_data.data)
                    validation_results.append(result)
            
            # Aggregate results
            for result in validation_results:
                validated_fields.extend(result.get("validated_fields", []))
                errors.extend(result.get("errors", []))
            
            # Calculate quality score
            quality_score = self._calculate_quality_score(input_data.data, errors)
            
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return ValidationOutput(
                is_valid=len(errors) == 0,
                validated_fields=list(set(validated_fields)),
                errors=errors,
                quality_score=quality_score,
                processing_time_ms=int(processing_time)
            )
            
        except Exception as e:
            # Return structured error, not natural language
            raise ValueError(f"Data validation failed: {str(e)}")
    
    def _validate_numeric_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate numeric fields - deterministic rule application"""
        numeric_patterns = {
            "price": ["price", "entry_price", "target_price", "stop_price", "close"],
            "percentage": ["confidence", "change_percent", "return", "win_rate"],
            "volume": ["volume", "trading_volume"],
            "count": ["count", "total", "quantity"],
            "score": ["score", "rating", "grade"]
        }
        
        validated_fields = []
        errors = []
        
        for field_name, field_value in data.items():
            # Check if field should be numeric
            is_numeric_field = False
            for pattern_name, patterns in numeric_patterns.items():
                if any(pattern in field_name.lower() for pattern in patterns):
                    is_numeric_field = True
                    break
            
            if is_numeric_field:
                try:
                    # Convert to number
                    if isinstance(field_value, str):
                        float(field_value)
                    elif isinstance(field_value, (int, float)):
                        pass
                    else:
                        raise ValueError("Invalid numeric type")
                    
                    validated_fields.append(field_name)
                    
                except (ValueError, TypeError):
                    errors.append(ValidationError(
                        field=field_name,
                        error_type="invalid_numeric",
                        message=f"Field {field_name} contains invalid numeric value",
                        severity="critical"
                    ))
        
        return {
            "validated_fields": validated_fields,
            "errors": errors
        }
    
    def _validate_required_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate required fields - deterministic rule application"""
        required_fields = ["symbol", "price", "timestamp"]
        errors = []
        
        for field in required_fields:
            if field not in data or data[field] is None or data[field] == "":
                errors.append(ValidationError(
                    field=field,
                    error_type="missing_required",
                    message=f"Required field {field} is missing or empty",
                    severity="critical"
                ))
        
        return {
            "validated_fields": [field for field in required_fields if field in data and data[field] is not None],
            "errors": errors
        }
    
    def _calculate_quality_score(self, data: Dict[str, Any], errors: List[ValidationError]) -> float:
        """Calculate data quality score - deterministic formula"""
        if not data:
            return 0.0
        
        base_score = 100.0
        
        # Deduct points for errors
        for error in errors:
            if error.severity == "critical":
                base_score -= 20.0
            elif error.severity == "warning":
                base_score -= 10.0
            elif error.severity == "info":
                base_score -= 5.0
        
        # Deduct points for missing optional fields
        optional_fields = ["volume", "change", "change_percent"]
        missing_optional = sum(1 for field in optional_fields if field not in data)
        base_score -= missing_optional * 2.5
        
        return max(0.0, min(100.0, base_score))


# Agent metadata for governance
AGENT_METADATA = {
    "agent_id": "data_validation_worker",
    "version": "1.0.0",
    "scope": "data_validation",
    "stateless": True,
    "input_contract": "ValidationInput",
    "output_contract": "ValidationOutput",
    "permissions": ["read_data", "write_validation_results"],
    "max_execution_time_ms": 1000,
    "retry_count": 1
}
