"""
Tests for V3 DLQ Logic - No Redis Required

Tests the core logic for v2 event handling and trace_id validation
without requiring a running Redis instance.
"""

import pytest

from api.core.writer.safe_writer import SafeWriter
from api.db import AsyncSessionFactory


class TestV3DLQLogic:
    """Test V3 DLQ logic without Redis dependency."""

    def test_v2_schema_validation(self):
        """Test that v2 schema is rejected by SafeWriter."""
        print("🧪 Testing V2 Schema Validation...")

        # Create SafeWriter mock
        safe_writer = SafeWriter(AsyncSessionFactory)

        # Test v2 data (should fail)
        v2_data = {
            "schema_version": "v2",
            "msg_id": "test-v2-001",
            "strategy_id": "test_strategy",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "source": "test"
        }

        # Should raise ValueError for v2 schema
        with pytest.raises(ValueError, match="Invalid schema version.*Expected 'v3'"):
            safe_writer._validate_schema_v3(v2_data, "TestModel")

        print("✅ V2 schema validation test PASSED")

    def test_missing_trace_id_validation(self):
        """Test that missing trace_id is rejected."""
        print("🧪 Testing Missing Trace ID Validation...")

        safe_writer = SafeWriter(AsyncSessionFactory)

        # Test data without trace_id (should fail)
        no_trace_data = {
            "schema_version": "v3",
            "msg_id": "test-no-trace-001",
            "strategy_id": "test_strategy",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "source": "test"
        }

        # Should raise ValueError for missing trace_id
        with pytest.raises(ValueError, match="trace_id field is required for v3 events"):
            safe_writer._validate_schema_v3(no_trace_data, "TestModel")

        print("✅ Missing trace ID validation test PASSED")

    def test_v3_schema_validation_success(self):
        """Test that valid v3 schema passes validation."""
        print("🧪 Testing V3 Schema Validation Success...")

        safe_writer = SafeWriter(AsyncSessionFactory)

        # Test valid v3 data (should pass)
        v3_data = {
            "schema_version": "v3",
            "msg_id": "test-v3-001",
            "trace_id": "trace-v3-001",
            "strategy_id": "test_strategy",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "source": "test"
        }

        # Should not raise exception
        try:
            safe_writer._validate_schema_v3(v3_data, "TestModel")
            print("✅ V3 schema validation passed")
        except Exception as e:
            pytest.fail(f"V3 schema validation failed: {e}")

        print("✅ V3 schema validation success test PASSED")

    def test_source_field_validation(self):
        """Test that source field is required for v3."""
        print("🧪 Testing Source Field Validation...")

        safe_writer = SafeWriter(AsyncSessionFactory)

        # Test data without source (should fail)
        no_source_data = {
            "schema_version": "v3",
            "msg_id": "test-no-source-001",
            "trace_id": "trace-no-source-001",
            "strategy_id": "test_strategy",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100
        }

        # Should raise ValueError for missing source
        with pytest.raises(ValueError, match="Source field is required and cannot be empty"):
            safe_writer._validate_schema_v3(no_source_data, "Order")  # Order requires source

        print("✅ Source field validation test PASSED")

    def test_empty_source_field_validation(self):
        """Test that empty source field is rejected."""
        print("🧪 Testing Empty Source Field Validation...")

        safe_writer = SafeWriter(AsyncSessionFactory)

        # Test data with empty source (should fail)
        empty_source_data = {
            "schema_version": "v3",
            "msg_id": "test-empty-source-001",
            "trace_id": "trace-empty-source-001",
            "strategy_id": "test_strategy",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "source": ""  # Empty source
        }

        # Should raise ValueError for empty source
        with pytest.raises(ValueError, match="Source field is required and cannot be empty"):
            safe_writer._validate_schema_v3(empty_source_data, "Order")

        print("✅ Empty source field validation test PASSED")

    def test_payload_validation(self):
        """Test payload validation for required fields."""
        print("🧪 Testing Payload Validation...")

        safe_writer = SafeWriter(AsyncSessionFactory)

        # Test data missing required fields (should fail)
        incomplete_data = {
            "schema_version": "v3",
            "msg_id": "test-incomplete-001",
            "trace_id": "trace-incomplete-001",
            "symbol": "AAPL",
            "side": "buy"
            # Missing required fields
        }

        # Should raise ValueError for missing required fields
        with pytest.raises(ValueError, match="Missing required field: strategy_id"):
            safe_writer.validate_payload(incomplete_data, ['strategy_id', 'symbol', 'side'], 'test')

        print("✅ Payload validation test PASSED")

    def test_idempotency_key_validation(self):
        """Test idempotency key validation for financial operations."""
        print("🧪 Testing Idempotency Key Validation...")

        safe_writer = SafeWriter(AsyncSessionFactory)

        # Test data without idempotency_key (should fail for financial ops)
        no_idempotency_data = {
            "schema_version": "v3",
            "msg_id": "test-no-idempotency-001",
            "trace_id": "trace-no-idempotency-001",
            "strategy_id": "test_strategy",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "source": "test"
        }

        # Should raise ValueError for missing idempotency_key
        with pytest.raises(ValueError, match="idempotency_key is required for write_order"):
            safe_writer.validate_payload(no_idempotency_data, ['strategy_id', 'symbol', 'side'], 'write_order')

        print("✅ Idempotency key validation test PASSED")

    def test_trace_id_format_validation(self):
        """Test trace_id format and content."""
        print("🧪 Testing Trace ID Format Validation...")

        safe_writer = SafeWriter(AsyncSessionFactory)

        # Test with valid UUID trace_id
        valid_trace_data = {
            "schema_version": "v3",
            "msg_id": "test-valid-trace-001",
            "trace_id": "550e8400-e29b-41d4-a716-446655440000",  # Valid UUID
            "strategy_id": "test_strategy",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "source": "test"
        }

        # Should pass validation
        try:
            safe_writer._validate_schema_v3(valid_trace_data, "TestModel")
            print("✅ Valid UUID trace_id passed")
        except Exception as e:
            pytest.fail(f"Valid UUID trace_id validation failed: {e}")

        # Test with empty trace_id (should fail)
        empty_trace_data = {
            "schema_version": "v3",
            "msg_id": "test-empty-trace-001",
            "trace_id": "",  # Empty trace_id
            "strategy_id": "test_strategy",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "source": "test"
        }

        # Should raise ValueError for empty trace_id
        with pytest.raises(ValueError, match="trace_id field is required for v3 events"):
            safe_writer._validate_schema_v3(empty_trace_data, "TestModel")

        print("✅ Trace ID format validation test PASSED")

    def test_schema_version_case_sensitivity(self):
        """Test that schema_version is case sensitive."""
        print("🧪 Testing Schema Version Case Sensitivity...")

        safe_writer = SafeWriter(AsyncSessionFactory)

        # Test with uppercase V3 (should fail)
        uppercase_data = {
            "schema_version": "V3",  # Uppercase
            "msg_id": "test-uppercase-001",
            "trace_id": "trace-uppercase-001",
            "strategy_id": "test_strategy",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "source": "test"
        }

        # Should raise ValueError for uppercase schema version
        with pytest.raises(ValueError, match="Invalid schema version.*Expected 'v3'"):
            safe_writer._validate_schema_v3(uppercase_data, "TestModel")

        print("✅ Schema version case sensitivity test PASSED")

    def test_comprehensive_v3_validation(self):
        """Test comprehensive v3 validation with all required fields."""
        print("🧪 Testing Comprehensive V3 Validation...")

        safe_writer = SafeWriter(AsyncSessionFactory)

        # Test complete valid v3 data
        complete_v3_data = {
            "schema_version": "v3",
            "msg_id": "test-complete-001",
            "trace_id": "550e8400-e29b-41d4-a716-446655440000",
            "strategy_id": "test_strategy",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "market",
            "quantity": 100,
            "idempotency_key": "test-complete-001",
            "source": "comprehensive_test",
            "metadata": {"test": True}
        }

        # Should pass all validations
        try:
            safe_writer._validate_schema_v3(complete_v3_data, "Order")
            safe_writer.validate_payload(complete_v3_data, ['strategy_id', 'symbol', 'side'], 'test')
            print("✅ Complete v3 data passed all validations")
        except Exception as e:
            pytest.fail(f"Complete v3 validation failed: {e}")

        print("✅ Comprehensive v3 validation test PASSED")


def test_v2_dlq_requirement():
    """Test the specific v2 DLQ requirement from the user."""
    print("=" * 80)
    print("🧪 V2 DLQ REQUIREMENT TEST")
    print("=" * 80)
    print("Testing: @[/Users/matthew/Desktop/trading-control-python/api/v3_fixed_startup.py:L171-L172]")
    print("Requirement: v2 events should go to DLQ immediately")

    safe_writer = SafeWriter(AsyncSessionFactory)

    # Test the exact v2 event structure from the code
    v2_event = {
        "schema_version": "v2",
        "msg_id": "fixed-v2-001",
        "symbol": "GOOGL",
        "price": 2500.50,
        "source": "old_system"
    }

    # Should be rejected by v3 validation
    with pytest.raises(ValueError, match="Invalid schema version.*Expected 'v3'"):
        safe_writer._validate_schema_v3(v2_event, "TestModel")

    print("✅ V2 event properly rejected - would go to DLQ in production")
    print("✅ V2 DLQ requirement VERIFIED")
    print("=" * 80)


if __name__ == "__main__":
    print("🧪 Running V3 DLQ Logic Tests (No Redis Required)")

    # Run the specific requirement test
    test_v2_dlq_requirement()

    # Run all other tests
    test_instance = TestV3DLQLogic()

    test_methods = [
        test_instance.test_v2_schema_validation,
        test_instance.test_missing_trace_id_validation,
        test_instance.test_v3_schema_validation_success,
        test_instance.test_source_field_validation,
        test_instance.test_empty_source_field_validation,
        test_instance.test_payload_validation,
        test_instance.test_idempotency_key_validation,
        test_instance.test_trace_id_format_validation,
        test_instance.test_schema_version_case_sensitivity,
        test_instance.test_comprehensive_v3_validation
    ]

    for test_method in test_methods:
        try:
            test_method()
        except Exception as e:
            print(f"❌ Test failed: {test_method.__name__}: {e}")
            raise

    print("\n🎉 ALL V3 DLQ LOGIC TESTS PASSED!")
    print("✅ V2 events rejected (go to DLQ)")
    print("✅ Missing trace_id rejected (go to DLQ)")
    print("✅ V3 events accepted")
    print("✅ All validations working correctly")
