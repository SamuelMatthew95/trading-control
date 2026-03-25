"""
Tests for SafeWriter V2 schema validation.
"""

import pytest
from api.core.writer.safe_writer import SafeWriter
from api.core.schemas import ProcessResult


class TestSafeWriterValidation:
    """Test SafeWriter's strict V2 schema validation."""
    
    def test_validate_schema_v2_success(self):
        """Test successful V2 schema validation."""
        writer = SafeWriter(None)  # Session factory not needed for validation test
        
        # Valid V2 data
        data = {
            'schema_version': 'v2',
            'source': 'test',
            'strategy_id': 'test-strategy'
        }
        
        # Should not raise exception
        writer._validate_schema_v2(data, 'Order')
    
    def test_validate_schema_v2_missing_version(self):
        """Test validation fails when schema_version is missing."""
        writer = SafeWriter(None)
        
        # Missing schema_version
        data = {
            'source': 'test',
            'strategy_id': 'test-strategy'
        }
        
        with pytest.raises(ValueError) as exc_info:
            writer._validate_schema_v2(data, 'Order')
        
        assert "Missing required field 'schema_version'" in str(exc_info.value)
        assert "Order" in str(exc_info.value)
    
    def test_validate_schema_v2_wrong_version(self):
        """Test validation fails with wrong schema version."""
        writer = SafeWriter(None)
        
        # Wrong schema version
        data = {
            'schema_version': 'v1',
            'source': 'test',
            'strategy_id': 'test-strategy'
        }
        
        with pytest.raises(ValueError) as exc_info:
            writer._validate_schema_v2(data, 'Order')
        
        assert "Invalid schema version 'v1'" in str(exc_info.value)
        assert "Expected 'v2'" in str(exc_info.value)
    
    def test_validate_schema_v2_missing_source(self):
        """Test validation fails when source is missing for models that require it."""
        writer = SafeWriter(None)
        
        # Missing source for Order (which requires it)
        data = {
            'schema_version': 'v2',
            'strategy_id': 'test-strategy'
        }
        
        with pytest.raises(ValueError) as exc_info:
            writer._validate_schema_v2(data, 'Order')
        
        assert "Source field is required" in str(exc_info.value)
        assert "Order" in str(exc_info.value)
    
    def test_validate_schema_v2_empty_source(self):
        """Test validation fails when source is empty."""
        writer = SafeWriter(None)
        
        # Empty source
        data = {
            'schema_version': 'v2',
            'source': '',
            'strategy_id': 'test-strategy'
        }
        
        with pytest.raises(ValueError) as exc_info:
            writer._validate_schema_v2(data, 'Order')
        
        assert "Source field is required" in str(exc_info.value)
    
    def test_log_write_operation(self):
        """Test write operation logging."""
        writer = SafeWriter(None)
        
        # Data with ID
        data = {'id': 'test-123', 'schema_version': 'v2'}
        
        # Should not raise exception
        writer._log_write_operation('test_op', 'TestModel', data)
    
    def test_log_write_operation_no_id(self):
        """Test logging when ID is missing."""
        writer = SafeWriter(None)
        
        # Data without ID
        data = {'schema_version': 'v2'}
        
        # Should not raise exception
        writer._log_write_operation('test_op', 'TestModel', data)


if __name__ == "__main__":
    pytest.main([__file__])
