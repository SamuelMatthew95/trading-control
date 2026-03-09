"""
Data Validation Tools - Field validation and quality checks
Extracted from tools.py for data-validation skill
"""

from __future__ import annotations

from typing import Any, Dict


class ValidateNumericFields:
    """Validate numeric fields in structured data"""

    def __init__(self):
        self.tool_id = "validate_numeric_fields"

    async def execute(self, data: Dict[str, Any], source: str) -> Dict[str, Any]:
        """Validate numeric fields in data"""
        if data is None:
            return {"error": "Data is required"}
            
        validation_results = {
            "source": source,
            "total_fields": len(data),
            "numeric_fields": 0,
            "valid_numeric_fields": 0,
            "invalid_fields": [],
            "missing_fields": [],
            "warnings": [],
            "overall_valid": True,
            "valid": True,  # For test compatibility
            "validated_fields": [],  # For test compatibility
        }

        # Define expected numeric fields by data type
        numeric_field_patterns = {
            "price": ["price", "entry_price", "target_price", "stop_price", "close"],
            "percentage": ["confidence", "change_percent", "return", "win_rate"],
            "volume": ["volume", "trading_volume"],
            "count": ["count", "total", "quantity"],
            "score": ["score", "rating", "grade"],
        }

        for field_name, field_value in data.items():
            is_numeric = False
            is_valid = True

            # Check if field should be numeric
            for pattern_name, patterns in numeric_field_patterns.items():
                if any(pattern in field_name.lower() for pattern in patterns):
                    is_numeric = True
                    validation_results["numeric_fields"] += 1
                    break

            if is_numeric:
                # Validate numeric value
                try:
                    if isinstance(field_value, str):
                        # Try to convert string to float
                        float(field_value)
                    elif isinstance(field_value, (int, float)):
                        pass  # Already numeric
                    else:
                        is_valid = False

                    if is_valid:
                        validation_results["valid_numeric_fields"] += 1
                        validation_results["validated_fields"].append(field_name)
                except (ValueError, TypeError):
                    is_valid = False
                    validation_results["invalid_fields"].append(
                        {
                            "field": field_name,
                            "value": field_value,
                            "error": "Invalid numeric value",
                        }
                    )
                    validation_results["overall_valid"] = False
                    validation_results["valid"] = False  # Keep in sync
            else:
                # Check for missing required fields
                if field_value is None or field_value == "":
                    validation_results["missing_fields"].append(field_name)
                    validation_results["warnings"].append(
                        f"Missing value for field: {field_name}"
                    )

        # Add summary
        validation_results["validation_rate"] = (
            validation_results["valid_numeric_fields"]
            / validation_results["numeric_fields"]
            if validation_results["numeric_fields"] > 0
            else 1.0
        )

        return validation_results
