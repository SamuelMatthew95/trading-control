"""
OpenClaw Orchestrator - Clean Production Implementation
No old references, robust architecture, proper error handling
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from logger import get_logger
from memory import MemoryManager, get_memory_manager
from tasks import TaskFactory, TaskQueue, TaskType, get_task_queue
from tools import ToolRegistry, get_tool_registry

logger = get_logger(__name__)


class OrchestratorStatus(Enum):
    """Orchestrator status"""

    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class CycleResult:
    """Orchestration cycle result"""

    cycle_id: str
    trace_id: str
    success: bool
    signals_generated: int
    tasks_executed: int
    steps_completed: List[str]
    errors: List[str]
    started_at: datetime
    completed_at: datetime


class OpenClawOrchestrator:
    """Clean, robust OpenClaw orchestrator implementation"""

    def __init__(
        self, memory: MemoryManager, tools: ToolRegistry, task_queue: TaskQueue
    ):
        self.memory = memory
        self.tools = tools
        self.task_queue = task_queue

        self.is_running = False
        self.status = OrchestratorStatus.IDLE
        self.current_cycle_id: Optional[str] = None
        self.active_cycles: Dict[str, datetime] = {}
        self.completed_cycles: List[CycleResult] = []

        # Configuration
        self.cycle_interval = 60  # seconds
        self.max_concurrent_cycles = 3
        self.confidence_threshold = 0.6
        self.risk_threshold = 0.7

        # Background task
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Agent registry
        self.agents: Dict[str, Any] = {}

        logger.info("OpenClaw Orchestrator initialized")

    async def start(self):
        """Start the orchestrator"""
        if self.is_running:
            logger.warning("Orchestrator is already running")
            return

        logger.info("Starting OpenClaw Orchestrator...")

        self.is_running = True
        self.status = OrchestratorStatus.RUNNING

        # Start heartbeat loop
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info("✅ OpenClaw Orchestrator started")

    async def stop(self):
        """Stop the orchestrator"""
        if not self.is_running:
            logger.warning("Orchestrator is not running")
            return

        logger.info("Stopping OpenClaw Orchestrator...")

        self.is_running = False
        self.status = OrchestratorStatus.STOPPED

        # Cancel heartbeat task
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        logger.info("✅ OpenClaw Orchestrator stopped")

    async def _heartbeat_loop(self):
        """Main orchestration heartbeat loop"""
        logger.info("Starting orchestration heartbeat loop")

        while self.is_running:
            try:
                # Check if we can start a new cycle
                if len(self.active_cycles) < self.max_concurrent_cycles:
                    await self._run_cycle()

                # Wait for next cycle
                await asyncio.sleep(self.cycle_interval)

            except asyncio.CancelledError:
                logger.info("Heartbeat loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(5)  # Wait before retrying

    async def _run_cycle(self):
        """Run a single orchestration cycle"""
        cycle_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())

        logger.debug(f"Starting orchestration cycle {cycle_id}")

        # Track active cycle
        self.active_cycles[cycle_id] = datetime.now()
        self.current_cycle_id = cycle_id

        try:
            steps_completed = []
            errors = []
            signals_generated = 0
            tasks_executed = 0

            # Step 1: Scan for opportunities
            opportunities = await self._scan_opportunities()
            steps_completed.append("scan_opportunities")

            # Step 2: Process each opportunity
            for opportunity in opportunities:
                try:
                    # Step 3: Analyze symbol
                    analysis = await self._analyze_symbol(opportunity["symbol"])
                    steps_completed.append(f"analyze_{opportunity['symbol']}")

                    # Step 4: Generate signal if conditions met
                    if self._should_generate_signal(analysis):
                        signal = await self._generate_signal(
                            opportunity["symbol"], analysis
                        )
                        steps_completed.append(
                            f"generate_signal_{opportunity['symbol']}"
                        )
                        signals_generated += 1

                        # Step 5: Validate signal
                        validation = await self._validate_signal(signal)
                        steps_completed.append(
                            f"validate_signal_{opportunity['symbol']}"
                        )

                        # Step 6: Store signal if valid
                        if validation["valid"]:
                            await self._store_signal(signal)
                            steps_completed.append(
                                f"store_signal_{opportunity['symbol']}"
                            )

                    tasks_executed += 1

                except Exception as e:
                    error_msg = f"Error processing {opportunity['symbol']}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            # Create cycle result
            cycle_result = CycleResult(
                cycle_id=cycle_id,
                trace_id=trace_id,
                success=len(errors) == 0,
                signals_generated=signals_generated,
                tasks_executed=tasks_executed,
                steps_completed=steps_completed,
                errors=errors,
                started_at=self.active_cycles[cycle_id],
                completed_at=datetime.now(),
            )

            # Store result
            self.completed_cycles.append(cycle_result)

            # Keep only last 100 cycles
            if len(self.completed_cycles) > 100:
                self.completed_cycles = self.completed_cycles[-100:]

            logger.debug(
                f"Completed cycle {cycle_id}: {signals_generated} signals, {tasks_executed} tasks"
            )

        except Exception as e:
            logger.error(f"Error in cycle {cycle_id}: {e}")

            # Create error result
            cycle_result = CycleResult(
                cycle_id=cycle_id,
                trace_id=trace_id,
                success=False,
                signals_generated=0,
                tasks_executed=0,
                steps_completed=[],
                errors=[str(e)],
                started_at=self.active_cycles[cycle_id],
                completed_at=datetime.now(),
            )

            self.completed_cycles.append(cycle_result)

        finally:
            # Remove from active cycles
            if cycle_id in self.active_cycles:
                del self.active_cycles[cycle_id]

            if self.current_cycle_id == cycle_id:
                self.current_cycle_id = None

    async def _scan_opportunities(self) -> List[Dict[str, Any]]:
        """Scan for trading opportunities"""
        try:
            # Get symbols to monitor (simplified - in production, use configuration)
            symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"]

            opportunities = []
            for symbol in symbols:
                # Get current quote
                quote_result = await self.tools.execute_tool(
                    "get_stock_quote", symbol=symbol
                )

                if "error" not in quote_result:
                    opportunities.append(
                        {
                            "symbol": symbol,
                            "price": quote_result["price"],
                            "change_percent": quote_result["change_percent"],
                            "volume": quote_result["volume"],
                        }
                    )

            logger.debug(f"Scanned {len(opportunities)} opportunities")
            return opportunities

        except Exception as e:
            logger.error(f"Error scanning opportunities: {e}")
            return []

    async def _analyze_symbol(self, symbol: str) -> Dict[str, Any]:
        """Analyze a symbol for trading signals"""
        try:
            analysis = {
                "symbol": symbol,
                "technical": {},
                "fundamental": {},
                "sentiment": {},
                "overall_score": 0.0,
            }

            # Get historical prices for technical analysis
            historical_result = await self.tools.execute_tool(
                "get_historical_prices",
                symbol=symbol,
                start_date=(datetime.now() - timedelta(days=30)).isoformat(),
                end_date=datetime.now().isoformat(),
            )

            if "error" not in historical_result:
                prices = [p["close"] for p in historical_result.get("prices", [])]
                if len(prices) > 20:
                    # Simple technical analysis (simplified)
                    analysis["technical"] = {
                        "trend": "up" if prices[-1] > prices[0] else "down",
                        "volatility": self._calculate_volatility(prices),
                        "volume_trend": "increasing",
                    }

            # Get news sentiment
            news_result = await self.tools.execute_tool(
                "get_recent_news", symbol=symbol, days=7
            )

            if "error" not in news_result:
                analysis["sentiment"] = {
                    "avg_sentiment": news_result.get("avg_sentiment", 0.5),
                    "news_count": news_result.get("total_articles", 0),
                }

            # Calculate overall score (simplified)
            tech_score = 0.5 if analysis["technical"].get("trend") == "up" else 0.3
            sentiment_score = analysis["sentiment"].get("avg_sentiment", 0.5)

            analysis["overall_score"] = (tech_score + sentiment_score) / 2

            return analysis

        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")
            return {"symbol": symbol, "error": str(e)}

    def _calculate_volatility(self, prices: List[float]) -> float:
        """Calculate price volatility"""
        if len(prices) < 2:
            return 0.0

        returns = [
            (prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))
        ]

        if not returns:
            return 0.0

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)

        return variance**0.5

    def _should_generate_signal(self, analysis: Dict[str, Any]) -> bool:
        """Determine if we should generate a signal"""
        if "error" in analysis:
            return False

        score = analysis.get("overall_score", 0.0)
        return score >= self.confidence_threshold

    async def _generate_signal(
        self, symbol: str, analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate trading signal"""
        try:
            # Get current price
            quote_result = await self.tools.execute_tool(
                "get_stock_quote", symbol=symbol
            )

            if "error" in quote_result:
                return {"error": f"Could not get quote for {symbol}"}

            current_price = quote_result["price"]

            # Generate signal based on analysis
            trend = analysis.get("technical", {}).get("trend", "neutral")
            confidence = analysis.get("overall_score", 0.5)

            if trend == "up":
                direction = "CALL"
                entry = current_price
                stop_loss = current_price * 0.95  # 5% stop loss
                take_profit = current_price * 1.10  # 10% take profit
            else:
                direction = "PUT"
                entry = current_price
                stop_loss = current_price * 1.05  # 5% stop loss
                take_profit = current_price * 0.90  # 10% take profit

            signal = {
                "ticker": symbol,
                "direction": direction,
                "entry": round(entry, 2),
                "stop_loss": round(stop_loss, 2),
                "take_profit": round(take_profit, 2),
                "confidence": round(confidence, 2),
                "reasoning": f"Signal based on {trend} trend with {confidence:.2f} confidence",
                "timestamp": datetime.now().isoformat(),
                "analysis": analysis,
            }

            return signal

        except Exception as e:
            logger.error(f"Error generating signal for {symbol}: {e}")
            return {"error": str(e)}

    async def _validate_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Validate trading signal"""
        try:
            if "error" in signal:
                return {
                    "valid": False,
                    "validation_score": 0.0,
                    "issues": ["Signal contains error"],
                }

            issues = []
            validation_score = 1.0

            # Check confidence
            confidence = signal.get("confidence", 0.0)
            if confidence < self.confidence_threshold:
                issues.append(f"Low confidence: {confidence}")
                validation_score -= 0.3

            # Check risk/reward ratio
            entry = signal.get("entry", 0)
            stop_loss = signal.get("stop_loss", 0)
            take_profit = signal.get("take_profit", 0)

            if entry > 0 and stop_loss > 0 and take_profit > 0:
                risk = abs(entry - stop_loss)
                reward = abs(take_profit - entry)
                ratio = reward / risk if risk > 0 else 0

                if ratio < 1.5:  # Minimum 1.5:1 risk/reward ratio
                    issues.append(f"Poor risk/reward ratio: {ratio:.2f}")
                    validation_score -= 0.2

            return {
                "valid": len(issues) == 0,
                "validation_score": max(0.0, validation_score),
                "issues": issues,
            }

        except Exception as e:
            logger.error(f"Error validating signal: {e}")
            return {"valid": False, "validation_score": 0.0, "issues": [str(e)]}

    async def _store_signal(self, signal: Dict[str, Any]) -> bool:
        """Store signal in memory"""
        try:
            # Store in memory (simplified implementation)
            # In production, this would store in the persistent memory layer
            logger.info(
                f"Stored signal for {signal.get('ticker')}: {signal.get('direction')}"
            )
            return True

        except Exception as e:
            logger.error(f"Error storing signal: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get orchestrator status"""
        return {
            "is_running": self.is_running,
            "status": self.status.value,
            "current_cycle_id": self.current_cycle_id,
            "active_cycles": len(self.active_cycles),
            "total_cycles": len(self.completed_cycles),
            "successful_cycles": len([c for c in self.completed_cycles if c.success]),
            "failed_cycles": len([c for c in self.completed_cycles if not c.success]),
            "success_rate": (
                len([c for c in self.completed_cycles if c.success])
                / len(self.completed_cycles)
                if self.completed_cycles
                else 0.0
            ),
            "last_cycle_time": (
                self.completed_cycles[-1].completed_at.isoformat()
                if self.completed_cycles
                else None
            ),
            "registered_agents": len(self.agents),
            "symbols_monitored": [
                "AAPL",
                "GOOGL",
                "MSFT",
                "AMZN",
                "TSLA",
            ],  # Simplified
        }

    async def get_cycle_results(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent cycle results"""
        recent_cycles = self.completed_cycles[-limit:] if self.completed_cycles else []

        return [
            {
                "cycle_id": cycle.cycle_id,
                "trace_id": cycle.trace_id,
                "success": cycle.success,
                "signals_generated": cycle.signals_generated,
                "tasks_executed": cycle.tasks_executed,
                "steps_completed": cycle.steps_completed,
                "errors": cycle.errors,
                "started_at": cycle.started_at.isoformat(),
                "completed_at": cycle.completed_at.isoformat(),
                "duration_ms": int(
                    (cycle.completed_at - cycle.started_at).total_seconds() * 1000
                ),
            }
            for cycle in recent_cycles
        ]

    def register_agent(self, agent_id: str, agent: Any):
        """Register an agent"""
        self.agents[agent_id] = agent
        logger.info(f"Registered agent: {agent_id}")

    def unregister_agent(self, agent_id: str):
        """Unregister an agent"""
        if agent_id in self.agents:
            del self.agents[agent_id]
            logger.info(f"Unregistered agent: {agent_id}")

    def get_agent(self, agent_id: str) -> Optional[Any]:
        """Get registered agent"""
        return self.agents.get(agent_id)

    def list_agents(self) -> List[str]:
        """List all registered agents"""
        return list(self.agents.keys())
