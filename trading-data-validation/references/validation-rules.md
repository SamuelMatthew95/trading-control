# Validation Rules Specification

## Field Pattern Matching

### Price Fields
**Pattern**: `price`, `entry_price`, `target_price`, `stop_price`, `close`
**Validation**: Must be numeric (int, float, or numeric string)
**Range**: Typically > 0, but allows negative values for certain scenarios

### Percentage Fields  
**Pattern**: `confidence`, `change_percent`, `return`, `win_rate`
**Validation**: Must be numeric
**Range**: Usually 0-100 for percentages, but flexible for different contexts

### Volume Fields
**Pattern**: `volume`, `trading_volume`
**Validation**: Must be numeric
**Range**: Non-negative integers preferred

### Count Fields
**Pattern**: `count`, `total`, `quantity`
**Validation**: Must be numeric
**Range**: Non-negative integers

### Score Fields
**Pattern**: `score`, `rating`, `grade`
**Validation**: Must be numeric
**Range**: Context dependent (0-100, 0-5, etc.)

## Validation Logic

### Type Conversion
```python
# String to numeric conversion
if isinstance(field_value, str):
    try:
        float(field_value)  # Success if convertible
    except ValueError:
        # Mark as invalid
```

### Null Handling
- `None`: Treated as missing value, generates warning
- `""` (empty string): Treated as missing value, generates warning
- Empty containers: Valid but may generate warning

### Error Classification
| Error Type | Description | Example |
|------------|-------------|---------|
| Invalid Type | Non-numeric value in numeric field | "N/A" in price field |
| Missing Value | None or empty in required field | None in volume field |
| Conversion Failed | String cannot be converted to number | "abc" in percentage field |

## Output Structure

### Success Case
```python
{
    "valid": True,
    "validated_fields": ["price", "volume"],
    "validation_rate": 1.0,
    "warnings": []
}
```

### Error Case
```python
{
    "valid": False,
    "invalid_fields": [
        {
            "field": "price",
            "value": "N/A",
            "error": "Invalid numeric value"
        }
    ],
    "validation_rate": 0.5,
    "warnings": ["Missing value for field: volume"]
}
```

## Test Cases

### Valid Data
```python
data = {
    "price": 175.43,
    "volume": "1000000",  # String convertible to int
    "change_percent": 0.72
}
# Expected: valid=True
```

### Invalid Data
```python
data = {
    "price": "N/A",      # Invalid string
    "volume": None,      # Missing value
    "change_percent": "high"  # Non-numeric
}
# Expected: valid=False with errors
```

### Edge Cases
```python
# Empty data
{}  # Expected: valid=True (nothing to invalidate)

# None data
None  # Expected: error="Data is required"
```
