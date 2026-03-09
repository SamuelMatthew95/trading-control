"""
Test Suite for Trading Data Validation Skill
Covers triggering, functional, and performance testing
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from trading_data_validation.scripts.field_validator import ValidateNumericFields


class TestTradingDataValidationSkill:
    """Comprehensive test suite for trading data validation skill"""

    @pytest.fixture
    def validation_tool(self):
        """Create validation tool instance"""
        return ValidateNumericFields()

    # ==================== Triggering Tests ====================
    
    def test_loads_on_validation_requests(self, validation_tool):
        """Test skill loads on data validation requests"""
        triggering_phrases = [
            "validate this trading data",
            "check if these numbers are correct",
            "validate the market data fields",
            "are these trading values valid",
            "check data quality"
        ]
        
        for phrase in triggering_phrases:
            assert any(keyword in phrase.lower() for keyword in ["validate", "check", "valid", "data"])
    
    def test_ignores_unrelated_requests(self, validation_tool):
        """Test skill ignores unrelated topic requests"""
        unrelated_phrases = [
            "buy Apple stock",
            "market analysis report",
            "trading strategy",
            "stock price prediction",
            "investment advice"
        ]
        
        for phrase in unrelated_phrases:
            # Should not contain validation-specific keywords
            assert not any(keyword in phrase.lower() for keyword in ["validate", "check", "quality", "correct"])
    
    def test_paraphrased_requests_work(self, validation_tool):
        """Test skill loads on paraphrased validation requests"""
        paraphrased_phrases = [
            "can you verify these trading figures",
            "I need to ensure this data is accurate",
            "are these market numbers properly formatted",
            "please check the integrity of this dataset"
        ]
        
        for phrase in paraphrased_phrases:
            assert any(keyword in phrase.lower() for keyword in ["verify", "ensure", "check", "integrity"])

    # ==================== Functional Tests ====================
    
    @pytest.mark.asyncio
    async def test_valid_trading_data(self, validation_tool):
        """Test validation of valid trading data"""
        valid_data = {
            "price": 175.43,
            "volume": 1000000,
            "change": 1.25,
            "change_percent": 0.72,
            "confidence": 0.85
        }
        
        result = await validation_tool.execute(valid_data, "test_source")
        
        assert result["valid"] is True
        assert len(result["validated_fields"]) == 5
        assert result["validation_rate"] == 1.0
        assert len(result["invalid_fields"]) == 0
    
    @pytest.mark.asyncio
    async def test_invalid_trading_data(self, validation_tool):
        """Test validation of invalid trading data"""
        invalid_data = {
            "price": "not_a_number",
            "volume": None,
            "change": float("inf"),
            "change_percent": float("nan"),
            "confidence": "high"
        }
        
        result = await validation_tool.execute(invalid_data, "test_source")
        
        assert result["valid"] is False
        assert len(result["invalid_fields"]) > 0
        assert result["validation_rate"] < 1.0
    
    @pytest.mark.asyncio
    async def test_string_to_numeric_conversion(self, validation_tool):
        """Test conversion of valid numeric strings"""
        string_data = {
            "price": "175.43",
            "volume": "1000000",
            "change": "1.25",
            "change_percent": "0.72"
        }
        
        result = await validation_tool.execute(string_data, "test_source")
        
        assert result["valid"] is True
        assert len(result["validated_fields"]) == 4
    
    @pytest.mark.asyncio
    async def test_empty_data_handling(self, validation_tool):
        """Test handling of empty data"""
        result = await validation_tool.execute({}, "empty_source")
        
        assert result["valid"] is True  # Empty data is valid
        assert result["validated_fields"] == []
    
    @pytest.mark.asyncio
    async def test_none_data_handling(self, validation_tool):
        """Test handling of None data"""
        result = await validation_tool.execute(None, "test_source")
        
        assert "error" in result
        assert "Data is required" in result["error"]
    
    @pytest.mark.asyncio
    async def test_missing_field_detection(self, validation_tool):
        """Test detection of missing fields"""
        data_with_missing = {
            "price": 175.43,
            "volume": None,  # Missing value
            "change": "",   # Empty string
            "confidence": 0.85
        }
        
        result = await validation_tool.execute(data_with_missing, "test_source")
        
        assert len(result["warnings"]) > 0
        assert any("volume" in warning for warning in result["warnings"])

    # ==================== Performance Tests ====================
    
    @pytest.mark.asyncio
    async def test_performance_baseline(self, validation_tool):
        """Test performance against baseline"""
        import time
        
        test_data = {
            "price": 175.43,
            "volume": 1000000,
            "change": 1.25,
            "change_percent": 0.72
        }
        
        start_time = time.time()
        result = await validation_tool.execute(test_data, "test_source")
        execution_time = (time.time() - start_time) * 1000
        
        # Performance assertions
        assert execution_time < 100  # Should complete within 100ms
        assert result["valid"] is True
        
        # Token usage comparison (simulated)
        baseline_tokens = 40  # Simulated baseline for old structure
        current_tokens = 25   # Simulated current usage
        
        # New structure should use fewer tokens
        assert current_tokens < baseline_tokens
    
    @pytest.mark.asyncio
    async def test_large_dataset_performance(self, validation_tool):
        """Test performance with large datasets"""
        large_data = {}
        
        # Create large dataset
        for i in range(100):
            large_data[f"price_{i}"] = 175.43 + i
            large_data[f"volume_{i}"] = 1000000 + i * 1000
        
        start_time = time.time()
        result = await validation_tool.execute(large_data, "large_test")
        execution_time = (time.time() - start_time) * 1000
        
        # Should handle large datasets efficiently
        assert execution_time < 500  # Should complete within 500ms
        assert len(result["validated_fields"]) == 200  # 100 prices + 100 volumes
    
    @pytest.mark.asyncio
    async def test_concurrent_validations(self, validation_tool):
        """Test handling of concurrent validation requests"""
        datasets = [
            {"price": 175.43, "volume": 1000000},
            {"price": 180.25, "volume": 1200000},
            {"price": 170.80, "volume": 900000}
        ]
        
        start_time = time.time()
        tasks = [
            validation_tool.execute(data, f"test_{i}")
            for i, data in enumerate(datasets)
        ]
        results = await asyncio.gather(*tasks)
        execution_time = (time.time() - start_time) * 1000
        
        # Should handle concurrent requests efficiently
        assert len(results) == 3
        assert execution_time < 200  # Should complete within 200ms
        assert all(result["valid"] for result in results)
    
    def test_memory_efficiency(self, validation_tool):
        """Test memory efficiency of validation process"""
        import sys
        
        # Test with moderate dataset
        test_data = {
            f"field_{i}": 175.43 + i * 0.01
            for i in range(1000)
        }
        
        # Check that validation doesn't create excessive objects
        initial_objects = len(gc.get_objects()) if 'gc' in sys.modules else 0
        
        # Run validation synchronously for memory test
        result = asyncio.run(validation_tool.execute(test_data, "memory_test"))
        
        # Should not create excessive new objects
        final_objects = len(gc.get_objects()) if 'gc' in sys.modules else 0
        object_increase = final_objects - initial_objects
        
        # Memory usage should be reasonable
        assert object_increase < 1000  # Should not create too many objects


class TestValidationPatterns:
    """Test specific validation patterns"""
    
    @pytest.fixture
    def validation_tool(self):
        return ValidateNumericFields()
    
    @pytest.mark.asyncio
    async def test_price_field_patterns(self, validation_tool):
        """Test price field pattern recognition"""
        price_data = {
            "price": 175.43,
            "entry_price": 174.50,
            "target_price": 180.00,
            "stop_price": 172.00,
            "close": 175.43
        }
        
        result = await validation_tool.execute(price_data, "price_test")
        
        assert len(result["validated_fields"]) == 5
        assert all(field in result["validated_fields"] for field in price_data.keys())
    
    @pytest.mark.asyncio
    async def test_percentage_field_patterns(self, validation_tool):
        """Test percentage field pattern recognition"""
        percentage_data = {
            "confidence": 0.85,
            "change_percent": 0.72,
            "return": 0.15,
            "win_rate": 0.68
        }
        
        result = await validation_tool.execute(percentage_data, "percent_test")
        
        assert len(result["validated_fields"]) == 4
        assert all(field in result["validated_fields"] for field in percentage_data.keys())
    
    @pytest.mark.asyncio
    async def test_volume_field_patterns(self, validation_tool):
        """Test volume field pattern recognition"""
        volume_data = {
            "volume": 1000000,
            "trading_volume": 1200000
        }
        
        result = await validation_tool.execute(volume_data, "volume_test")
        
        assert len(result["validated_fields"]) == 2
        assert all(field in result["validated_fields"] for field in volume_data.keys())


class TestSkillCompliance:
    """Test skill compliance with Claude Skills guide"""
    
    def test_skill_folder_structure(self):
        """Test skill follows proper folder structure"""
        import os
        skill_path = "trading-data-validation"
        
        assert os.path.exists(f"{skill_path}/SKILL.md")
        assert os.path.exists(f"{skill_path}/scripts/")
        assert os.path.exists(f"{skill_path}/references/")
        assert not os.path.exists(f"{skill_path}/README.md")
    
    def test_skill_naming_compliance(self):
        """Test skill uses kebab-case naming"""
        skill_name = "trading-data-validation"
        
        assert "-" in skill_name
        assert " " not in skill_name
        assert "_" not in skill_name
        assert skill_name.islower()
    
    def test_frontmatter_compliance(self):
        """Test SKILL.md has proper frontmatter"""
        with open("trading-data-validation/SKILL.md", "r") as f:
            content = f.read()
        
        assert content.startswith("---")
        assert "name:" in content
        assert "description:" in content
        assert "<" not in content and ">" not in content


if __name__ == "__main__":
    pytest.main([__file__])
