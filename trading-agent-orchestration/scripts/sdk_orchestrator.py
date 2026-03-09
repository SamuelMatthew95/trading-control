"""
Production-Grade Trading Agent Orchestration
Uses Claude Agent SDK for programmatic control
Integrates with Skills architecture
"""

from __future__ import annotations
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

# Import SDK components
from .supervisor_orchestrator import SupervisorOrchestrator
from .observability import observability_system
from ..agents.market_data_agent import MarketDataAgent, MarketDataInput, MarketDataOutput
from ..agents.data_validation_agent import DataValidationAgent, ValidationInput, ValidationOutput
from ..agents.technical_analysis_agent import TechnicalAnalysisAgent, TechnicalAnalysisInput, TechnicalAnalysisOutput


class SDKBasedTradingOrchestrator:
    """
    Production orchestrator using Claude Agent SDK principles
    Provides programmatic control while leveraging Skills architecture
    """
    
    def __init__(self, claude_sdk_api_key: str = None):
        self.orchestrator_id = f"sdk_orchestrator_{datetime.now().timestamp()}"
        
        # SDK would be initialized here in production
        # For now, we use our custom implementation that follows SDK patterns
        self.supervisor = SupervisorOrchestrator()
        self.observability = observability_system
        
        # Skill registry for SDK integration
        self.registered_skills = {
            "trading-market-data": {
                "path": "trading-market-data",
                "agent": "market_data",
                "input_contract": "MarketDataInput",
                "output_contract": "MarketDataOutput"
            },
            "trading-data-validation": {
                "path": "trading-data-validation", 
                "agent": "data_validation",
                "input_contract": "ValidationInput",
                "output_contract": "ValidationOutput"
            },
            "trading-technical-analysis": {
                "path": "trading-agent-orchestration",
                "agent": "technical_analysis", 
                "input_contract": "TechnicalAnalysisInput",
                "output_contract": "TechnicalAnalysisOutput"
            }
        }
        
        # Workflow definitions for SDK
        self.workflow_definitions = {
            "market_analysis": {
                "name": "Market Data Analysis",
                "skills": ["trading-market-data", "trading-data-validation"],
                "description": "Fetch and validate market data",
                "estimated_duration_ms": 2000
            },
            "technical_analysis": {
                "name": "Technical Analysis",
                "skills": ["trading-market-data", "trading-data-validation", "trading-technical-analysis"],
                "description": "Complete technical analysis with indicators",
                "estimated_duration_ms": 5000
            },
            "health_monitoring": {
                "name": "System Health Check",
                "skills": ["trading-system-monitoring"],
                "description": "Monitor system health and performance",
                "estimated_duration_ms": 1000
            }
        }
    
    async def execute_workflow(self, workflow_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute workflow using SDK-style programmatic control
        This replaces the old monolithic orchestrator approach
        """
        if workflow_name not in self.workflow_definitions:
            raise ValueError(f"Unknown workflow: {workflow_name}")
        
        workflow_def = self.workflow_definitions[workflow_name]
        
        # Start observability tracing
        correlation_id = self.observability.start_workflow_trace(
            workflow_id=f"{workflow_name}_{datetime.now().timestamp()}",
            metadata={
                "workflow_name": workflow_name,
                "parameters": parameters,
                "skills_used": workflow_def["skills"]
            }
        )
        
        try:
            # Execute based on workflow type
            if workflow_name == "market_analysis":
                result = await self._execute_market_analysis(parameters, correlation_id)
            elif workflow_name == "technical_analysis":
                result = await self._execute_technical_analysis(parameters, correlation_id)
            elif workflow_name == "health_monitoring":
                result = await self._execute_health_monitoring(parameters, correlation_id)
            else:
                raise ValueError(f"Workflow {workflow_name} not implemented")
            
            # Record successful completion
            self.observability.end_workflow_trace(
                workflow_id=correlation_id,
                success=True
            )
            
            return {
                "workflow_id": correlation_id,
                "workflow_name": workflow_name,
                "status": "completed",
                "result": result,
                "skills_used": workflow_def["skills"],
                "executed_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            # Record failure
            self.observability.end_workflow_trace(
                workflow_id=correlation_id,
                success=False,
                error=str(e)
            )
            
            return {
                "workflow_id": correlation_id,
                "workflow_name": workflow_name,
                "status": "failed",
                "error": str(e),
                "skills_used": workflow_def["skills"],
                "executed_at": datetime.now().isoformat()
            }
    
    async def _execute_market_analysis(self, parameters: Dict[str, Any], correlation_id: str) -> Dict[str, Any]:
        """Execute market analysis workflow"""
        symbol = parameters.get("symbol")
        if not symbol:
            raise ValueError("Symbol parameter required")
        
        # Use supervisor orchestrator for actual execution
        return await self.supervisor.execute_trading_analysis(
            symbol=symbol,
            analysis_config={
                "indicators": [],  # No technical analysis for basic market analysis
                "data_sources": parameters.get("data_sources", ["alpha_vantage", "yahoo_finance"])
            }
        )
    
    async def _execute_technical_analysis(self, parameters: Dict[str, Any], correlation_id: str) -> Dict[str, Any]:
        """Execute technical analysis workflow"""
        symbol = parameters.get("symbol")
        if not symbol:
            raise ValueError("Symbol parameter required")
        
        return await self.supervisor.execute_trading_analysis(
            symbol=symbol,
            analysis_config={
                "indicators": parameters.get("indicators", ["RSI", "MACD", "BB"]),
                "time_period": parameters.get("time_period", 14),
                "data_sources": parameters.get("data_sources", ["alpha_vantage", "yahoo_finance"])
            }
        )
    
    async def _execute_health_monitoring(self, parameters: Dict[str, Any], correlation_id: str) -> Dict[str, Any]:
        """Execute health monitoring workflow"""
        # This would integrate with trading-system-monitoring skill
        from trading_system_monitoring.scripts.health_checker import HealthChecker
        
        health_checker = HealthChecker()
        health_status = await health_checker.check_system_health()
        
        return {
            "health_status": health_status,
            "timestamp": datetime.now().isoformat()
        }
    
    def get_available_workflows(self) -> Dict[str, Any]:
        """Get available workflows for SDK interface"""
        return {
            "workflows": self.workflow_definitions,
            "skills": self.registered_skills,
            "orchestrator_id": self.orchestrator_id
        }
    
    def get_workflow_trace(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow trace for debugging"""
        return self.observability.get_workflow_trace(workflow_id)
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get system status"""
        supervisor_status = self.supervisor.get_system_status()
        observability_metrics = self.observability.get_performance_metrics()
        
        return {
            "orchestrator_id": self.orchestrator_id,
            "sdk_mode": True,
            "supervisor_status": supervisor_status,
            "observability_metrics": observability_metrics,
            "available_workflows": len(self.workflow_definitions),
            "registered_skills": len(self.registered_skills),
            "timestamp": datetime.now().isoformat()
        }


# Factory function for SDK integration
def create_trading_orchestrator(claude_api_key: str = None) -> SDKBasedTradingOrchestrator:
    """
    Factory function for creating SDK-based orchestrator
    This is the recommended way to create orchestrators in production
    """
    return SDKBasedTradingOrchestrator(claude_api_key)
