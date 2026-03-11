"""
Complete Claude Multi-Agent Trade Bot System
With proper error handling, logging, and real agent calls
"""

import json
import logging
import anthropic
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trade-bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class AgentCall:
    """Track agent calls for logging"""
    agent_name: str
    input_data: Dict[str, Any]
    output_data: Dict[str, Any]
    timestamp: datetime
    success: bool
    error: Optional[str] = None

class MultiAgentOrchestrator:
    """Complete multi-agent orchestrator with real Claude calls"""
    
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.agent_calls = []
        self.trade_log = []
        
        # Agent system prompts
        self.agents = {
            "SIGNAL_AGENT": {
                "system": """You normalize trade signals. Return valid JSON only with this format:
                [{"source": "agent_name", "direction": "LONG/SHORT/FLAT", "confidence": 0.85, "timeframe": "1D"}]
                Analyze the asset and return multiple signals from different perspectives.""",
                "required_fields": ["source", "direction", "confidence", "timeframe"]
            },
            "CONSENSUS_AGENT": {
                "system": """You aggregate signals and compute consensus. Return valid JSON only:
                {"direction": "LONG/SHORT/FLAT", "agreement_ratio": 0.75, "signal_strength": 0.8}
                agreement_ratio = percentage of agents agreeing on the direction.
                signal_strength = agreement_ratio * average_confidence.""",
                "required_fields": ["direction", "agreement_ratio", "signal_strength"]
            },
            "RISK_AGENT": {
                "system": """You enforce risk limits and can veto trades. Return valid JSON only:
                {"approved": true, "veto": false, "risk_score": 0.3, "size_multiplier": 1.0, "flags": ["flag1", "flag2"]}
                Veto if: drawdown > 15%, position size > 10%, or insufficient liquidity.
                size_multiplier: reduce position if risk is high (0.5-1.0).""",
                "required_fields": ["approved", "veto", "risk_score", "size_multiplier", "flags"]
            },
            "SIZING_AGENT": {
                "system": """You calculate position size using Kelly criterion. Return valid JSON only:
                {"units": 100, "entry": 150.25, "stop": 145.00, "target": 160.00, "rr_ratio": 2.0}
                Use Kelly: position_size = (win_probability * avg_win - loss_probability * avg_loss) / avg_win * 0.25
                rr_ratio = (target - entry) / (entry - stop).""",
                "required_fields": ["units", "entry", "stop", "target", "rr_ratio"]
            }
        }
    
    def call_agent(self, agent_name: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Call individual agent with error handling and logging"""
        
        try:
            logger.info(f"Calling {agent_name} with input: {input_data}")
            
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=self.agents[agent_name]["system"],
                messages=[
                    {"role": "user", "content": json.dumps(input_data, indent=2)}
                ]
            )
            
            raw_output = response.content[0].text
            logger.info(f"{agent_name} raw output: {raw_output}")
            
            # Parse JSON response
            try:
                output_data = json.loads(raw_output)
                
                # Validate required fields
                required_fields = self.agents[agent_name]["required_fields"]
                missing_fields = [field for field in required_fields if field not in output_data]
                
                if missing_fields:
                    error_msg = f"Missing required fields: {missing_fields}"
                    logger.error(f"{agent_name} validation error: {error_msg}")
                    
                    agent_call = AgentCall(
                        agent_name=agent_name,
                        input_data=input_data,
                        output_data={},
                        timestamp=datetime.now(),
                        success=False,
                        error=error_msg
                    )
                    self.agent_calls.append(agent_call)
                    return {"success": False, "error": error_msg}
                
                # Log successful call
                agent_call = AgentCall(
                    agent_name=agent_name,
                    input_data=input_data,
                    output_data=output_data,
                    timestamp=datetime.now(),
                    success=True
                )
                self.agent_calls.append(agent_call)
                
                return {"success": True, "data": output_data}
                
            except json.JSONDecodeError as e:
                error_msg = f"JSON parsing error: {str(e)}"
                logger.error(f"{agent_name} JSON error: {error_msg}")
                
                agent_call = AgentCall(
                    agent_name=agent_name,
                    input_data=input_data,
                    output_data={},
                    timestamp=datetime.now(),
                    success=False,
                    error=error_msg
                )
                self.agent_calls.append(agent_call)
                
                return {"success": False, "error": error_msg}
            
        except Exception as e:
            error_msg = f"API call error: {str(e)}"
            logger.error(f"{agent_name} API error: {error_msg}")
            
            agent_call = AgentCall(
                agent_name=agent_name,
                input_data=input_data,
                output_data={},
                timestamp=datetime.now(),
                success=False,
                error=error_msg
            )
            self.agent_calls.append(agent_call)
            
            return {"success": False, "error": error_msg}
    
    def analyze_trade(self, asset: str, timeframe: str, portfolio_state: Dict[str, Any]) -> Dict[str, Any]:
        """Complete trade analysis pipeline"""
        
        logger.info(f"Starting trade analysis for {asset}")
        
        # Step 1: Signal Agent
        signal_input = {
            "asset": asset,
            "timeframe": timeframe,
            "portfolio_state": portfolio_state
        }
        
        signal_result = self.call_agent("SIGNAL_AGENT", signal_input)
        if not signal_result["success"]:
            return self._error_decision(asset, f"Signal agent failed: {signal_result['error']}")
        
        signals = signal_result["data"]
        
        # Step 2: Consensus Agent
        consensus_input = {
            "signals": signals
        }
        
        consensus_result = self.call_agent("CONSENSUS_AGENT", consensus_input)
        if not consensus_result["success"]:
            return self._error_decision(asset, f"Consensus agent failed: {consensus_result['error']}")
        
        consensus = consensus_result["data"]
        
        # Check consensus threshold
        if consensus["agreement_ratio"] < 0.50:
            return self._conflict_decision(asset, consensus, signals)
        
        # Step 3: Risk Agent
        risk_input = {
            "consensus": consensus,
            "portfolio": portfolio_state
        }
        
        risk_result = self.call_agent("RISK_AGENT", risk_input)
        if not risk_result["success"]:
            return self._error_decision(asset, f"Risk agent failed: {risk_result['error']}")
        
        risk = risk_result["data"]
        
        # Check for veto
        if risk["veto"]:
            return self._veto_decision(asset, consensus, risk)
        
        # Step 4: Sizing Agent
        sizing_input = {
            "consensus": consensus,
            "risk": risk,
            "asset_price": self._get_current_price(asset),
            "atr": self._get_atr(asset, timeframe),
            "portfolio_value": portfolio_state.get("total_value", 100000)
        }
        
        sizing_result = self.call_agent("SIZING_AGENT", sizing_input)
        if not sizing_result["success"]:
            return self._error_decision(asset, f"Sizing agent failed: {sizing_result['error']}")
        
        sizing = sizing_result["data"]
        
        # Generate final decision
        final_decision = self._format_final_decision(asset, consensus, risk, sizing, signals)
        
        # Log to trade log
        self._log_trade(final_decision)
        
        return final_decision
    
    def _get_current_price(self, asset: str) -> float:
        """Get current asset price (placeholder - implement real data source)"""
        # In production, this would call your data provider
        price_map = {
            "AAPL": 150.25,
            "MSFT": 380.50,
            "GOOGL": 2800.00,
            "TSLA": 250.00
        }
        return price_map.get(asset, 100.00)
    
    def _get_atr(self, asset: str, timeframe: str) -> float:
        """Get Average True Range (placeholder - implement real calculation)"""
        # In production, this would calculate ATR from historical data
        return 5.0  # Placeholder ATR
    
    def _format_final_decision(self, asset: str, consensus: Dict, risk: Dict, 
                              sizing: Dict, signals: List[Dict]) -> Dict[str, Any]:
        """Format final decision in standard output format"""
        
        # Determine confidence level
        signal_strength = consensus["signal_strength"]
        if signal_strength > 0.8:
            confidence = "HIGH"
        elif signal_strength > 0.6:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        
        # Calculate portfolio percentage
        portfolio_value = 100000  # Placeholder
        position_value = sizing["units"] * sizing["entry"]
        portfolio_pct = (position_value / portfolio_value) * 100
        
        return {
            "DECISION": consensus["direction"],
            "ASSET": asset,
            "SIZE": f"{sizing['units']} units ({portfolio_pct:.1f}% of portfolio)",
            "ENTRY": f"{sizing['entry']:.2f}",
            "STOP": f"{sizing['stop']:.2f}",
            "TARGET": f"{sizing['target']:.2f}",
            "R/R RATIO": f"{sizing['rr_ratio']:.1f}:1",
            "CONFIDENCE": confidence,
            
            "SIGNAL SUMMARY": [
                f"Signal Agent: {len(signals)} signals collected",
                f"Consensus Agent: {consensus['agreement_ratio']:.1%} agreement for {consensus['direction']}",
                f"Risk Agent: Approved with {risk['size_multiplier']:.1f}x multiplier",
                f"Sizing Agent: Kelly criterion position sizing"
            ],
            
            "RISK FLAGS": risk["flags"],
            
            "RATIONALE": f"Strong {consensus['direction']} consensus with {consensus['agreement_ratio']:.1%} agreement. Risk score {risk['risk_score']:.2f} is acceptable. Kelly criterion suggests optimal position size.",
            
            "INVALIDATION": f"Price below {sizing['stop']:.2f} (stop loss) or above {sizing['target']:.2f} (target)"
        }
    
    def _error_decision(self, asset: str, error_msg: str) -> Dict[str, Any]:
        """Return error decision"""
        decision = {
            "DECISION": "FLAT",
            "ASSET": asset,
            "SIZE": "0 units",
            "ENTRY": "MARKET",
            "STOP": "N/A",
            "TARGET": "N/A",
            "R/R RATIO": "N/A",
            "CONFIDENCE": "LOW",
            "SIGNAL SUMMARY": [f"Error: {error_msg}"],
            "RISK FLAGS": ["SYSTEM_ERROR"],
            "RATIONALE": f"System error prevented analysis: {error_msg}",
            "INVALIDATION": "N/A"
        }
        self._log_trade(decision)
        return decision
    
    def _conflict_decision(self, asset: str, consensus: Dict, signals: List[Dict]) -> Dict[str, Any]:
        """Return conflict decision"""
        decision = {
            "DECISION": "FLAT",
            "ASSET": asset,
            "SIZE": "0 units",
            "ENTRY": "MARKET",
            "STOP": "N/A",
            "TARGET": "N/A",
            "R/R RATIO": "N/A",
            "CONFIDENCE": "LOW",
            "SIGNAL SUMMARY": [
                f"Signal Agent: {len(signals)} signals collected",
                f"Consensus Agent: Only {consensus['agreement_ratio']:.1%} agreement - below 50% threshold"
            ],
            "RISK FLAGS": ["LOW_CONSENSUS"],
            "RATIONALE": f"Insufficient consensus ({consensus['agreement_ratio']:.1%} - below 50% threshold). Signals are conflicting.",
            "INVALIDATION": "N/A"
        }
        self._log_trade(decision)
        return decision
    
    def _veto_decision(self, asset: str, consensus: Dict, risk: Dict) -> Dict[str, Any]:
        """Return veto decision"""
        decision = {
            "DECISION": "VETO",
            "ASSET": asset,
            "SIZE": "0 units",
            "ENTRY": "MARKET",
            "STOP": "N/A",
            "TARGET": "N/A",
            "R/R RATIO": "N/A",
            "CONFIDENCE": "LOW",
            "SIGNAL SUMMARY": [
                f"Signal Agent: Consensus for {consensus['direction']}",
                f"Risk Agent: VETOED - {risk['flags']}"
            ],
            "RISK FLAGS": risk["flags"],
            "RATIONALE": f"Risk management veto: {', '.join(risk['flags'])}. Trade rejected despite signal consensus.",
            "INVALIDATION": "N/A"
        }
        self._log_trade(decision)
        return decision
    
    def _log_trade(self, decision: Dict[str, Any]):
        """Log trade decision to file"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "decision": decision,
            "agent_calls": [
                {
                    "agent": call.agent_name,
                    "success": call.success,
                    "error": call.error,
                    "timestamp": call.timestamp.isoformat()
                }
                for call in self.agent_calls
            ]
        }
        
        self.trade_log.append(log_entry)
        
        # Save to file
        try:
            with open('trade-log.json', 'w') as f:
                json.dump(self.trade_log, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save trade log: {e}")
        
        # Clear agent calls for next trade
        self.agent_calls = []
    
    def get_trade_history(self) -> List[Dict]:
        """Get trade history"""
        return self.trade_log
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Calculate performance statistics from trade log"""
        if not self.trade_log:
            return {"total_trades": 0}
        
        decisions = [entry["decision"] for entry in self.trade_log]
        
        total_trades = len(decisions)
        long_trades = len([d for d in decisions if d["DECISION"] == "LONG"])
        short_trades = len([d for d in decisions if d["DECISION"] == "SHORT"])
        veto_trades = len([d for d in decisions if d["DECISION"] == "VETO"])
        flat_trades = len([d for d in decisions if d["DECISION"] == "FLAT"])
        
        return {
            "total_trades": total_trades,
            "long_trades": long_trades,
            "short_trades": short_trades,
            "veto_trades": veto_trades,
            "flat_trades": flat_trades,
            "trade_rate": (long_trades + short_trades) / total_trades if total_trades > 0 else 0
        }


# Example usage
if __name__ == "__main__":
    # Initialize with your API key
    orchestrator = MultiAgentOrchestrator(api_key="your-anthropic-api-key")
    
    # Example portfolio state
    portfolio = {
        "total_value": 100000,
        "cash": 50000,
        "positions": {"AAPL": 25000, "MSFT": 25000},
        "drawdown": -0.03
    }
    
    # Run analysis
    result = orchestrator.analyze_trade("AAPL", "1D", portfolio)
    
    print("=== TRADE DECISION ===")
    for key, value in result.items():
        print(f"{key}: {value}")
    
    # Get performance stats
    stats = orchestrator.get_performance_stats()
    print(f"\n=== PERFORMANCE STATS ===")
    for key, value in stats.items():
        print(f"{key}: {value}")
