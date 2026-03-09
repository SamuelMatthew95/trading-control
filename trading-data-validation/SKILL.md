---
name: trading-data-validation
description: Field validation and data quality checks for trading data integrity. Use when you need to validate numeric trading data, check data quality, or ensure field consistency like "validate this trading data" or "check if these numbers are correct".
---

# Trading Data Validation

Validates numeric fields in trading data to ensure data integrity and quality.

## Quick Start
```python
from trading_data_validation.scripts.field_validator import ValidateNumericFields

validator = ValidateNumericFields()
data = {"price": 175.43, "volume": 1000000}
result = await validator.execute(data, "market_data")

if result["valid"]:
    print("Data is valid")
```

## Features
- **Pattern-based validation** for trading field types
- **Type conversion** from strings to numbers
- **Missing field detection** and warnings
- **Structured error reporting**

## Validation Patterns
- **Price fields**: price, entry_price, target_price, stop_price, close
- **Percentage fields**: confidence, change_percent, return, win_rate
- **Volume fields**: volume, trading_volume
- **Count fields**: count, total, quantity
- **Score fields**: score, rating, grade

## Output Format
```python
{
    "source": "market_data",
    "valid": True,
    "validated_fields": ["price", "volume"],
    "invalid_fields": [],
    "warnings": [],
    "validation_rate": 1.0
}
```

## Error Handling
- Graceful handling of None and empty data
- Detailed field-level error messages
- Conversion error tracking

---
*See [references/validation-rules.md](references/validation-rules.md) for detailed validation specifications.*
