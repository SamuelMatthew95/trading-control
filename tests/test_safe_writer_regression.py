"""
Regression Test - Prevent SafeWriter signature mismatch bug.

This test ensures the previous TypeError never happens again:
TypeError: SafeWriter.write_system_metric() got an unexpected keyword argument 'metric_name'
"""

import pytest
from datetime import datetime, timezone


class TestSafeWriterSignatureRegression:
    """Regression test to prevent signature mismatch bugs."""
    
    @pytest.mark.asyncio
    async def test_write_system_metric_signature_contract(self, safe_writer):
        """
        MANDATORY: This test would have caught the previous TypeError.
        
        Tests the exact contract between caller and SafeWriter.
        All parameter names must match exactly between caller and method signature.
        """
        # This is the EXACT call pattern used by SystemMetricsConsumer
        result = await safe_writer.write_system_metric(
            msg_id="test-id",
            metric_name="cpu_usage",
            metric_value=0.5,
            metric_unit="percent",
            tags={},
            schema_version="v2",
            source="test",
            timestamp=datetime.now(timezone.utc),
        )
        
        # Should succeed without TypeError
        assert result is True
    
    @pytest.mark.asyncio
    async def test_all_callers_use_same_signature(self):
        """
        Verify all callers in codebase use identical argument names.
        This prevents future signature drift.
        """
        import ast
        import os
        
        # Expected argument names (contract)
        expected_args = {
            'msg_id', 'metric_name', 'metric_value', 
            'metric_unit', 'tags', 'schema_version', 
            'source', 'timestamp'
        }
        
        # Find all Python files with write_system_metric calls
        python_files = []
        for root, dirs, files in os.walk('.'):
            # Skip hidden directories and common non-source dirs
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules']]
            
            for file in files:
                if file.endswith('.py'):
                    python_files.append(os.path.join(root, file))
        
        # Parse each file and check write_system_metric calls
        for file_path in python_files:
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                    
                # Skip if no write_system_metric call
                if 'write_system_metric(' not in content:
                    continue
                    
                # Parse AST to find function calls
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        if (hasattr(node.func, 'attr') and 
                            node.func.attr == 'write_system_metric'):
                            
                            # Check keyword arguments
                            if node.keywords:
                                used_args = {kw.arg for kw in node.keywords if kw.arg}
                                
                                # Verify all expected args are present (or subset for partial calls)
                                unexpected_args = used_args - expected_args
                                if unexpected_args:
                                    pytest.fail(
                                        f"File {file_path} uses unexpected arguments "
                                        f"in write_system_metric call: {unexpected_args}. "
                                        f"Expected: {expected_args}"
                                    )
                                
                                # Verify no argument name mismatches
                                for kw in node.keywords:
                                    if kw.arg and kw.arg not in expected_args:
                                        pytest.fail(
                                            f"File {file_path} uses invalid argument "
                                            f"'{kw.arg}' in write_system_metric call. "
                                            f"Valid arguments: {expected_args}"
                                        )
                                    
            except Exception as e:
                # Skip files that can't be parsed (likely non-critical)
                continue
    
    @pytest.mark.asyncio 
    async def test_parameter_validation_defensive(self, safe_writer):
        """
        Test defensive validation prevents silent failures.
        """
        timestamp = datetime.now(timezone.utc)
        
        # Test missing msg_id
        with pytest.raises(ValueError) as exc_info:
            await safe_writer.write_system_metric(
                msg_id="",  # Empty
                metric_name="cpu_usage",
                metric_value=0.5,
                metric_unit=None,
                tags={},
                schema_version="v2",
                source="test",
                timestamp=timestamp,
            )
        assert "msg_id is required" in str(exc_info.value)
        
        # Test missing metric_name
        with pytest.raises(ValueError) as exc_info:
            await safe_writer.write_system_metric(
                msg_id="test-id",
                metric_name="",  # Empty
                metric_value=0.5,
                metric_unit=None,
                tags={},
                schema_version="v2",
                source="test",
                timestamp=timestamp,
            )
        assert "metric_name is required" in str(exc_info.value)
        
        # Test missing metric_value
        with pytest.raises(ValueError) as exc_info:
            await safe_writer.write_system_metric(
                msg_id="test-id",
                metric_name="cpu_usage",
                metric_value=None,  # None
                metric_unit=None,
                tags={},
                schema_version="v2",
                source="test",
                timestamp=timestamp,
            )
        assert "metric_value is required" in str(exc_info.value)


class TestSystemMetricsHandlerRegression:
    """Regression test for system_metrics_handler.py signature fix."""
    
    @pytest.mark.asyncio
    async def test_handler_uses_correct_signature(self):
        """
        Verify system_metrics_handler.py uses new signature.
        This would have caught the previous bug.
        """
        from api.services.system_metrics_handler import handle_system_metric
        
        # Mock SafeWriter to capture the call
        from unittest.mock import Mock, patch
        
        with patch('api.services.system_metrics_handler.SafeWriter') as mock_writer_class:
            mock_writer = Mock()
            mock_writer_class.return_value = mock_writer
            
            # Test data
            test_data = {
                "metric_name": "cpu_usage",
                "value": 75.5,
                "unit": "percent",
                "tags": {"host": "server1"},
                "timestamp": "2024-01-01T00:00:00Z"
            }
            
            # Call handler
            result = await handle_system_metric(
                msg_id="test-handler-1",
                stream="system_metrics", 
                data=test_data,
                trace_id="trace-123"
            )
            
            # Verify SafeWriter was called with NEW signature
            mock_writer.write_system_metric.assert_called_once()
            call_kwargs = mock_writer.write_system_metric.call_args[1]
            
            # Check all expected arguments are present
            expected_args = {
                'msg_id', 'metric_name', 'metric_value',
                'metric_unit', 'tags', 'schema_version',
                'source', 'timestamp'
            }
            
            actual_args = set(call_kwargs.keys())
            assert actual_args == expected_args, f"Handler uses wrong args: {actual_args}"
            
            # Verify specific values
            assert call_kwargs['msg_id'] == "test-handler-1"
            assert call_kwargs['metric_name'] == "cpu_usage"
            assert call_kwargs['metric_value'] == 75.5
            assert call_kwargs['metric_unit'] == "percent"
            assert call_kwargs['tags'] == {"host": "server1"}
            assert call_kwargs['schema_version'] == "v2"
            assert call_kwargs['source'] == "system_monitor"
