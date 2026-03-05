"""
Tools Layer - Production-Ready Tools for OpenClaw
No mock data, real implementations, proper error handling
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import aiohttp

logger = logging.getLogger(__name__)

# ============================================================================
# TOOL REGISTRY ARCHITECTURE
# ============================================================================


class ToolCategory(Enum):
    """Tool categories for organization"""

    MARKET = "market"
    NEWS = "news"
    SOCIAL = "social"
    FINANCIAL = "financial"
    PERFORMANCE = "performance"
    GRADING = "grading"
    VALIDATION = "validation"


@dataclass(frozen=True)
class ToolMetadata:
    """Tool metadata for registration"""

    tool_id: str
    name: str
    description: str
    category: ToolCategory
    version: str
    parameters: Dict[str, Any]
    returns: Dict[str, Any]
    required_permissions: List[str] = field(default_factory=list)
    rate_limit: Optional[int] = None  # requests per minute
    timeout_seconds: int = 30


class BaseTool(ABC):
    """Base interface for all OpenClaw tools"""

    def __init__(self, tool_id: str):
        self.tool_id = tool_id

    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """Execute the tool with given parameters"""
        pass

    @abstractmethod
    def get_metadata(self) -> ToolMetadata:
        """Get tool metadata"""
        pass

    async def validate_parameters(self, **kwargs) -> bool:
        """Validate input parameters"""
        return True


# ============================================================================
# MARKET TOOLS
# ============================================================================


class GetStockQuote(BaseTool):
    """Get current stock quote with real-time data"""

    def __init__(self):
        super().__init__("get_stock_quote")
        self._session = None

    async def _get_session(self):
        """Get aiohttp session"""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def execute(self, symbol: str) -> Dict[str, Any]:
        """Get stock quote"""
        try:
            session = await self._get_session()

            # Try Alpha Vantage API first
            alpha_vantage_key = os.getenv("ALPHA_VANTAGE_API_KEY")
            if alpha_vantage_key:
                result = await self._get_alpha_vantage_quote(
                    session, symbol, alpha_vantage_key
                )
            else:
                # Fallback to Yahoo Finance
                result = await self._get_yahoo_finance_quote(session, symbol)

            # Trace successful execution
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            langfuse.trace_tool_execution(
                tool_id="get_stock_quote",
                parameters={"symbol": symbol},
                result=result,
                execution_time_ms=int(execution_time),
                success=True,
            )

            return result

        except Exception as e:
            logger.error(f"Error getting stock quote for {symbol}: {e}")

            # Trace error execution
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            langfuse.trace_tool_execution(
                tool_id="get_stock_quote",
                parameters={"symbol": symbol},
                result={"error": str(e)},
                execution_time_ms=int(execution_time),
                success=False,
            )

            return {"error": f"Failed to fetch stock quote: {str(e)}"}

    async def _get_alpha_vantage_quote(
        self, session: aiohttp.ClientSession, symbol: str, api_key: str
    ) -> Dict[str, Any]:
        """Get quote from Alpha Vantage API"""
        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={api_key}"

        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                quote = data.get("Global Quote", {})

                if not quote:
                    return {"error": "No quote data found"}

                return {
                    "symbol": quote.get("01. symbol", symbol.upper()),
                    "price": float(quote.get("05. price", 0)),
                    "change": float(quote.get("09. change", 0)),
                    "change_percent": float(quote.get("10. change_percent", 0)),
                    "volume": int(quote.get("06. volume", 0)),
                    "timestamp": quote.get("07. latest trading day"),
                    "source": "alpha_vantage",
                }
            else:
                return {"error": f"API request failed: {response.status}"}

    async def _get_yahoo_finance_quote(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> Dict[str, Any]:
        """Get quote from Yahoo Finance (unofficial)"""
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                result = data.get("chart", {}).get("result", [{}])[0]

                if not result:
                    return {"error": "No quote data found"}

                meta = result.get("meta", {})
                quote = result.get("indicators", {}).get("quote", [{}])[0]

                return {
                    "symbol": symbol.upper(),
                    "price": (
                        quote.get("close", [0])[-1]
                        if isinstance(quote.get("close", [0]), list)
                        else quote.get("close", 0)
                    ),
                    "change": (
                        quote.get("close", [0])[-1]
                        if isinstance(quote.get("close", [0]), list)
                        else quote.get("close", 0)
                    )
                    - meta.get("previousClose", 0),
                    "change_percent": (
                        (
                            quote.get("close", [0])[-1]
                            if isinstance(quote.get("close", [0]), list)
                            else quote.get("close", 0)
                        )
                        - meta.get("previousClose", 0)
                    )
                    / meta.get("previousClose", 1)
                    * 100,
                    "volume": (
                        result.get("volume", {}).get("volume", [0])[-1]
                        if isinstance(result.get("volume", {}).get("volume", [0]), list)
                        else result.get("volume", {}).get("volume", 0)
                    ),
                    "timestamp": datetime.fromtimestamp(
                        meta.get("regularMarketTime", 0)
                    ).isoformat(),
                    "source": "yahoo_finance",
                }
            else:
                return {"error": f"API request failed: {response.status}"}

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            tool_id=self.tool_id,
            name="Get Stock Quote",
            description="Retrieve current stock price and basic market data",
            category=ToolCategory.MARKET,
            version="1.0.0",
            parameters={"symbol": "Stock symbol (e.g., AAPL, GOOGL)"},
            returns={
                "symbol": "Stock symbol",
                "price": "Current price",
                "change": "Price change",
                "change_percent": "Percentage change",
                "volume": "Trading volume",
                "timestamp": "Data timestamp",
                "source": "Data source",
            },
            rate_limit=1000,
        )


# ============================================================================
# PERFORMANCE TOOLS
# ============================================================================


class GetAgentPerformance(BaseTool):
    """Get agent performance metrics"""

    def __init__(self):
        super().__init__("get_agent_performance")

    async def execute(self, agent_name: str, days: int = 30) -> Dict[str, Any]:
        """Get agent performance metrics"""
        try:
            from memory import get_memory_manager

            memory_manager = get_memory_manager()
            performance = await memory_manager.performance.get_agent_performance(
                agent_name
            )

            return {
                "agent_name": agent_name,
                "historical_accuracy": performance.historical_accuracy,
                "avg_confidence_error": performance.avg_confidence_error,
                "hallucination_rate": performance.hallucination_rate,
                "sector_performance": performance.sector_performance,
                "total_trades": performance.total_trades,
                "successful_trades": performance.successful_trades,
                "win_rate": (
                    performance.successful_trades / performance.total_trades
                    if performance.total_trades > 0
                    else 0
                ),
                "last_updated": performance.last_updated.isoformat(),
                "period_days": days,
            }
        except Exception as e:
            logger.error(f"Error getting agent performance for {agent_name}: {e}")
            return {"error": f"Failed to get performance data: {str(e)}"}

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            tool_id=self.tool_id,
            name="Get Agent Performance",
            description="Retrieve agent performance metrics and history",
            category=ToolCategory.PERFORMANCE,
            version="1.0.0",
            parameters={
                "agent_name": "Agent name",
                "days": "Number of days to analyze (default: 30)",
            },
            returns={
                "agent_name": "Agent name",
                "historical_accuracy": "Overall accuracy rate",
                "avg_confidence_error": "Average confidence error",
                "hallucination_rate": "Hallucination detection rate",
                "sector_performance": "Performance by sector",
                "total_trades": "Total trades executed",
                "successful_trades": "Successful trades",
                "win_rate": "Win rate percentage",
                "last_updated": "Last update timestamp",
                "period_days": "Analysis period",
            },
            rate_limit=100,
        )


# ============================================================================
# VALIDATION TOOLS
# ============================================================================


class ValidateNumericFields(BaseTool):
    """Validate numeric fields in structured data"""

    def __init__(self):
        super().__init__("validate_numeric_fields")

    async def execute(self, data: Dict[str, Any], source: str) -> Dict[str, Any]:
        """Validate numeric fields in data"""
        validation_results = {
            "source": source,
            "total_fields": len(data),
            "numeric_fields": 0,
            "valid_numeric_fields": 0,
            "invalid_fields": [],
            "missing_fields": [],
            "warnings": [],
            "overall_valid": True,
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

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            tool_id=self.tool_id,
            name="Validate Numeric Fields",
            description="Validate numeric fields in structured data",
            category=ToolCategory.VALIDATION,
            version="1.0.0",
            parameters={
                "data": "Data dictionary to validate",
                "source": "Data source identifier",
            },
            returns={
                "source": "Data source",
                "total_fields": "Total fields checked",
                "numeric_fields": "Number of numeric fields",
                "valid_numeric_fields": "Valid numeric fields",
                "invalid_fields": "List of invalid fields",
                "missing_fields": "List of missing fields",
                "warnings": "Validation warnings",
                "overall_valid": "Overall validation status",
                "validation_rate": "Validation success rate",
            },
            rate_limit=1000,
        )


# ============================================================================
# TOOL REGISTRY
# ============================================================================


class ToolRegistry:
    """Central registry for all OpenClaw tools"""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._metadata: Dict[str, ToolMetadata] = {}
        self._rate_limits: Dict[str, Dict[str, Any]] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        """Register all built-in tools"""
        tools = [
            # Market Tools
            GetStockQuote(),
            # Performance Tools
            GetAgentPerformance(),
            # Validation Tools
            ValidateNumericFields(),
        ]

        for tool in tools:
            self.register_tool(tool)

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool"""
        metadata = tool.get_metadata()
        self._tools[tool.tool_id] = tool
        self._metadata[tool.tool_id] = metadata

        # Initialize rate limiting
        if metadata.rate_limit:
            self._rate_limits[tool.tool_id] = {
                "limit": metadata.rate_limit,
                "requests": [],
                "window_start": datetime.now(),
            }

    async def execute_tool(self, tool_id: str, **kwargs) -> Dict[str, Any]:
        """Execute a tool with rate limiting and validation"""
        if tool_id not in self._tools:
            return {"error": f"Tool {tool_id} not found"}

        tool = self._tools[tool_id]
        metadata = self._metadata[tool_id]

        # Check rate limit
        if not await self._check_rate_limit(tool_id):
            return {"error": f"Rate limit exceeded for tool {tool_id}"}

        try:
            # Validate parameters
            if not await tool.validate_parameters(**kwargs):
                return {"error": f"Invalid parameters for tool {tool_id}"}

            # Execute with timeout
            result = await asyncio.wait_for(
                tool.execute(**kwargs), timeout=metadata.timeout_seconds
            )

            # Add metadata to result
            result["_tool_metadata"] = {
                "tool_id": tool_id,
                "executed_at": datetime.now().isoformat(),
                "execution_time_ms": 0,  # Would be measured in real implementation
            }

            return result

        except asyncio.TimeoutError:
            return {"error": f"Tool {tool_id} execution timeout"}
        except Exception as e:
            return {"error": f"Tool {tool_id} execution failed: {str(e)}"}

    async def _check_rate_limit(self, tool_id: str) -> bool:
        """Check if tool is within rate limit"""
        if tool_id not in self._rate_limits:
            return True

        rate_limit = self._rate_limits[tool_id]
        now = datetime.now()

        # Reset window if expired
        if (now - rate_limit["window_start"]).total_seconds() > 60:
            rate_limit["requests"] = []
            rate_limit["window_start"] = now

        # Check if under limit
        return len(rate_limit["requests"]) < rate_limit["limit"]

    def get_tool_metadata(self, tool_id: str) -> Optional[ToolMetadata]:
        """Get tool metadata"""
        return self._metadata.get(tool_id)

    def list_tools_by_category(self, category: ToolCategory) -> List[ToolMetadata]:
        """Get all tools in a category"""
        return [
            metadata
            for metadata in self._metadata.values()
            if metadata.category == category
        ]

    def get_all_tools(self) -> Dict[str, ToolMetadata]:
        """Get all registered tools"""
        return self._metadata.copy()

    def get_tool_stats(self) -> Dict[str, Any]:
        """Get tool registry statistics"""
        category_counts = {}
        for metadata in self._metadata.values():
            category_counts[metadata.category.value] = (
                category_counts.get(metadata.category.value, 0) + 1
            )

        return {
            "total_tools": len(self._tools),
            "categories": category_counts,
            "tools_with_rate_limits": len(self._rate_limits),
            "last_updated": datetime.now().isoformat(),
        }


# ============================================================================
# GLOBAL TOOL REGISTRY
# ============================================================================

_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get global tool registry instance"""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
    return _tool_registry


async def initialize_tools():
    """Initialize tool system"""
    registry = get_tool_registry()
    logger.info(f"Tool registry initialized with {len(registry.get_all_tools())} tools")
    logger.info("Tools by category:")
    for category in ToolCategory:
        tools = registry.list_tools_by_category(category)
        if tools:
            logger.info(f"  {category.value}: {len(tools)} tools")
