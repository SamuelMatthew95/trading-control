"""
Test Suite for Tools Module
Comprehensive tests for tool registry and implementations
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import tools


class TestToolRegistry:
    """Test tool registry functionality"""

    def test_tool_registry_initialization(self):
        """Test tool registry initializes correctly"""
        registry = tools.ToolRegistry()

        assert registry is not None
        assert hasattr(registry, "register_tool")
        assert hasattr(registry, "get_all_tools")
        assert hasattr(registry, "list_tools_by_category")
        # Check that it has the default tools
        all_tools = registry.get_all_tools()
        assert len(all_tools) >= 3  # Should have the default tools

    def test_register_tool(self):
        """Test tool registration"""
        registry = tools.ToolRegistry(auto_register=False)

        # Create a mock tool
        mock_tool = MagicMock()
        mock_tool.tool_id = "test_tool"
        mock_tool.name = "Test Tool"
        mock_tool.description = "Test description"
        mock_tool.tool_type = tools.ToolCategory.MARKET
        mock_tool.version = "1.0.0"
        mock_tool.parameters = {"param1": "value1"}

        # Register tool
        registry.register_tool(mock_tool)

        assert len(registry.tools) == 1
        assert "test_tool" in registry.tools
        assert registry.tools["test_tool"] is mock_tool
        assert len(registry.tool_metadata) == 1
        assert "test_tool" in registry.tool_metadata

    def test_register_duplicate_tool(self):
        """Test registering duplicate tool"""
        registry = tools.ToolRegistry()

        mock_tool = MagicMock()
        mock_tool.tool_id = "duplicate_tool"

        # Register tool twice
        registry.register_tool(mock_tool)

        with pytest.raises(ValueError, match="Tool duplicate_tool already registered"):
            registry.register_tool(mock_tool)

    def test_get_tool(self):
        """Test getting tool from registry"""
        registry = tools.ToolRegistry()

        mock_tool = MagicMock()
        mock_tool.tool_id = "test_tool"
        mock_tool.name = "Test Tool"

        registry.register_tool(mock_tool)

        # Get existing tool
        retrieved_tool = registry.get_tool("test_tool")
        assert retrieved_tool is mock_tool
        assert retrieved_tool.name == "Test Tool"

        # Get non-existing tool
        with pytest.raises(ValueError, match="Tool non_existent_tool not found"):
            registry.get_tool("non_existent_tool")

    def test_list_tools(self):
        """Test listing all tools"""
        registry = tools.ToolRegistry(auto_register=False)

        # Register multiple tools
        for i in range(3):
            mock_tool = MagicMock()
            mock_tool.tool_id = f"tool_{i}"
            mock_tool.name = f"Tool {i}"
            mock_tool.tool_type = tools.ToolCategory.MARKET
            registry.register_tool(mock_tool)

        tools_list = registry.list_tools()
        assert len(tools_list) == 3
        assert all(hasattr(tool, "tool_id") for tool in tools_list)
        assert all(hasattr(tool, "name") for tool in tools_list)

    def test_get_tools_by_category(self):
        """Test getting tools by category"""
        registry = tools.ToolRegistry(auto_register=False)

        # Register tools with different categories
        market_tool = MagicMock()
        market_tool.tool_id = "market_tool"
        market_tool.tool_type = tools.ToolCategory.MARKET

        performance_tool = MagicMock()
        performance_tool.tool_id = "performance_tool"
        performance_tool.tool_type = tools.ToolCategory.PERFORMANCE

        registry.register_tool(market_tool)
        registry.register_tool(performance_tool)

        market_tools = registry.get_tools_by_category(tools.ToolCategory.MARKET)
        performance_tools = registry.get_tools_by_category(
            tools.ToolCategory.PERFORMANCE
        )

        assert len(market_tools) == 1
        assert len(performance_tools) == 1
        assert market_tools[0].tool_id == "market_tool"
        assert performance_tools[0].tool_id == "performance_tool"


class TestToolCategories:
    """Test tool categories enum"""

    def test_tool_category_values(self):
        """Test tool category enum has expected values"""
        assert tools.ToolCategory.MARKET.value == "market"
        assert tools.ToolCategory.NEWS.value == "news"
        assert tools.ToolCategory.PERFORMANCE.value == "performance"
        assert tools.ToolCategory.VALIDATION.value == "validation"

    def test_tool_category_count(self):
        """Test tool category has correct number of values"""
        categories = list(tools.ToolCategory)
        assert len(categories) >= 4  # At least 4 categories
        assert tools.ToolCategory.MARKET in categories
        assert tools.ToolCategory.NEWS in categories
        assert tools.ToolCategory.PERFORMANCE in categories
        assert tools.ToolCategory.VALIDATION in categories


class TestGetStockQuote:
    """Test GetStockQuote tool implementation"""

    @pytest.fixture
    def stock_quote_tool(self):
        """Create GetStockQuote tool instance"""
        return tools.GetStockQuote()

    @pytest.mark.asyncio
    async def test_tool_metadata(self, stock_quote_tool):
        """Test tool has correct metadata"""
        assert stock_quote_tool.tool_id == "get_stock_quote"
        assert stock_quote_tool.name == "Get Stock Quote"
        assert "stock" in stock_quote_tool.description.lower()
        assert stock_quote_tool.tool_type == tools.ToolCategory.MARKET
        assert stock_quote_tool.version == "1.0.0"
        assert "symbol" in stock_quote_tool.parameters

    @pytest.mark.asyncio
    async def test_execute_success_alpha_vantage(self, stock_quote_tool):
        """Test successful execution with Alpha Vantage"""
        mock_response = {
            "Global Quote": {
                "01. symbol": "AAPL",
                "05. price": "175.43",
                "09. change": "+1.25",
                "10. change percent": "0.72%",
            }
        }

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.return_value.__aenter__.return_value.status = 200
            mock_get.return_value.__aenter__.return_value.json = AsyncMock(
                return_value=mock_response
            )

            with patch.dict(os.environ, {"ALPHA_VANTAGE_API_KEY": "test_key"}):
                result = await stock_quote_tool.execute("AAPL")

                assert "price" in result
                assert result["price"] == "175.43"
                assert result["symbol"] == "AAPL"
                assert result["source"] == "alpha_vantage"
                assert "error" not in result

    @pytest.mark.asyncio
    async def test_execute_success_yahoo_fallback(self, stock_quote_tool):
        """Test successful execution with Yahoo Finance fallback"""
        mock_response = {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "AAPL"},
                        "indicators": {"quote": [{"close": 175.43}]},
                    }
                ]
            }
        }

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.return_value.__aenter__.return_value.status = 200
            mock_get.return_value.__aenter__.return_value.json = AsyncMock(
                return_value=mock_response
            )

            with patch.dict(os.environ, {}, clear=True):  # No Alpha Vantage key
                result = await stock_quote_tool.execute("AAPL")

                assert "price" in result
                assert result["price"] == 175.43
                assert result["symbol"] == "AAPL"
                assert result["source"] == "yahoo_finance"
                assert "error" not in result

    @pytest.mark.asyncio
    async def test_execute_api_error(self, stock_quote_tool):
        """Test execution with API error"""
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.return_value.__aenter__.return_value.status = 500
            mock_get.return_value.__aenter__.return_value.json = AsyncMock(
                side_effect=Exception("API Error")
            )

            result = await stock_quote_tool.execute("AAPL")

            assert "error" in result
            assert "Failed to fetch stock quote" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_invalid_symbol(self, stock_quote_tool):
        """Test execution with invalid symbol"""
        mock_response = {"Global Quote": {}}

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.return_value.__aenter__.return_value.status = 200
            mock_get.return_value.__aenter__.return_value.json = AsyncMock(
                return_value=mock_response
            )

            result = await stock_quote_tool.execute("INVALID")

            assert "error" in result
            assert "No quote data found" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_empty_symbol(self, stock_quote_tool):
        """Test execution with empty symbol"""
        result = await stock_quote_tool.execute("")

        assert "error" in result
        assert "Symbol is required" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_none_symbol(self, stock_quote_tool):
        """Test execution with None symbol"""
        result = await stock_quote_tool.execute(None)

        assert "error" in result
        assert "Symbol is required" in result["error"]


class TestGetAgentPerformance:
    """Test GetAgentPerformance tool implementation"""

    @pytest.fixture
    def performance_tool(self):
        """Create GetAgentPerformance tool instance"""
        return tools.GetAgentPerformance()

    @pytest.mark.asyncio
    async def test_performance_tool_metadata(self, performance_tool):
        """Test performance tool has correct metadata"""
        assert performance_tool.tool_id == "get_agent_performance"
        assert "performance" in performance_tool.name.lower()
        assert performance_tool.tool_type == tools.ToolCategory.PERFORMANCE
        assert "agent_name" in performance_tool.parameters
        assert "days" in performance_tool.parameters

    @pytest.mark.asyncio
    async def test_execute_success(self, performance_tool):
        """Test successful performance retrieval"""
        result = await performance_tool.execute("test_agent", 30)

        assert "agent_name" in result
        assert result["agent_name"] == "test_agent"
        assert "period_days" in result
        assert result["period_days"] == 30
        assert "metrics" in result
        assert "tasks_completed" in result["metrics"]
        assert "success_rate" in result["metrics"]
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_execute_with_defaults(self, performance_tool):
        """Test execution with default parameters"""
        result = await performance_tool.execute("test_agent")

        assert result["period_days"] == 30  # Default value
        assert "metrics" in result

    @pytest.mark.asyncio
    async def test_execute_invalid_days(self, performance_tool):
        """Test execution with invalid days parameter"""
        result = await performance_tool.execute("test_agent", -5)

        assert "error" in result
        assert "Days must be positive" in result["error"]


class TestValidateNumericFields:
    """Test ValidateNumericFields tool implementation"""

    @pytest.fixture
    def validation_tool(self):
        """Create ValidateNumericFields tool instance"""
        return tools.ValidateNumericFields()

    @pytest.mark.asyncio
    async def test_validation_tool_metadata(self, validation_tool):
        """Test validation tool has correct metadata"""
        assert validation_tool.tool_id == "validate_numeric_fields"
        assert "validation" in validation_tool.name.lower()
        assert validation_tool.tool_type == tools.ToolCategory.VALIDATION
        assert "data" in validation_tool.parameters
        assert "source" in validation_tool.parameters

    @pytest.mark.asyncio
    async def test_execute_valid_data(self, validation_tool):
        """Test execution with valid data"""
        test_data = {
            "price": 175.43,
            "volume": 1000000,
            "change": 1.25,
            "change_percent": 0.72,
        }

        result = await validation_tool.execute(test_data, "test_source")

        assert result["valid"] is True
        assert result["validated_fields"] == [
            "price",
            "volume",
            "change",
            "change_percent",
        ]
        assert result["source"] == "test_source"
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_execute_invalid_data(self, validation_tool):
        """Test execution with invalid data"""
        test_data = {
            "price": "not_a_number",
            "volume": None,
            "change": float("inf"),
            "change_percent": float("nan"),
        }

        result = await validation_tool.execute(test_data, "test_source")

        assert result["valid"] is False
        assert "invalid_fields" in result
        assert len(result["invalid_fields"]) > 0
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_execute_empty_data(self, validation_tool):
        """Test execution with empty data"""
        result = await validation_tool.execute({}, "test_source")

        assert result["valid"] is True  # Empty data is valid
        assert result["validated_fields"] == []

    @pytest.mark.asyncio
    async def test_execute_none_data(self, validation_tool):
        """Test execution with None data"""
        result = await validation_tool.execute(None, "test_source")

        assert "error" in result
        assert "Data is required" in result["error"]


class TestToolIntegration:
    """Test tool integration and registry"""

    @pytest.mark.asyncio
    async def test_initialize_tools(self):
        """Test tools initialization"""
        # Should not raise any exceptions
        await tools.initialize_tools()

        # Registry should be populated
        registry = tools.get_tool_registry()
        assert len(registry.tools) >= 3  # At least 3 default tools

        # Check for expected tools
        expected_tools = [
            "get_stock_quote",
            "get_agent_performance",
            "validate_numeric_fields",
        ]
        for tool_id in expected_tools:
            assert tool_id in registry.tools

    def test_get_tool_registry(self):
        """Test getting global tool registry"""
        registry = tools.get_tool_registry()

        assert registry is not None
        assert hasattr(registry, "tools")
        assert hasattr(registry, "get_tool")
        assert hasattr(registry, "list_tools")

    @pytest.mark.asyncio
    async def test_tool_execution_flow(self):
        """Test complete tool execution flow"""
        await tools.initialize_tools()
        registry = tools.get_tool_registry()

        # Get stock quote tool
        stock_tool = registry.get_tool("get_stock_quote")
        assert stock_tool is not None
        assert stock_tool.tool_id == "get_stock_quote"

        # Check tool has required methods
        assert hasattr(stock_tool, "execute")
        assert callable(getattr(stock_tool, "execute"))


class TestToolErrorHandling:
    """Test tool error handling and edge cases"""

    @pytest.mark.asyncio
    async def test_network_timeout_handling(self):
        """Test handling of network timeouts"""
        tool = tools.GetStockQuote()

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.return_value.__aenter__.return_value.status = 408
            mock_get.return_value.__aenter__.return_value.json = AsyncMock(
                side_effect=asyncio.TimeoutError("Timeout")
            )

            result = await tool.execute("AAPL")

            assert "error" in result
            assert "timeout" in result["error"].lower() or "Failed" in result["error"]

    @pytest.mark.asyncio
    async def test_malformed_response_handling(self):
        """Test handling of malformed API responses"""
        tool = tools.GetStockQuote()

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.return_value.__aenter__.return_value.status = 200
            mock_get.return_value.__aenter__.return_value.json = AsyncMock(
                side_effect=ValueError("No JSON object could be decoded")
            )

            result = await tool.execute("AAPL")

            assert "error" in result
            assert "Failed" in result["error"]

    @pytest.mark.asyncio
    async def test_rate_limiting_handling(self):
        """Test handling of rate limiting"""
        tool = tools.GetStockQuote()

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.return_value.__aenter__.return_value.status = 429
            mock_get.return_value.__aenter__.return_value.json = AsyncMock(
                return_value={"error": "Rate limit exceeded"}
            )

            result = await tool.execute("AAPL")

            assert "error" in result
            assert (
                "rate limit" in result["error"].lower() or "Failed" in result["error"]
            )
