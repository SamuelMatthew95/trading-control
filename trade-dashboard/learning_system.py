import json
import time
from datetime import datetime
from typing import Dict, List, Any
import anthropic
import streamlit as st

class AgentLearningSystem:
    """Track and learn from agent performance over time"""
    
    def __init__(self):
        self.agent_performance = {
            "SIGNAL_AGENT": {
                "total_calls": 0,
                "successful_calls": 0,
                "avg_response_time": 0,
                "accuracy_score": 0,
                "confidence_calibration": [],
                "common_patterns": {},
                "improvement_areas": []
            },
            "CONSENSUS_AGENT": {
                "total_calls": 0,
                "successful_calls": 0,
                "avg_response_time": 0,
                "agreement_accuracy": 0,
                "conflict_resolution_rate": 0,
                "bias_detection": [],
                "improvement_areas": []
            },
            "RISK_AGENT": {
                "total_calls": 0,
                "successful_calls": 0,
                "avg_response_time": 0,
                "veto_accuracy": 0,
                "risk_assessment_score": 0,
                "false_veto_rate": 0,
                "missed_risks": [],
                "improvement_areas": []
            },
            "SIZING_AGENT": {
                "total_calls": 0,
                "successful_calls": 0,
                "avg_response_time": 0,
                "position_optimization": 0,
                "risk_reward_ratio": 0,
                "kelly_accuracy": 0,
                "oversizing_rate": 0,
                "improvement_areas": []
            }
        }
        
        self.trade_outcomes = []
        self.learning_metrics = {
            "total_trades": 0,
            "win_rate": 0,
            "avg_return": 0,
            "max_drawdown": 0,
            "sharpe_ratio": 0,
            "agent_contributions": {},
            "pattern_recognition": {},
            "strategy_effectiveness": {}
        }
    
    def track_agent_call(self, agent_name: str, input_data: Dict, 
                        response_data: Dict, response_time: float, success: bool):
        """Track individual agent performance"""
        
        perf = self.agent_performance[agent_name]
        perf["total_calls"] += 1
        
        if success:
            perf["successful_calls"] += 1
            
            # Update response time
            perf["avg_response_time"] = (
                (perf["avg_response_time"] * (perf["successful_calls"] - 1) + response_time) 
                / perf["successful_calls"]
            )
            
            # Agent-specific tracking
            if agent_name == "SIGNAL_AGENT":
                self._track_signal_agent(input_data, response_data)
            elif agent_name == "CONSENSUS_AGENT":
                self._track_consensus_agent(input_data, response_data)
            elif agent_name == "RISK_AGENT":
                self._track_risk_agent(input_data, response_data)
            elif agent_name == "SIZING_AGENT":
                self._track_sizing_agent(input_data, response_data)
    
    def _track_signal_agent(self, input_data: Dict, response_data: Dict):
        """Track signal agent performance"""
        perf = self.agent_performance["SIGNAL_AGENT"]
        
        # Track confidence calibration
        signals = response_data.get("signals", [])
        for signal in signals:
            confidence = signal.get("confidence", 0)
            perf["confidence_calibration"].append(confidence)
            
            # Track patterns
            source = signal.get("source", "unknown")
            if source not in perf["common_patterns"]:
                perf["common_patterns"][source] = {"count": 0, "avg_confidence": 0}
            
            pattern = perf["common_patterns"][source]
            pattern["count"] += 1
            pattern["avg_confidence"] = (
                (pattern["avg_confidence"] * (pattern["count"] - 1) + confidence) 
                / pattern["count"]
            )
    
    def _track_consensus_agent(self, input_data: Dict, response_data: Dict):
        """Track consensus agent performance"""
        perf = self.agent_performance["CONSENSUS_AGENT"]
        
        agreement = response_data.get("agreement_ratio", 0)
        perf["agreement_accuracy"] = (
            (perf["agreement_accuracy"] * (perf["successful_calls"] - 1) + agreement) 
            / perf["successful_calls"]
        )
        
        # Track conflict resolution
        if agreement < 0.5:
            perf["conflict_resolution_rate"] += 1
    
    def _track_risk_agent(self, input_data: Dict, response_data: Dict):
        """Track risk agent performance"""
        perf = self.agent_performance["RISK_AGENT"]
        
        veto = response_data.get("veto", False)
        if veto:
            perf["veto_accuracy"] += 1
        
        risk_score = response_data.get("risk_score", 0)
        perf["risk_assessment_score"] = (
            (perf["risk_assessment_score"] * (perf["successful_calls"] - 1) + risk_score) 
            / perf["successful_calls"]
        )
    
    def _track_sizing_agent(self, input_data: Dict, response_data: Dict):
        """Track sizing agent performance"""
        perf = self.agent_performance["SIZING_AGENT"]
        
        rr_ratio = response_data.get("rr_ratio", 0)
        perf["risk_reward_ratio"] = (
            (perf["risk_reward_ratio"] * (perf["successful_calls"] - 1) + rr_ratio) 
            / perf["successful_calls"]
        )
    
    def record_trade_outcome(self, trade_data: Dict, outcome: Dict):
        """Record actual trade outcomes for learning"""
        
        trade_record = {
            "timestamp": datetime.now().isoformat(),
            "trade": trade_data,
            "outcome": outcome,
            "agent_contributions": self._analyze_agent_contributions(trade_data),
            "learning_insights": self._generate_learning_insights(trade_data, outcome)
        }
        
        self.trade_outcomes.append(trade_record)
        self._update_learning_metrics()
    
    def _analyze_agent_contributions(self, trade_data: Dict) -> Dict:
        """Analyze how each agent contributed to the trade outcome"""
        
        contributions = {}
        
        # Signal agent contribution
        signals = trade_data.get("signals", {}).get("signals", [])
        if signals:
            avg_confidence = sum(s.get("confidence", 0) for s in signals) / len(signals)
            contributions["SIGNAL_AGENT"] = {
                "signal_count": len(signals),
                "avg_confidence": avg_confidence,
                "signal_quality": "high" if avg_confidence > 0.8 else "medium" if avg_confidence > 0.6 else "low"
            }
        
        # Consensus agent contribution
        consensus = trade_data.get("consensus", {})
        contributions["CONSENSUS_AGENT"] = {
            "agreement_ratio": consensus.get("agreement_ratio", 0),
            "signal_strength": consensus.get("signal_strength", 0),
            "consensus_quality": "strong" if consensus.get("agreement_ratio", 0) > 0.8 else "moderate"
        }
        
        # Risk agent contribution
        risk = trade_data.get("risk", {})
        contributions["RISK_AGENT"] = {
            "risk_score": risk.get("risk_score", 0),
            "approved": risk.get("approved", False),
            "risk_management": "conservative" if risk.get("risk_score", 0) < 0.3 else "moderate"
        }
        
        # Sizing agent contribution
        sizing = trade_data.get("sizing", {})
        contributions["SIZING_AGENT"] = {
            "position_size": sizing.get("units", 0),
            "rr_ratio": sizing.get("rr_ratio", 0),
            "sizing_quality": "optimal" if sizing.get("rr_ratio", 0) > 2.0 else "acceptable"
        }
        
        return contributions
    
    def _generate_learning_insights(self, trade_data: Dict, outcome: Dict) -> List[str]:
        """Generate learning insights from trade outcome"""
        
        insights = []
        
        pnl = outcome.get("pnl", 0)
        direction = trade_data.get("decision", {}).get("DECISION", "FLAT")
        
        # Performance insights
        if pnl > 0:
            insights.append("Profitable trade - analyze contributing factors")
            
            # Check which agents performed well
            consensus = trade_data.get("consensus", {})
            if consensus.get("agreement_ratio", 0) > 0.8:
                insights.append("High consensus correlated with profit")
            
            sizing = trade_data.get("sizing", {})
            if sizing.get("rr_ratio", 0) > 2.0:
                insights.append("Good risk/reward ratio achieved")
                
        else:
            insights.append("Loss trade - identify failure points")
            
            # Check for issues
            risk = trade_data.get("risk", {})
            if risk.get("risk_score", 0) > 0.7:
                insights.append("High risk score may have contributed to loss")
        
        return insights
    
    def _update_learning_metrics(self):
        """Update overall learning metrics"""
        
        if not self.trade_outcomes:
            return
        
        # Calculate win rate
        wins = sum(1 for t in self.trade_outcomes if t["outcome"].get("pnl", 0) > 0)
        self.learning_metrics["total_trades"] = len(self.trade_outcomes)
        self.learning_metrics["win_rate"] = wins / len(self.trade_outcomes)
        
        # Calculate average return
        total_pnl = sum(t["outcome"].get("pnl", 0) for t in self.trade_outcomes)
        self.learning_metrics["avg_return"] = total_pnl / len(self.trade_outcomes)
        
        # Analyze agent contributions to wins vs losses
        self._analyze_agent_effectiveness()
    
    def _analyze_agent_effectiveness(self):
        """Analyze which agents contribute most to successful trades"""
        
        winning_trades = [t for t in self.trade_outcomes if t["outcome"].get("pnl", 0) > 0]
        losing_trades = [t for t in self.trade_outcomes if t["outcome"].get("pnl", 0) < 0]
        
        for agent in ["SIGNAL_AGENT", "CONSENSUS_AGENT", "RISK_AGENT", "SIZING_AGENT"]:
            win_contributions = []
            loss_contributions = []
            
            for trade in winning_trades:
                contrib = trade["agent_contributions"].get(agent, {})
                win_contributions.append(contrib)
            
            for trade in losing_trades:
                contrib = trade["agent_contributions"].get(agent, {})
                loss_contributions.append(contrib)
            
            self.learning_metrics["agent_contributions"][agent] = {
                "winning_trades": len(winning_trades),
                "losing_trades": len(losing_trades),
                "win_rate_in_wins": len(winning_trades) / max(len(winning_trades), 1),
                "avg_performance": self._calculate_agent_performance_score(win_contributions, loss_contributions)
            }
    
    def _calculate_agent_performance_score(self, wins: List[Dict], losses: List[Dict]) -> float:
        """Calculate performance score for an agent"""
        
        if not wins and not losses:
            return 0.5
        
        score = 0.5  # Base score
        
        # Bonus for wins
        if wins:
            for win in wins:
                if win.get("signal_quality") == "high":
                    score += 0.1
                if win.get("consensus_quality") == "strong":
                    score += 0.1
                if win.get("risk_management") == "conservative":
                    score += 0.1
                if win.get("sizing_quality") == "optimal":
                    score += 0.1
        
        # Penalty for losses
        if losses:
            for loss in losses:
                if loss.get("signal_quality") == "low":
                    score -= 0.1
                if loss.get("consensus_quality") == "weak":
                    score -= 0.1
                if loss.get("risk_management") == "aggressive":
                    score -= 0.1
                if loss.get("sizing_quality") == "poor":
                    score -= 0.1
        
        return max(0, min(1, score))
    
    def generate_improvement_recommendations(self) -> Dict[str, List[str]]:
        """Generate improvement recommendations for each agent"""
        
        recommendations = {}
        
        for agent_name, perf in self.agent_performance.items():
            agent_recs = []
            
            # Success rate
            success_rate = perf["successful_calls"] / max(perf["total_calls"], 1)
            if success_rate < 0.8:
                agent_recs.append(f"Low success rate ({success_rate:.1%}) - review error handling")
            
            # Response time
            if perf["avg_response_time"] > 5.0:
                agent_recs.append(f"Slow response time ({perf['avg_response_time']:.1f}s) - optimize prompts")
            
            # Agent-specific recommendations
            if agent_name == "SIGNAL_AGENT":
                conf_calib = perf["confidence_calibration"]
                if conf_calib:
                    avg_conf = sum(conf_calib) / len(conf_calib)
                    if avg_conf > 0.9:
                        agent_recs.append("Overconfident signals - calibrate confidence scores")
                    elif avg_conf < 0.6:
                        agent_recs.append("Low confidence - improve signal detection")
            
            elif agent_name == "CONSENSUS_AGENT":
                if perf["agreement_accuracy"] < 0.7:
                    agent_recs.append("Poor agreement detection - review consensus logic")
            
            elif agent_name == "RISK_AGENT":
                if perf["veto_accuracy"] > 0.3:
                    agent_recs.append("High veto rate - review risk criteria")
            
            elif agent_name == "SIZING_AGENT":
                if perf["risk_reward_ratio"] < 1.5:
                    agent_recs.append("Low risk/reward ratios - improve position sizing")
            
            recommendations[agent_name] = agent_recs
        
        return recommendations
    
    def get_learning_dashboard_data(self) -> Dict[str, Any]:
        """Get data for learning dashboard"""
        
        return {
            "agent_performance": self.agent_performance,
            "learning_metrics": self.learning_metrics,
            "recent_trades": self.trade_outcomes[-10:],  # Last 10 trades
            "improvement_recommendations": self.generate_improvement_recommendations(),
            "learning_trends": self._calculate_learning_trends()
        }
    
    def _calculate_learning_trends(self) -> Dict[str, Any]:
        """Calculate learning trends over time"""
        
        if len(self.trade_outcomes) < 10:
            return {"message": "Insufficient data for trends"}
        
        # Compare recent vs older performance
        recent_trades = self.trade_outcomes[-5:]
        older_trades = self.trade_outcomes[-10:-5]
        
        recent_win_rate = sum(1 for t in recent_trades if t["outcome"].get("pnl", 0) > 0) / len(recent_trades)
        older_win_rate = sum(1 for t in older_trades if t["outcome"].get("pnl", 0) > 0) / len(older_trades)
        
        trend = "improving" if recent_win_rate > older_win_rate else "declining" if recent_win_rate < older_win_rate else "stable"
        
        return {
            "trend": trend,
            "recent_win_rate": recent_win_rate,
            "older_win_rate": older_win_rate,
            "improvement": (recent_win_rate - older_win_rate) * 100
        }
