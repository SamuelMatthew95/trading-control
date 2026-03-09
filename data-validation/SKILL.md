---
name: Data Validation
description: Field validation and data quality checks for trading data integrity
---

# Data Validation Skill

## Overview
The Data Validation skill ensures data integrity and quality through comprehensive field validation, particularly for numeric trading data.

## Capabilities

### Level 1: High-Level Overview
- Numeric field validation and type checking
- Data quality assessment and reporting
- Missing field detection and warnings

### Level 2: Implementation Details
- **Primary Tool**: `ValidateNumericFields` class
- **Validation Patterns**: Price, percentage, volume, count, score fields
- **Error Reporting**: Detailed field-level validation results
- **Compatibility**: Test-compliant interface with backward compatibility

### Level 3: Technical Specifications

#### Validation Patterns
```python
numeric_field_patterns = {
    "price": ["price", "entry_price", "target_price", "stop_price", "close"],
    "percentage": ["confidence", "change_percent", "return", "win_rate"],
    "volume": ["volume", "trading_volume"],
    "count": ["count", "total", "quantity"],
    "score": ["score", "rating", "grade"],
}
```

#### Result Structure
```python
{
    "source": "test_source",
    "total_fields": 4,
    "numeric_fields": 4,
    "valid_numeric_fields": 4,
    "invalid_fields": [],
    "missing_fields": [],
    "warnings": [],
    "overall_valid": True,
    "valid": True,  # Test compatibility
    "validated_fields": ["price", "volume", "change", "change_percent"],
    "validation_rate": 1.0
}
```

## Usage Examples

### Basic Validation
```python
from data_validation.scripts.field_validator import ValidateNumericFields

validator = ValidateNumericFields()
data = {"price": 175.43, "volume": 1000000, "change": 1.25, "change_percent": 0.72}
result = await validator.execute(data, "market_data")

if result["valid"]:
    print("Data is valid")
else:
    print(f"Invalid fields: {result['invalid_fields']}")
```

### Error Handling
```python
result = await validator.execute(None, "test_source")
if "error" in result:
    print(f"Validation error: {result['error']}")
```

### Empty Data Handling
```python
result = await validator.execute({}, "empty_source")
# Returns valid=True for empty data
```

## Dependencies
- `typing` for type annotations
- Standard library only (no external dependencies)

## Test Compliance
This skill is designed to pass the existing test suite:
- `test_execute_valid_data`
- `test_execute_invalid_data` 
- `test_execute_empty_data`
- `test_execute_none_data`

## Validation Rules
- **Numeric Detection**: Pattern-based field identification
- **Type Conversion**: String to numeric conversion when possible
- **Null Handling**: Proper None and empty string detection
- **Error Reporting**: Structured error messages with field details
