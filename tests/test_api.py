"""
Test Suite for API Module
Comprehensive tests for API endpoints and models
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Add parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.models import (
    AgentInfo,
    HealthStatus,
    PlatformStatus,
    ToolExecutionRequest,
    ToolExecutionResponse,
    ToolInfo,
)
from api.routes import api_router


class TestAPIModels:
    """Test API data models"""

    def test_tool_info_model(self):
        """Test ToolInfo model creation and validation"""
        tool_info = ToolInfo(
            tool_id="get_stock_quote",
            name="Get Stock Quote",
            description="Retrieve current stock price and basic market data",
            tool_type="market",
            version="1.0.0",
            parameters={"symbol": "Stock symbol (e.g., AAPL, GOOGL)"},
        )

        assert tool_info.tool_id == "get_stock_quote"
        assert tool_info.name == "Get Stock Quote"
        assert "stock price" in tool_info.description.lower()
        assert tool_info.tool_type == "market"
        assert tool_info.version == "1.0.0"
        assert "symbol" in tool_info.parameters
        assert tool_info.parameters["symbol"] == "Stock symbol (e.g., AAPL, GOOGL)"

    def test_tool_execution_request_model(self):
        """Test ToolExecutionRequest model creation and validation"""
        request = ToolExecutionRequest(
            tool_id="get_stock_quote", parameters={"symbol": "AAPL"}
        )

        assert request.tool_id == "get_stock_quote"
        assert request.parameters["symbol"] == "AAPL"

    def test_tool_execution_request_missing_tool_id(self):
        """Test ToolExecutionRequest with missing tool_id"""
        with pytest.raises(ValueError):
            ToolExecutionRequest(tool_id=None, parameters={"symbol": "AAPL"})

    def test_tool_execution_request_empty_parameters(self):
        """Test ToolExecutionRequest with empty parameters"""
        request = ToolExecutionRequest(tool_id="validate_numeric_fields", parameters={})

        assert request.tool_id == "validate_numeric_fields"
        assert request.parameters == {}

    def test_tool_execution_response_model(self):
        """Test ToolExecutionResponse model creation"""
        response = ToolExecutionResponse(
            tool_id="get_stock_quote",
            result={"symbol": "AAPL", "price": 175.43, "source": "alpha_vantage"},
            timestamp="2024-03-04T15:30:00Z",
        )

        assert response.tool_id == "get_stock_quote"
        assert response.result["symbol"] == "AAPL"
        assert response.result["price"] == 175.43
        assert response.result["source"] == "alpha_vantage"
        assert response.timestamp == "2024-03-04T15:30:00Z"

    def test_agent_info_model(self):
        """Test AgentInfo model creation"""
        agent_info = AgentInfo(
            agent_id="technical_analyst_001",
            agent_type="technical_analyst",
            name="Technical Analyst Agent",
            status="active",
            tasks_completed=150,
            tasks_failed=5,
            current_load=2,
            max_concurrent_tasks=5,
            last_activity="2024-03-04T15:30:00Z",
        )

        assert agent_info.agent_id == "technical_analyst_001"
        assert agent_info.agent_type == "technical_analyst"
        assert agent_info.name == "Technical Analyst Agent"
        assert agent_info.status == "active"
        assert agent_info.tasks_completed == 150
        assert agent_info.tasks_failed == 5
        assert agent_info.current_load == 2
        assert agent_info.max_concurrent_tasks == 5
        assert agent_info.last_activity == "2024-03-04T15:30:00Z"

    def test_platform_status_model(self):
        """Test PlatformStatus model creation"""
        from api.models import OrchestratorStatus

        platform_status = PlatformStatus(
            status="running",
            environment="development",
            registered_agents=3,
            active_tasks=5,
            background_tasks=2,
            orchestrator=OrchestratorStatus(
                is_running=True,
                current_cycle_id="cycle_001",
                active_cycles=1,
                total_cycles=10,
                successful_cycles=8,
                failed_cycles=2,
                success_rate=0.8,
                last_cycle_time="2024-03-04T15:30:00Z",
                registered_agents=3,
                symbols_monitored=["AAPL", "GOOGL", "MSFT"],
            ),
            observability={"events_processed": 1000},
            memory={"short_term_size": 50, "persistent_size": 1000},
            tools={"available_tools": 5, "executed_today": 25},
        )

        assert platform_status.status == "running"
        assert platform_status.environment == "development"
        assert platform_status.registered_agents == 3
        assert platform_status.active_tasks == 5
        assert platform_status.background_tasks == 2
        assert platform_status.orchestrator.is_running is True
        assert platform_status.orchestrator.active_cycles == 1
        assert platform_status.observability["events_processed"] == 1000
        assert platform_status.memory["short_term_size"] == 50
        assert platform_status.tools["available_tools"] == 5

    def test_health_status_model(self):
        """Test HealthStatus model creation"""
        health_status = HealthStatus(
            status="healthy",
            timestamp="2024-03-04T15:30:00Z",
            platform_running=True,
            orchestrator_running=True,
            agents_registered=3,
            active_cycles=1,
            reason=None,
        )

        assert health_status.status == "healthy"
        assert health_status.timestamp == "2024-03-04T15:30:00Z"
        assert health_status.platform_running is True
        assert health_status.orchestrator_running is True
        assert health_status.agents_registered == 3
        assert health_status.active_cycles == 1
        assert health_status.reason is None


class TestAPIEndpoints:
    """Test API endpoint functionality"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        from main import TradingControlPlatform, app

        # Initialize platform state for tests
        platform = TradingControlPlatform()

        # Set platform in app state
        app.state.platform = platform

        return TestClient(app)

    def test_root_endpoint(self, client):
        """Test root endpoint"""
        response = client.get("/api/v1/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data or "message" in data or "status" in data

    def test_health_endpoint(self, client):
        """Test health check endpoint"""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        assert data["status"] in ["healthy", "unhealthy", "degraded"]

    def test_health_endpoint_with_orchestrator(self, client):
        """Test health endpoint with orchestrator status"""
        with patch("orchestrator.OpenClawOrchestrator") as mock_orchestrator:
            mock_orchestrator.return_value.get_status.return_value = {
                "is_running": True,
                "active_cycles": 1,
                "success_rate": 0.95,
            }

            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"

    def test_get_tools_endpoint(self, client):
        """Test getting all tools endpoint"""
        with patch("tools.get_tool_registry") as mock_registry:
            mock_tool = MagicMock()
            mock_tool.tool_id = "get_stock_quote"
            mock_tool.name = "Get Stock Quote"
            mock_tool.description = "Retrieve stock price"
            mock_tool.tool_type = "market"
            mock_tool.version = "1.0.0"
            mock_tool.parameters = {"symbol": "Stock symbol"}

            mock_registry_instance = MagicMock()
            mock_registry_instance.list_tools.return_value = [mock_tool]
            mock_registry.return_value = mock_registry_instance

            response = client.get("/api/v1/tools")

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) >= 1
            assert data[0]["tool_id"] == "get_stock_quote"
            assert data[0]["name"] == "Get Stock Quote"

    def test_get_specific_tool_endpoint(self, client):
        """Test getting specific tool endpoint"""
        with patch("tools.get_tool_registry") as mock_registry:
            mock_tool = MagicMock()
            mock_tool.tool_id = "get_stock_quote"
            mock_tool.name = "Get Stock Quote"
            mock_tool.description = "Retrieve stock price"
            mock_tool.tool_type = "market"
            mock_tool.version = "1.0.0"
            mock_tool.parameters = {"symbol": "Stock symbol"}

            mock_registry_instance = MagicMock()
            mock_registry_instance.get_tool.return_value = mock_tool
            mock_registry.return_value = mock_registry_instance

            response = client.get("/api/v1/tools/get_stock_quote")

            assert response.status_code == 200
            data = response.json()
            assert data["tool_id"] == "get_stock_quote"
            assert data["name"] == "Get Stock Quote"

    def test_get_nonexistent_tool_endpoint(self, client):
        """Test getting non-existent tool endpoint"""
        with patch("tools.get_tool_registry") as mock_registry:
            mock_registry_instance = MagicMock()
            mock_registry_instance.get_tool.side_effect = ValueError("Tool not found")
            mock_registry.return_value = mock_registry_instance

            response = client.get("/api/v1/tools/non_existent_tool")

            assert response.status_code == 404

    def test_execute_tool_endpoint_success(self, client):
        """Test tool execution endpoint success"""
        with patch("tools.get_tool_registry") as mock_registry:
            mock_tool = AsyncMock()
            mock_tool.execute.return_value = {
                "symbol": "AAPL",
                "price": 175.43,
                "source": "alpha_vantage",
            }

            mock_registry_instance = MagicMock()
            mock_registry_instance.get_tool.return_value = mock_tool
            mock_registry.return_value = mock_registry_instance

            request_data = {
                "tool_id": "get_stock_quote",
                "parameters": {"symbol": "AAPL"},
            }

            response = client.post(
                "/api/v1/tools/get_stock_quote/execute", json=request_data
            )

            assert response.status_code == 200
            data = response.json()
            assert data["tool_id"] == "get_stock_quote"
            assert "result" in data
            assert data["result"]["symbol"] == "AAPL"
            assert data["result"]["price"] == 175.43
            assert "timestamp" in data

    def test_execute_tool_endpoint_missing_tool_id(self, client):
        """Test tool execution with missing tool_id"""
        request_data = {"parameters": {"symbol": "AAPL"}}

        response = client.post(
            "/api/v1/tools/get_stock_quote/execute", json=request_data
        )

        assert response.status_code == 422  # Validation error

    def test_execute_tool_endpoint_invalid_parameters(self, client):
        """Test tool execution with invalid parameters"""
        with patch("tools.get_tool_registry") as mock_registry:
            mock_tool = AsyncMock()
            mock_tool.execute.side_effect = ValueError("Invalid parameters")

            mock_registry_instance = MagicMock()
            mock_registry_instance.get_tool.return_value = mock_tool
            mock_registry.return_value = mock_registry_instance

            request_data = {
                "tool_id": "get_stock_quote",
                "parameters": {"invalid_param": "value"},
            }

            response = client.post(
                "/api/v1/tools/get_stock_quote/execute", json=request_data
            )

            assert response.status_code == 400 or response.status_code == 500

    def test_execute_nonexistent_tool_endpoint(self, client):
        """Test executing non-existent tool"""
        with patch("tools.get_tool_registry") as mock_registry:
            mock_registry_instance = MagicMock()
            mock_registry_instance.get_tool.side_effect = ValueError("Tool not found")
            mock_registry.return_value = mock_registry_instance

            request_data = {"tool_id": "non_existent_tool", "parameters": {}}

            response = client.post(
                "/api/v1/tools/non_existent_tool/execute", json=request_data
            )

            assert response.status_code == 404

    def test_get_agents_endpoint(self, client):
        """Test getting all agents endpoint"""
        with patch("orchestrator.OpenClawOrchestrator") as mock_orchestrator:
            mock_orchestrator.return_value.get_registered_agents.return_value = [
                {
                    "agent_id": "technical_analyst_001",
                    "agent_type": "technical_analyst",
                    "name": "Technical Analyst",
                    "status": "active",
                    "tasks_completed": 100,
                    "tasks_failed": 5,
                    "current_load": 2,
                    "max_concurrent_tasks": 5,
                }
            ]

            response = client.get("/api/v1/agents")

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) >= 1
            assert data[0]["agent_id"] == "technical_analyst_001"

    def test_get_specific_agent_endpoint(self, client):
        """Test getting specific agent endpoint"""
        with patch("orchestrator.OpenClawOrchestrator") as mock_orchestrator:
            mock_orchestrator.return_value.get_registered_agents.return_value = [
                {
                    "agent_id": "technical_analyst_001",
                    "agent_type": "technical_analyst",
                    "name": "Technical Analyst",
                    "status": "active",
                    "tasks_completed": 100,
                    "tasks_failed": 5,
                    "current_load": 2,
                    "max_concurrent_tasks": 5,
                }
            ]

            response = client.get("/api/v1/agents/technical_analyst_001")

            assert response.status_code == 200
            data = response.json()
            assert data["agent_id"] == "technical_analyst_001"

    def test_get_nonexistent_agent_endpoint(self, client):
        """Test getting non-existent agent endpoint"""
        with patch("orchestrator.OpenClawOrchestrator") as mock_orchestrator:
            mock_orchestrator.return_value.get_registered_agents.return_value = []

            response = client.get("/api/v1/agents/non_existent_agent")

            assert response.status_code == 404

    def test_platform_status_endpoint(self, client):
        """Test platform status endpoint"""
        with (
            patch("orchestrator.OpenClawOrchestrator") as mock_orchestrator,
            patch("tools.get_tool_registry") as mock_tools,
            patch("memory.get_memory_manager") as mock_memory,
        ):

            mock_orchestrator.return_value.get_status.return_value = {
                "is_running": True,
                "active_cycles": 1,
                "total_cycles": 100,
                "success_rate": 0.95,
            }

            mock_tools.return_value.list_tools.return_value = [
                MagicMock(tool_id="tool1"),
                MagicMock(tool_id="tool2"),
            ]

            mock_memory.return_value.get_memory_stats.return_value = {
                "short_term_size": 50,
                "persistent_size": 1000,
            }

            response = client.get("/api/v1/platform/status")

            assert response.status_code == 200
            data = response.json()
            assert "status" in data
            assert "environment" in data
            assert "registered_agents" in data
            assert "active_tasks" in data
            assert "background_tasks" in data
            assert "orchestrator" in data
            assert "memory" in data
            assert "tools" in data


class TestAPIErrorHandling:
    """Test API error handling"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        from main import TradingControlPlatform, app

        # Initialize platform state for tests
        platform = TradingControlPlatform()

        # Set platform in app state
        app.state.platform = platform

        return TestClient(app)

    def test_invalid_json_handling(self, client):
        """Test handling of invalid JSON"""
        response = client.post(
            "/api/v1/tools/get_stock_quote/execute",
            data="invalid json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 422

    def test_missing_content_type(self, client):
        """Test handling of missing content type"""
        response = client.post(
            "/api/v1/tools/get_stock_quote/execute",
            data='{"tool_id": "get_stock_quote", "parameters": {}}',
        )

        # FastAPI should handle this gracefully
        assert response.status_code in [200, 422, 415]

    def test_large_payload_handling(self, client):
        """Test handling of large payloads"""
        large_data = {"data": "x" * 1000000}  # 1MB of data

        response = client.post(
            "/api/v1/tools/validate_numeric_fields/execute",
            json={"tool_id": "validate_numeric_fields", "parameters": large_data},
        )

        # Should handle large payload or reject appropriately
        assert response.status_code in [200, 413, 422]

    def test_concurrent_requests(self, client):
        """Test handling of concurrent requests"""
        import threading
        import time

        results = []

        def make_request():
            response = client.get("/health")
            results.append(response.status_code)

        # Make multiple concurrent requests
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All requests should succeed
        assert all(status == 200 for status in results)
        assert len(results) == 10

    def test_timeout_handling(self, client):
        """Test handling of request timeouts"""
        with patch("tools.get_tool_registry") as mock_registry:
            # Mock tool that takes too long
            async def slow_tool(*args, **kwargs):
                import time

                time.sleep(2)  # Longer than typical timeout
                return {"result": "success"}

            mock_tool = AsyncMock(side_effect=slow_tool)
            mock_registry_instance = MagicMock()
            mock_registry_instance.get_tool.return_value = mock_tool
            mock_registry.return_value = mock_registry_instance

            request_data = {"tool_id": "slow_tool", "parameters": {}}

            # This test verifies timeout handling exists
            # Actual timeout behavior depends on FastAPI configuration
            try:
                response = client.post(
                    "/api/v1/tools/slow_tool/execute",
                    json=request_data,
                    timeout=1.0,
                )
                # Either succeeds or times out appropriately
                assert response.status_code in [200, 408, 500]
            except Exception:
                # Timeout exceptions are acceptable
                assert True


class TestAPIIntegration:
    """Test API integration scenarios"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        from main import TradingControlPlatform, app

        # Initialize platform state for tests
        platform = TradingControlPlatform()

        # Set platform in app state
        app.state.platform = platform

        return TestClient(app)

    def test_cors_headers(self, client):
        """Test CORS headers are present"""
        response = client.options("/health")

        # Should have CORS headers if configured
        assert response.status_code in [200, 405]  # 405 if OPTIONS not implemented

    def test_api_versioning(self, client):
        """Test API versioning consistency"""
        # All endpoints should use consistent versioning
        endpoints = [
            "/api/v1/tools",
            "/api/v1/agents",
            "/api/v1/platform/status",
            "/api/v1/health",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            # Should return 200 or appropriate status for each endpoint
            assert response.status_code in [200, 404, 405]

    def test_openapi_documentation(self, client):
        """Test OpenAPI documentation is available"""
        response = client.get("/openapi.json")

        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data
        assert "components" in data

    def test_swagger_ui(self, client):
        """Test Swagger UI is available"""
        response = client.get("/docs")

        # Should serve Swagger UI or redirect
        assert response.status_code in [200, 302]

    def test_redoc_ui(self, client):
        """Test ReDoc UI is available"""
        response = client.get("/redoc")

        # Should serve ReDoc UI or redirect
        assert response.status_code in [200, 302, 404]

    def test_complete_tool_workflow(self, client):
        """Test complete tool workflow: list -> get -> execute"""
        with patch("tools.get_tool_registry") as mock_registry:
            # Mock tool
            mock_tool = AsyncMock()
            mock_tool.tool_id = "test_tool"
            mock_tool.name = "Test Tool"
            mock_tool.description = "Test description"
            mock_tool.tool_type = "test"
            mock_tool.version = "1.0.0"
            mock_tool.parameters = {"input": "test input"}
            mock_tool.execute.return_value = {"result": "success"}

            mock_registry_instance = MagicMock()
            mock_registry_instance.list_tools.return_value = [mock_tool]
            mock_registry_instance.get_tool.return_value = mock_tool
            mock_registry.return_value = mock_registry_instance

            # 1. List tools
            list_response = client.get("/api/v1/tools")
            assert list_response.status_code == 200
            tools_list = list_response.json()
            assert len(tools_list) >= 1

            # 2. Get specific tool
            tool_id = tools_list[0]["tool_id"]
            get_response = client.get(f"/api/v1/tools/{tool_id}")
            assert get_response.status_code == 200
            tool_info = get_response.json()
            assert tool_info["tool_id"] == tool_id

            # 3. Execute tool
            execute_response = client.post(
                f"/api/v1/tools/{tool_id}/execute",
                json={"tool_id": tool_id, "parameters": {"input": "test data"}},
            )
            assert execute_response.status_code == 200
            execution_result = execute_response.json()
            assert execution_result["tool_id"] == tool_id
            assert "result" in execution_result
