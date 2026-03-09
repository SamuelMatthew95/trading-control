"""
Claude Code Template for Trading System Orchestration
Integrates production-grade trading system with Claude Code
"""

import json
from typing import Any, Dict, List


class TradingSystemClaudeTemplate:
    """
    Claude Code template for trading system orchestration
    Bridges our production SDK with Claude's orchestration capabilities
    """

    def __init__(self):
        self.template_id = "trading-system-orchestrator"
        self.version = "1.0.0"

    def get_agent_definition(self) -> Dict[str, Any]:
        """Agent definition for Claude Code templates"""
        return {
            "name": "Trading System Orchestrator",
            "description": "Production-grade trading system with market analysis, data validation, and technical indicators",
            "category": "finance/trading",
            "version": self.version,
            "author": "Trading System Team",
            "capabilities": [
                "Real-time market data analysis",
                "Multi-source data validation",
                "Technical indicator calculations",
                "Risk assessment and signaling",
                "Portfolio optimization",
            ],
            "skills": [
                "trading-market-data",
                "trading-data-validation",
                "trading-agent-orchestration",
                "trading-system-monitoring",
            ],
            "configuration": {
                "agent_ceiling": 5,
                "observability_level": "full",
                "retry_policy": "exponential_backoff",
                "timeout_settings": {
                    "market_data": 5000,
                    "validation": 2000,
                    "analysis": 8000,
                },
            },
            "integration_points": {
                "claude_sdk": True,
                "mcp_support": ["postgresql", "redis", "websocket"],
                "api_endpoints": [
                    "/api/v1/analyze/{symbol}",
                    "/api/v1/portfolio/optimize",
                    "/api/v1/health/status",
                ],
            },
        }

    def get_command_definitions(self) -> List[Dict[str, Any]]:
        """Custom slash commands for Claude Code"""
        return [
            {
                "name": "analyze-trading",
                "description": "Analyze trading symbol with comprehensive technical analysis",
                "usage": "/analyze-trading AAPL --indicators=RSI,MACD,BB --timeframe=1d",
                "parameters": {
                    "symbol": {
                        "type": "string",
                        "required": True,
                        "description": "Trading symbol",
                    },
                    "indicators": {
                        "type": "array",
                        "default": ["RSI", "MACD"],
                        "description": "Technical indicators",
                    },
                    "timeframe": {
                        "type": "string",
                        "default": "1d",
                        "description": "Analysis timeframe",
                    },
                },
                "implementation": self._implement_analyze_command,
            },
            {
                "name": "validate-market-data",
                "description": "Validate market data quality and integrity",
                "usage": "/validate-market-data --source=alpha_vantage --symbol=AAPL",
                "parameters": {
                    "source": {
                        "type": "string",
                        "required": True,
                        "description": "Data source",
                    },
                    "symbol": {
                        "type": "string",
                        "required": True,
                        "description": "Trading symbol",
                    },
                },
                "implementation": self._implement_validate_command,
            },
            {
                "name": "portfolio-health",
                "description": "Check portfolio health and system status",
                "usage": "/portfolio-health --detailed",
                "parameters": {
                    "detailed": {
                        "type": "boolean",
                        "default": False,
                        "description": "Show detailed metrics",
                    }
                },
                "implementation": self._implement_health_command,
            },
        ]

    def get_mcp_integrations(self) -> List[Dict[str, Any]]:
        """MCP (Model Context Protocol) integrations"""
        return [
            {
                "name": "trading-data-mcp",
                "description": "Real-time market data integration",
                "type": "external_api",
                "configuration": {
                    "endpoints": [
                        "alpha_vantage_market_data",
                        "yahoo_finance_stream",
                        "polygon_realtime",
                    ],
                    "authentication": "api_key",
                    "rate_limits": {"requests_per_minute": 100, "burst_limit": 20},
                },
            },
            {
                "name": "portfolio-database-mcp",
                "description": "Portfolio and trade tracking database",
                "type": "database",
                "configuration": {
                    "provider": "postgresql",
                    "connection_pool_size": 10,
                    "tables": ["trades", "positions", "market_data", "signals"],
                },
            },
            {
                "name": "notification-mcp",
                "description": "Trade alerts and notifications",
                "type": "webhook",
                "configuration": {
                    "channels": ["slack", "email", "telegram"],
                    "templates": ["trade_alert", "risk_warning", "portfolio_update"],
                },
            },
        ]

    def get_settings_configuration(self) -> Dict[str, Any]:
        """Claude Code settings for optimal performance"""
        return {
            "performance": {
                "timeout_ms": 30000,
                "memory_limit_mb": 2048,
                "concurrent_requests": 5,
                "cache_strategy": "lru_with_ttl",
            },
            "trading_specific": {
                "default_indicators": ["RSI", "MACD", "BollingerBands"],
                "risk_tolerance": "medium",
                "analysis_timeframe": "1d",
                "data_sources": ["alpha_vantage", "yahoo_finance"],
                "portfolio_size_limit": 100,
            },
            "observability": {
                "trace_level": "detailed",
                "metrics_collection": True,
                "error_tracking": True,
                "performance_profiling": True,
            },
        }

    def get_hook_definitions(self) -> List[Dict[str, Any]]:
        """Automation hooks for trading workflows"""
        return [
            {
                "name": "pre-trade-validation",
                "trigger": "before_trade_execution",
                "action": "validate_trade_conditions",
                "configuration": {
                    "risk_checks": ["position_size", "correlation", "liquidity"],
                    "market_conditions": ["volatility", "volume", "spread"],
                    "portfolio_constraints": ["sector_limits", "concentration"],
                },
            },
            {
                "name": "post-analysis-notification",
                "trigger": "after_analysis_completion",
                "action": "send_analysis_alert",
                "configuration": {
                    "alert_conditions": ["strong_signals", "high_risk", "anomalies"],
                    "notification_channels": ["slack", "email"],
                    "report_format": "detailed_summary",
                },
            },
            {
                "name": "system-health-monitor",
                "trigger": "periodic",
                "schedule": "*/5 * * * *",  # Every 5 minutes
                "action": "health_check_and_alert",
                "configuration": {
                    "checks": ["api_connectivity", "data_quality", "performance"],
                    "alert_threshold": "warning",
                },
            },
        ]

    async def _implement_analyze_command(
        self, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Implementation for /analyze-trading command"""
        from production_trading_system import ProductionTradingAPI

        api = ProductionTradingAPI()
        await api.initialize()

        result = await api.analyze_symbol(
            symbol=params["symbol"], analysis_type="comprehensive_analysis"
        )

        return {
            "status": "success",
            "symbol": params["symbol"],
            "analysis": result,
            "indicators_used": params.get("indicators", ["RSI", "MACD"]),
            "timestamp": result.get("executed_at"),
        }

    async def _implement_validate_command(
        self, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Implementation for /validate-market-data command"""
        from trading_data_validation.scripts.field_validator import (
            ValidateNumericFields,
        )

        # Fetch market data from specified source
        market_data = await self._fetch_market_data(params["source"], params["symbol"])

        # Validate data quality
        validator = ValidateNumericFields()
        validation_result = await validator.execute(market_data, params["source"])

        return {
            "status": "success",
            "source": params["source"],
            "symbol": params["symbol"],
            "validation": validation_result,
            "data_quality_score": validation_result.get("quality_score", 0),
        }

    async def _implement_health_command(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Implementation for /portfolio-health command"""
        from trading_system_monitoring.scripts.health_checker import HealthChecker

        health_checker = HealthChecker()
        health_status = await health_checker.check_system_health()

        if params.get("detailed", False):
            # Add detailed metrics
            from production_trading_system import ProductionTradingAPI

            api = ProductionTradingAPI()
            system_metrics = await api.get_system_metrics()

            return {
                "status": "success",
                "health": health_status,
                "system_metrics": system_metrics,
                "detailed_view": True,
            }

        return {
            "status": "success",
            "health": health_status,
            "summary": {
                "overall_score": health_status.get("overall_score"),
                "status": health_status.get("status"),
                "alerts_count": len(health_status.get("alerts", [])),
            },
        }

    async def _fetch_market_data(self, source: str, symbol: str) -> Dict[str, Any]:
        """Helper to fetch market data from specified source"""
        # This would integrate with the actual data sources
        return {
            "symbol": symbol,
            "price": 175.43,
            "volume": 1000000,
            "change": 1.25,
            "change_percent": 0.72,
            "timestamp": "2024-01-15T16:00:00",
        }

    def generate_claude_code_config(self) -> Dict[str, Any]:
        """Generate complete Claude Code configuration"""
        return {
            "template": {
                "id": self.template_id,
                "version": self.version,
                "name": "Trading System Orchestrator",
                "description": "Production-grade trading system with Claude Code integration",
            },
            "agent": self.get_agent_definition(),
            "commands": self.get_command_definitions(),
            "mcps": self.get_mcp_integrations(),
            "settings": self.get_settings_configuration(),
            "hooks": self.get_hook_definitions(),
            "installation": {
                "dependencies": [
                    "production_trading_system",
                    "trading-market-data",
                    "trading-data-validation",
                    "trading-agent-orchestration",
                    "trading-system-monitoring",
                ],
                "environment_variables": [
                    "CLAUDE_API_KEY",
                    "ALPHA_VANTAGE_API_KEY",
                    "TRADING_DB_URL",
                    "NOTIFICATION_WEBHOOK_URL",
                ],
                "quick_start": {
                    "install_command": f"npx claude-code-templates@latest --agent {self.template_id} --yes",
                    "test_command": "/analyze-trading AAPL --indicators=RSI,MACD",
                    "health_check": "/portfolio-health --detailed",
                },
            },
        }


# Template factory for Claude Code integration
def create_trading_template() -> TradingSystemClaudeTemplate:
    """Create trading system template for Claude Code"""
    return TradingSystemClaudeTemplate()


# Export for Claude Code templates
if __name__ == "__main__":
    template = create_trading_template()
    config = template.generate_claude_code_config()

    # Save configuration for Claude Code
    with open("claude-trading-config.json", "w") as f:
        json.dump(config, f, indent=2)

    print(f"✅ Trading system template generated: {template.template_id}")
    print(f"📋 Configuration saved to: claude-trading-config.json")
    print(
        f"🚀 Quick install: npx claude-code-templates@latest --agent {template.template_id} --yes"
    )
