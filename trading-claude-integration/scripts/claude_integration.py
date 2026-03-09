"""
Claude Code Integration Scripts
Production trading system integration with Claude Code
"""

from __future__ import annotations
import asyncio
import json
from typing import Dict, Any, List
from datetime import datetime

from production_trading_system import ProductionTradingAPI
from trading_data_validation.scripts.field_validator import ValidateNumericFields
from trading_system_monitoring.scripts.health_checker import HealthChecker


class ClaudeCodeIntegration:
    """
    Integration layer between Claude Code and production trading system
    Handles slash commands, MCP integrations, and automated workflows
    """
    
    def __init__(self):
        self.api = ProductionTradingAPI()
        self.validator = ValidateNumericFields()
        self.health_checker = HealthChecker()
        self.initialized = False
    
    async def initialize(self):
        """Initialize Claude Code integration"""
        if not self.initialized:
            await self.api.initialize()
            self.initialized = True
    
    async def handle_analyze_command(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle /analyze-trading command"""
        await self.initialize()
        
        symbol = params.get("symbol")
        if not symbol:
            return {"error": "Symbol parameter required"}
        
        indicators = params.get("indicators", ["RSI", "MACD"])
        timeframe = params.get("timeframe", "1d")
        
        try:
            result = await self.api.analyze_symbol(symbol, "comprehensive_analysis")
            
            return {
                "status": "success",
                "symbol": symbol,
                "analysis": result,
                "indicators_used": indicators,
                "timeframe": timeframe,
                "timestamp": result.get("executed_at"),
                "claude_context": {
                    "command": "/analyze-trading",
                    "parameters": params,
                    "execution_time_ms": result.get("execution_time_ms", 0)
                }
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "symbol": symbol,
                "claude_context": {
                    "command": "/analyze-trading",
                    "error_occurred": True
                }
            }
    
    async def handle_validate_command(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle /validate-market-data command"""
        source = params.get("source")
        symbol = params.get("symbol")
        
        if not source or not symbol:
            return {"error": "Source and symbol parameters required"}
        
        try:
            # Fetch market data from source
            market_data = await self._fetch_market_data(source, symbol)
            
            # Validate data quality
            validation_result = await self.validator.execute(market_data, source)
            
            return {
                "status": "success",
                "source": source,
                "symbol": symbol,
                "validation": validation_result,
                "data_quality_score": validation_result.get("quality_score", 0),
                "claude_context": {
                    "command": "/validate-market-data",
                    "parameters": params,
                    "validation_rules": ["numeric_fields", "required_fields"]
                }
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "source": source,
                "symbol": symbol,
                "claude_context": {
                    "command": "/validate-market-data",
                    "error_occurred": True
                }
            }
    
    async def handle_health_command(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle /portfolio-health command"""
        detailed = params.get("detailed", False)
        
        try:
            health_status = await self.health_checker.check_system_health()
            
            result = {
                "status": "success",
                "health": health_status,
                "summary": {
                    "overall_score": health_status.get("overall_score"),
                    "status": health_status.get("status"),
                    "alerts_count": len(health_status.get("alerts", [])),
                    "components_checked": len(health_status.get("checks", {}))
                },
                "claude_context": {
                    "command": "/portfolio-health",
                    "parameters": params,
                    "health_check_time": datetime.now().isoformat()
                }
            }
            
            if detailed:
                # Add detailed metrics
                system_metrics = await self.api.get_system_metrics()
                result["system_metrics"] = system_metrics
                result["detailed_view"] = True
            
            return result
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "claude_context": {
                    "command": "/portfolio-health",
                    "error_occurred": True
                }
            }
    
    async def handle_batch_analysis(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle batch analysis for multiple symbols"""
        symbols = params.get("symbols", [])
        if not symbols:
            return {"error": "Symbols parameter required"}
        
        indicators = params.get("indicators", ["RSI", "MACD"])
        
        try:
            await self.initialize()
            
            results = []
            for symbol in symbols:
                result = await self.api.analyze_symbol(symbol, "comprehensive_analysis")
                results.append({
                    "symbol": symbol,
                    "analysis": result,
                    "status": result.get("status", "unknown")
                })
            
            return {
                "status": "success",
                "symbols_analyzed": symbols,
                "results": results,
                "indicators_used": indicators,
                "summary": {
                    "total_symbols": len(symbols),
                    "successful_analyses": len([r for r in results if r["status"] == "completed"]),
                    "failed_analyses": len([r for r in results if r["status"] == "failed"])
                },
                "claude_context": {
                    "command": "batch-analysis",
                    "parameters": params,
                    "batch_size": len(symbols)
                }
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "claude_context": {
                    "command": "batch-analysis",
                    "error_occurred": True
                }
            }
    
    async def handle_risk_assessment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle portfolio risk assessment"""
        portfolio = params.get("portfolio", {})
        risk_tolerance = params.get("risk_tolerance", "medium")
        
        try:
            # This would integrate with risk assessment logic
            risk_score = self._calculate_portfolio_risk(portfolio)
            risk_level = self._assess_risk_level(risk_score, risk_tolerance)
            
            return {
                "status": "success",
                "risk_score": risk_score,
                "risk_level": risk_level,
                "risk_tolerance": risk_tolerance,
                "recommendations": self._generate_risk_recommendations(risk_score, risk_tolerance),
                "claude_context": {
                    "command": "risk-assessment",
                    "parameters": params,
                    "assessment_time": datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "claude_context": {
                    "command": "risk-assessment",
                    "error_occurred": True
                }
            }
    
    async def _fetch_market_data(self, source: str, symbol: str) -> Dict[str, Any]:
        """Fetch market data from specified source"""
        # This would integrate with actual data sources
        # For now, return mock data
        return {
            "symbol": symbol,
            "price": 175.43,
            "volume": 1000000,
            "change": 1.25,
            "change_percent": 0.72,
            "timestamp": datetime.now().isoformat(),
            "source": source
        }
    
    def _calculate_portfolio_risk(self, portfolio: Dict[str, Any]) -> float:
        """Calculate portfolio risk score (0-100)"""
        # Simplified risk calculation
        positions = portfolio.get("positions", [])
        if not positions:
            return 0.0
        
        # Calculate concentration risk
        total_value = sum(pos.get("value", 0) for pos in positions)
        if total_value == 0:
            return 0.0
        
        concentration_risk = 0
        for pos in positions:
            weight = pos.get("value", 0) / total_value
            concentration_risk += weight ** 2  # Herfindahl index
        
        # Convert to 0-100 scale
        risk_score = concentration_risk * 100
        return min(100.0, max(0.0, risk_score))
    
    def _assess_risk_level(self, risk_score: float, tolerance: str) -> str:
        """Assess risk level based on score and tolerance"""
        tolerance_thresholds = {
            "low": 20,
            "medium": 50,
            "high": 80
        }
        
        threshold = tolerance_thresholds.get(tolerance, 50)
        
        if risk_score < threshold:
            return "low"
        elif risk_score < threshold * 1.5:
            return "medium"
        else:
            return "high"
    
    def _generate_risk_recommendations(self, risk_score: float, tolerance: str) -> List[str]:
        """Generate risk recommendations"""
        recommendations = []
        
        if risk_score > 70:
            recommendations.append("Consider diversifying portfolio to reduce concentration risk")
            recommendations.append("Review position sizes and consider rebalancing")
        
        if risk_score > 50 and tolerance == "low":
            recommendations.append("Portfolio risk exceeds your tolerance level")
            recommendations.append("Consider reducing exposure to volatile positions")
        
        if risk_score < 30:
            recommendations.append("Portfolio appears well-diversified")
            recommendations.append("Consider if risk level aligns with investment goals")
        
        return recommendations


# Claude Code command handler factory
def create_claude_integration() -> ClaudeCodeIntegration:
    """Create Claude Code integration instance"""
    return ClaudeCodeIntegration()


# Command registry for Claude Code
CLAUDE_COMMANDS = {
    "analyze-trading": "handle_analyze_command",
    "validate-market-data": "handle_validate_command", 
    "portfolio-health": "handle_health_command",
    "batch-analysis": "handle_batch_analysis",
    "risk-assessment": "handle_risk_assessment"
}


# MCP integration handlers
class MCPIntegrationHandler:
    """Handle MCP (Model Context Protocol) integrations"""
    
    def __init__(self):
        self.integrations = {
            "trading-data-mcp": self._handle_trading_data_mcp,
            "portfolio-database-mcp": self._handle_portfolio_database_mcp,
            "notification-mcp": self._handle_notification_mcp
        }
    
    async def handle_mcp_request(self, mcp_name: str, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP request"""
        if mcp_name not in self.integrations:
            return {"error": f"Unknown MCP: {mcp_name}"}
        
        handler = self.integrations[mcp_name]
        return await handler(request)
    
    async def _handle_trading_data_mcp(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle trading data MCP requests"""
        action = request.get("action")
        
        if action == "get_market_data":
            symbol = request.get("symbol")
            source = request.get("source", "alpha_vantage")
            
            # Fetch market data
            integration = create_claude_integration()
            data = await integration._fetch_market_data(source, symbol)
            
            return {
                "status": "success",
                "data": data,
                "mcp": "trading-data-mcp"
            }
        
        return {"error": "Unknown action for trading-data-mcp"}
    
    async def _handle_portfolio_database_mcp(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle portfolio database MCP requests"""
        action = request.get("action")
        
        if action == "get_positions":
            # This would query actual database
            return {
                "status": "success",
                "positions": [
                    {"symbol": "AAPL", "shares": 100, "value": 17543},
                    {"symbol": "MSFT", "shares": 50, "value": 8500}
                ],
                "mcp": "portfolio-database-mcp"
            }
        
        return {"error": "Unknown action for portfolio-database-mcp"}
    
    async def _handle_notification_mcp(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle notification MCP requests"""
        action = request.get("action")
        
        if action == "send_alert":
            message = request.get("message")
            channel = request.get("channel", "slack")
            
            # This would send actual notification
            return {
                "status": "success",
                "message": f"Alert sent to {channel}: {message}",
                "mcp": "notification-mcp"
            }
        
        return {"error": "Unknown action for notification-mcp"}
