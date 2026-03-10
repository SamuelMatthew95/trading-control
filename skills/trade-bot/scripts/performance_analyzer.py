"""
Performance Analyzer Script
Track and analyze trading performance metrics
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime, timedelta

class PerformanceAnalyzer:
    """Trading performance analysis and monitoring"""
    
    def __init__(self):
        self.metrics = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0.0,
            "total_commission": 0.0,
            "max_drawdown": 0.0,
            "current_drawdown": 0.0,
            "peak_balance": 0.0
        }
    
    def analyze_trade_performance(self, trades: List[Dict[str, Any]], 
                                account_balance: float) -> Dict[str, Any]:
        """
        Analyze complete trading performance
        
        Args:
            trades: List of completed trades
            account_balance: Current account balance
        
        Returns:
            Comprehensive performance analysis
        """
        
        if not trades:
            return self._empty_performance_analysis()
        
        # Calculate basic metrics
        total_trades = len(trades)
        winning_trades = len([t for t in trades if t.get("pnl", 0) > 0])
        losing_trades = len([t for t in trades if t.get("pnl", 0) < 0])
        
        # Calculate P&L metrics
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        total_commission = sum(t.get("commission", 0) for t in trades)
        net_pnl = total_pnl - total_commission
        
        # Calculate win rate
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # Calculate average win/loss
        winning_trades_list = [t for t in trades if t.get("pnl", 0) > 0]
        losing_trades_list = [t for t in trades if t.get("pnl", 0) < 0]
        
        avg_win = np.mean([t["pnl"] for t in winning_trades_list]) if winning_trades_list else 0
        avg_loss = np.mean([t["pnl"] for t in losing_trades_list]) if losing_trades_list else 0
        
        # Calculate profit factor
        total_wins = sum(t["pnl"] for t in winning_trades_list)
        total_losses = abs(sum(t["pnl"] for t in losing_trades_list))
        profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')
        
        # Calculate drawdown
        running_balance = account_balance
        peak_balance = account_balance
        max_drawdown = 0
        current_drawdown = 0
        
        balance_series = [account_balance]
        
        for trade in trades:
            running_balance += trade.get("pnl", 0) - trade.get("commission", 0)
            balance_series.append(running_balance)
            
            if running_balance > peak_balance:
                peak_balance = running_balance
                current_drawdown = 0
            else:
                current_drawdown = (peak_balance - running_balance) / peak_balance
                max_drawdown = max(max_drawdown, current_drawdown)
        
        # Calculate Sharpe ratio (simplified)
        returns = np.diff(balance_series) / balance_series[:-1]
        sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252) if len(returns) > 1 and np.std(returns) > 0 else 0
        
        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "total_commission": total_commission,
            "net_pnl": net_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
            "current_drawdown": current_drawdown,
            "peak_balance": peak_balance,
            "current_balance": running_balance,
            "sharpe_ratio": sharpe_ratio,
            "total_return_pct": (running_balance / account_balance - 1) * 100
        }
    
    def analyze_position_performance(self, positions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze current open positions performance
        
        Args:
            positions: Dictionary of open positions
        
        Returns:
            Position performance analysis
        """
        
        if not positions:
            return {"open_positions": 0, "total_unrealized_pnl": 0.0}
        
        total_unrealized_pnl = 0
        winning_positions = 0
        losing_positions = 0
        position_details = []
        
        for symbol, position in positions.items():
            unrealized_pnl = position.get("unrealized_pnl", 0)
            entry_price = position.get("entry_price", 0)
            current_price = position.get("current_price", 0)
            position_size = position.get("size", 0)
            
            total_unrealized_pnl += unrealized_pnl
            
            if unrealized_pnl > 0:
                winning_positions += 1
            elif unrealized_pnl < 0:
                losing_positions += 1
            
            # Calculate position return
            position_return = (current_price - entry_price) / entry_price if entry_price > 0 else 0
            
            position_details.append({
                "symbol": symbol,
                "size": position_size,
                "entry_price": entry_price,
                "current_price": current_price,
                "unrealized_pnl": unrealized_pnl,
                "return_pct": position_return * 100
            })
        
        # Calculate position metrics
        open_positions = len(positions)
        win_rate = winning_positions / open_positions if open_positions > 0 else 0
        
        return {
            "open_positions": open_positions,
            "winning_positions": winning_positions,
            "losing_positions": losing_positions,
            "position_win_rate": win_rate,
            "total_unrealized_pnl": total_unrealized_pnl,
            "position_details": position_details
        }
    
    def calculate_risk_metrics(self, trades: List[Dict[str, Any]], 
                            account_balance: float) -> Dict[str, Any]:
        """
        Calculate risk-adjusted performance metrics
        
        Args:
            trades: List of completed trades
            account_balance: Starting account balance
        
        Returns:
            Risk metrics analysis
        """
        
        if not trades:
            return self._empty_risk_metrics()
        
        # Calculate daily returns (simplified)
        daily_returns = []
        running_balance = account_balance
        
        for trade in trades:
            pnl = trade.get("pnl", 0) - trade.get("commission", 0)
            return_pct = pnl / running_balance if running_balance > 0 else 0
            daily_returns.append(return_pct)
            running_balance += pnl
        
        if not daily_returns:
            return self._empty_risk_metrics()
        
        # Calculate risk metrics
        returns_array = np.array(daily_returns)
        
        # Volatility (annualized)
        volatility = np.std(returns_array) * np.sqrt(252)
        
        # Value at Risk (5%)
        var_95 = np.percentile(returns_array, 5)
        
        # Conditional Value at Risk (Expected Shortfall)
        cvar_95 = returns_array[returns_array <= var_95].mean()
        
        # Maximum drawdown (already calculated in performance analysis)
        performance = self.analyze_trade_performance(trades, account_balance)
        max_drawdown = performance.get("max_drawdown", 0)
        
        # Calmar ratio (annual return / max drawdown)
        annual_return = performance.get("total_return_pct", 0) / 100
        calmar_ratio = annual_return / max_drawdown if max_drawdown > 0 else 0
        
        # Sortino ratio (downside deviation)
        downside_returns = returns_array[returns_array < 0]
        downside_deviation = np.std(downside_returns) * np.sqrt(252) if len(downside_returns) > 0 else 0
        sortino_ratio = annual_return / downside_deviation if downside_deviation > 0 else 0
        
        return {
            "volatility": volatility,
            "var_95": var_95,
            "cvar_95": cvar_95,
            "max_drawdown": max_drawdown,
            "calmar_ratio": calmar_ratio,
            "sortino_ratio": sortino_ratio,
            "sharpe_ratio": performance.get("sharpe_ratio", 0),
            "downside_deviation": downside_deviation
        }
    
    def generate_performance_report(self, trades: List[Dict[str, Any]], 
                                  positions: Dict[str, Dict[str, Any]], 
                                  account_balance: float) -> Dict[str, Any]:
        """
        Generate comprehensive performance report
        
        Args:
            trades: Completed trades
            positions: Open positions
            account_balance: Account balance
        
        Returns:
            Complete performance report
        """
        
        # Trade performance
        trade_performance = self.analyze_trade_performance(trades, account_balance)
        
        # Position performance
        position_performance = self.analyze_position_performance(positions)
        
        # Risk metrics
        risk_metrics = self.calculate_risk_metrics(trades, account_balance)
        
        # Performance rating
        rating = self._calculate_performance_rating(trade_performance, risk_metrics)
        
        # Recommendations
        recommendations = self._generate_recommendations(trade_performance, risk_metrics)
        
        return {
            "summary": {
                "total_return": trade_performance.get("total_return_pct", 0),
                "win_rate": trade_performance.get("win_rate", 0),
                "sharpe_ratio": trade_performance.get("sharpe_ratio", 0),
                "max_drawdown": trade_performance.get("max_drawdown", 0),
                "performance_rating": rating
            },
            "trade_analysis": trade_performance,
            "position_analysis": position_performance,
            "risk_analysis": risk_metrics,
            "recommendations": recommendations,
            "generated_at": datetime.now().isoformat()
        }
    
    def _empty_performance_analysis(self) -> Dict[str, Any]:
        """Return empty performance analysis"""
        return {
            "total_trades": 0,
            "win_rate": 0,
            "total_return_pct": 0,
            "sharpe_ratio": 0,
            "max_drawdown": 0
        }
    
    def _empty_risk_metrics(self) -> Dict[str, Any]:
        """Return empty risk metrics"""
        return {
            "volatility": 0,
            "var_95": 0,
            "max_drawdown": 0,
            "sharpe_ratio": 0
        }
    
    def _calculate_performance_rating(self, performance: Dict[str, Any], 
                                   risk_metrics: Dict[str, Any]) -> str:
        """Calculate overall performance rating"""
        
        score = 0
        
        # Return score (40%)
        total_return = performance.get("total_return_pct", 0)
        if total_return > 20:
            score += 40
        elif total_return > 10:
            score += 30
        elif total_return > 5:
            score += 20
        elif total_return > 0:
            score += 10
        
        # Sharpe ratio (30%)
        sharpe = performance.get("sharpe_ratio", 0)
        if sharpe > 2:
            score += 30
        elif sharpe > 1.5:
            score += 25
        elif sharpe > 1:
            score += 20
        elif sharpe > 0.5:
            score += 15
        elif sharpe > 0:
            score += 10
        
        # Max drawdown (20%)
        max_dd = performance.get("max_drawdown", 0)
        if max_dd < 0.05:
            score += 20
        elif max_dd < 0.10:
            score += 15
        elif max_dd < 0.15:
            score += 10
        elif max_dd < 0.20:
            score += 5
        
        # Win rate (10%)
        win_rate = performance.get("win_rate", 0)
        if win_rate > 0.6:
            score += 10
        elif win_rate > 0.5:
            score += 8
        elif win_rate > 0.4:
            score += 6
        elif win_rate > 0.3:
            score += 4
        
        if score >= 80:
            return "EXCELLENT"
        elif score >= 60:
            return "GOOD"
        elif score >= 40:
            return "AVERAGE"
        elif score >= 20:
            return "POOR"
        else:
            return "VERY POOR"
    
    def _generate_recommendations(self, performance: Dict[str, Any], 
                                 risk_metrics: Dict[str, Any]) -> List[str]:
        """Generate performance recommendations"""
        
        recommendations = []
        
        # Return recommendations
        total_return = performance.get("total_return_pct", 0)
        if total_return < 0:
            recommendations.append("Consider reviewing strategy - negative returns")
        elif total_return < 5:
            recommendations.append("Returns are low - consider strategy optimization")
        
        # Risk recommendations
        max_dd = performance.get("max_drawdown", 0)
        if max_dd > 0.15:
            recommendations.append("High drawdown detected - improve risk management")
        
        # Win rate recommendations
        win_rate = performance.get("win_rate", 0)
        if win_rate < 0.4:
            recommendations.append("Low win rate - review entry criteria")
        
        # Sharpe ratio recommendations
        sharpe = performance.get("sharpe_ratio", 0)
        if sharpe < 0.5:
            recommendations.append("Low risk-adjusted returns - improve risk/reward")
        
        if not recommendations:
            recommendations.append("Performance metrics look good - continue current strategy")
        
        return recommendations
