"""
Performance Analytics - P&L calculation and agent grading engine.

This service provides real-time P&L calculations and agent performance metrics
that power the dashboard with meaningful data instead of empty placeholders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.models.trade_ledger import TradeLedger


@dataclass
class PortfolioMetrics:
    """Portfolio performance metrics."""

    total_pnl: Decimal
    daily_pnl: Decimal
    win_rate: float
    total_trades: int
    open_positions: int
    winning_trades: int
    losing_trades: int
    avg_win: Decimal
    avg_loss: Decimal
    profit_factor: float
    sharpe_ratio: float | None
    max_drawdown: Decimal | None


@dataclass
class AgentPerformance:
    """Individual agent performance metrics."""

    agent_id: str
    grade: str
    total_trades: int
    win_rate: float
    total_pnl: Decimal
    avg_pnl: Decimal
    winning_trades: int
    losing_trades: int
    avg_win: Decimal
    avg_loss: Decimal
    profit_factor: float
    recent_performance: list[dict[str, Any]]
    risk_score: float
    consistency_score: float


class PerformanceAnalytics:
    """
    P&L calculation and agent grading engine.

    This service transforms raw trade data into actionable insights
    that power the dashboard and agent management systems.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_portfolio_metrics(
        self,
        agent_id: str | None = None,
        strategy_id: str | None = None,
        lookback_days: int = 30,
    ) -> PortfolioMetrics:
        """
        Calculate comprehensive portfolio metrics.

        Args:
            agent_id: Filter by specific agent
            strategy_id: Filter by specific strategy
            lookback_days: Lookback period for calculations

        Returns:
            PortfolioMetrics object with all performance data
        """

        datetime.now(timezone.utc) - timedelta(days=lookback_days)
        today_start = datetime.combine(
            datetime.now(timezone.utc).date(), datetime.min.time()
        ).replace(tzinfo=timezone.utc)

        # Base query filters
        base_filters = [TradeLedger.status == "CLOSED"]
        if agent_id:
            base_filters.append(TradeLedger.agent_id == agent_id)
        if strategy_id:
            base_filters.append(TradeLedger.strategy_id == strategy_id)

        # Total P&L (all time)
        total_pnl_query = select(func.sum(TradeLedger.pnl_realized)).where(and_(*base_filters))
        total_pnl_result = await self.session.execute(total_pnl_query)
        total_pnl = total_pnl_result.scalar() or Decimal("0")

        # Daily P&L (today only)
        daily_pnl_query = select(func.sum(TradeLedger.pnl_realized)).where(
            and_(*base_filters, TradeLedger.closed_at >= today_start)
        )
        daily_pnl_result = await self.session.execute(daily_pnl_query)
        daily_pnl = daily_pnl_result.scalar() or Decimal("0")

        # Trade statistics
        trade_stats_query = select(
            func.count(TradeLedger.trade_id).label("total_trades"),
            func.sum(
                case(
                    (TradeLedger.pnl_realized > 0, 1),
                    else_=0,
                )
            ).label("winning_trades"),
            func.sum(
                case(
                    (TradeLedger.pnl_realized < 0, 1),
                    else_=0,
                )
            ).label("losing_trades"),
            func.avg(
                case(
                    (TradeLedger.pnl_realized > 0, TradeLedger.pnl_realized),
                    else_=None,
                )
            ).label("avg_win"),
            func.avg(
                case(
                    (TradeLedger.pnl_realized < 0, TradeLedger.pnl_realized),
                    else_=None,
                )
            ).label("avg_loss"),
            func.sum(
                case(
                    (TradeLedger.pnl_realized > 0, TradeLedger.pnl_realized),
                    else_=0,
                )
            ).label("total_wins"),
            func.sum(
                case(
                    (TradeLedger.pnl_realized < 0, TradeLedger.pnl_realized),
                    else_=0,
                )
            ).label("total_losses"),
        ).where(and_(*base_filters))

        trade_stats_result = await self.session.execute(trade_stats_query)
        stats = trade_stats_result.first()

        total_trades = stats.total_trades or 0
        winning_trades = stats.winning_trades or 0
        losing_trades = stats.losing_trades or 0
        avg_win = stats.avg_win or Decimal("0")
        avg_loss = stats.avg_loss or Decimal("0")
        total_wins = stats.total_wins or Decimal("0")
        total_losses = abs(stats.total_losses or Decimal("0"))

        # Calculate derived metrics
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        profit_factor = (total_wins / total_losses) if total_losses > 0 else float("inf")

        # Open positions
        open_positions_query = select(func.count(TradeLedger.trade_id)).where(
            and_(
                TradeLedger.status == "OPEN",
                *([TradeLedger.agent_id == agent_id] if agent_id else []),
                *([TradeLedger.strategy_id == strategy_id] if strategy_id else []),
            )
        )
        open_positions_result = await self.session.execute(open_positions_query)
        open_positions = open_positions_result.scalar() or 0

        # Calculate Sharpe ratio and max drawdown (simplified versions)
        sharpe_ratio = await self._calculate_sharpe_ratio(base_filters)
        max_drawdown = await self._calculate_max_drawdown(base_filters)

        return PortfolioMetrics(
            total_pnl=total_pnl,
            daily_pnl=daily_pnl,
            win_rate=win_rate,
            total_trades=total_trades,
            open_positions=open_positions,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
        )

    async def get_agent_performance(
        self,
        agent_id: str,
        lookback_days: int = 30,
    ) -> AgentPerformance:
        """
        Calculate comprehensive agent performance for grading.

        Args:
            agent_id: The agent to analyze
            lookback_days: Lookback period for analysis

        Returns:
            AgentPerformance object with detailed metrics
        """

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        # Get agent's trade statistics
        base_filters = [
            TradeLedger.agent_id == agent_id,
            TradeLedger.status == "CLOSED",
            TradeLedger.closed_at >= cutoff_date,
        ]

        trade_stats_query = select(
            func.count(TradeLedger.trade_id).label("total_trades"),
            func.sum(
                case(
                    (TradeLedger.pnl_realized > 0, 1),
                    else_=0,
                )
            ).label("winning_trades"),
            func.sum(
                case(
                    (TradeLedger.pnl_realized < 0, 1),
                    else_=0,
                )
            ).label("losing_trades"),
            func.sum(TradeLedger.pnl_realized).label("total_pnl"),
            func.avg(TradeLedger.pnl_realized).label("avg_pnl"),
            func.avg(
                case(
                    (TradeLedger.pnl_realized > 0, TradeLedger.pnl_realized),
                    else_=None,
                )
            ).label("avg_win"),
            func.avg(
                case(
                    (TradeLedger.pnl_realized < 0, TradeLedger.pnl_realized),
                    else_=None,
                )
            ).label("avg_loss"),
            func.sum(
                case(
                    (TradeLedger.pnl_realized > 0, TradeLedger.pnl_realized),
                    else_=0,
                )
            ).label("total_wins"),
            func.sum(
                case(
                    (TradeLedger.pnl_realized < 0, TradeLedger.pnl_realized),
                    else_=0,
                )
            ).label("total_losses"),
        ).where(and_(*base_filters))

        trade_stats_result = await self.session.execute(trade_stats_query)
        stats = trade_stats_result.first()

        total_trades = stats.total_trades or 0
        winning_trades = stats.winning_trades or 0
        losing_trades = stats.losing_trades or 0
        total_pnl = stats.total_pnl or Decimal("0")
        avg_pnl = stats.avg_pnl or Decimal("0")
        avg_win = stats.avg_win or Decimal("0")
        avg_loss = stats.avg_loss or Decimal("0")
        total_wins = stats.total_wins or Decimal("0")
        total_losses = abs(stats.total_losses or Decimal("0"))

        # Calculate derived metrics
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        profit_factor = (total_wins / total_losses) if total_losses > 0 else float("inf")

        # Get recent trades for performance trend
        recent_trades_query = (
            select(TradeLedger)
            .where(and_(*base_filters))
            .order_by(desc(TradeLedger.closed_at))
            .limit(10)
        )
        recent_trades_result = await self.session.execute(recent_trades_query)
        recent_trades = recent_trades_result.scalars().all()

        recent_performance = [
            {
                "trade_id": str(trade.trade_id),
                "symbol": trade.symbol,
                "trade_type": trade.trade_type,
                "pnl": float(trade.pnl_realized),
                "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
                "execution_mode": trade.execution_mode,
            }
            for trade in recent_trades
        ]

        # Calculate risk and consistency scores
        risk_score = self._calculate_risk_score(win_rate, profit_factor, avg_loss)
        consistency_score = self._calculate_consistency_score(recent_performance)

        # Calculate grade
        grade = self._calculate_agent_grade(
            win_rate=win_rate,
            total_pnl=total_pnl,
            total_trades=total_trades,
            profit_factor=profit_factor,
            risk_score=risk_score,
            consistency_score=consistency_score,
        )

        return AgentPerformance(
            agent_id=agent_id,
            grade=grade,
            total_trades=total_trades,
            win_rate=win_rate,
            total_pnl=total_pnl,
            avg_pnl=avg_pnl,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            recent_performance=recent_performance,
            risk_score=risk_score,
            consistency_score=consistency_score,
        )

    async def get_top_agents(
        self,
        limit: int = 10,
        lookback_days: int = 30,
        sort_by: str = "total_pnl",
    ) -> list[AgentPerformance]:
        """
        Get top-performing agents by various metrics.

        Args:
            limit: Maximum number of agents to return
            lookback_days: Lookback period for analysis
            sort_by: Metric to sort by (total_pnl, win_rate, profit_factor)

        Returns:
            List of AgentPerformance objects sorted by the specified metric
        """

        # Get all unique agent IDs
        agents_query = select(TradeLedger.agent_id).where(TradeLedger.status == "CLOSED").distinct()
        agents_result = await self.session.execute(agents_query)
        agent_ids = [row[0] for row in agents_result.fetchall()]

        # Calculate performance for each agent
        agent_performances = []
        for agent_id in agent_ids:
            performance = await self.get_agent_performance(agent_id, lookback_days)
            if performance.total_trades >= 5:  # Only include agents with sufficient trades
                agent_performances.append(performance)

        # Sort by the specified metric
        if sort_by == "total_pnl":
            agent_performances.sort(key=lambda x: x.total_pnl, reverse=True)
        elif sort_by == "win_rate":
            agent_performances.sort(key=lambda x: x.win_rate, reverse=True)
        elif sort_by == "profit_factor":
            agent_performances.sort(key=lambda x: x.profit_factor, reverse=True)

        return agent_performances[:limit]

    async def _calculate_sharpe_ratio(self, base_filters: list[Any]) -> float | None:
        """Calculate simplified Sharpe ratio."""
        # This is a simplified calculation - in production, you'd want
        # more sophisticated risk-adjusted return calculations
        return None  # Placeholder for now

    async def _calculate_max_drawdown(self, base_filters: list[Any]) -> Decimal | None:
        """Calculate maximum drawdown."""
        # This would require tracking portfolio value over time
        # For now, return None as placeholder
        return None

    def _calculate_risk_score(
        self,
        win_rate: float,
        profit_factor: float,
        avg_loss: Decimal,
    ) -> float:
        """
        Calculate risk score (0-100, lower is better).

        Considers win rate, profit factor, and average loss size.
        """
        risk_score = 0

        # Win rate component (30% weight)
        if win_rate < 40:
            risk_score += 30
        elif win_rate < 50:
            risk_score += 20
        elif win_rate < 60:
            risk_score += 10
        else:
            risk_score += 0

        # Profit factor component (40% weight)
        if profit_factor < 1.0:
            risk_score += 40
        elif profit_factor < 1.5:
            risk_score += 25
        elif profit_factor < 2.0:
            risk_score += 10
        else:
            risk_score += 0

        # Average loss component (30% weight)
        if avg_loss > Decimal("1000"):
            risk_score += 30
        elif avg_loss > Decimal("500"):
            risk_score += 20
        elif avg_loss > Decimal("200"):
            risk_score += 10
        else:
            risk_score += 0

        return min(risk_score, 100)

    def _calculate_consistency_score(
        self,
        recent_performance: list[dict[str, Any]],
    ) -> float:
        """
        Calculate consistency score (0-100, higher is better).

        Measures how consistent recent performance has been.
        """
        if len(recent_performance) < 5:
            return 50  # Neutral score for insufficient data

        # Calculate win rate in recent trades
        wins = sum(1 for trade in recent_performance if trade["pnl"] > 0)
        recent_win_rate = wins / len(recent_performance) * 100

        # Calculate variance in P&L
        pnls = [trade["pnl"] for trade in recent_performance]
        avg_pnl = sum(pnls) / len(pnls)
        variance = sum((pnl - avg_pnl) ** 2 for pnl in pnls) / len(pnls)
        std_dev = variance**0.5

        # Consistency score combines win rate and low variance
        consistency = (recent_win_rate / 100) * 0.6 + (1 - min(std_dev / 1000, 1)) * 0.4
        return consistency * 100

    def _calculate_agent_grade(
        self,
        win_rate: float,
        total_pnl: Decimal,
        total_trades: int,
        profit_factor: float,
        risk_score: float,
        consistency_score: float,
    ) -> str:
        """
        Calculate overall agent grade.

        Uses multiple factors to determine the final grade.
        """
        if total_trades < 5:
            return "INSUFFICIENT_DATA"

        # Grade calculation weights
        win_rate_weight = 0.25
        pnl_weight = 0.30
        profit_factor_weight = 0.20
        risk_weight = 0.15
        consistency_weight = 0.10

        # Normalize scores (0-100 scale)
        win_rate_score = min(win_rate, 100)
        pnl_score = min(float(total_pnl) / 100 * 100, 100) if total_pnl > 0 else 0
        profit_factor_score = min(profit_factor * 25, 100)  # 4.0 = 100
        risk_score_normalized = max(100 - risk_score, 0)  # Lower risk is better

        # Calculate weighted score
        final_score = (
            win_rate_score * win_rate_weight
            + pnl_score * pnl_weight
            + profit_factor_score * profit_factor_weight
            + risk_score_normalized * risk_weight
            + consistency_score * consistency_weight
        )

        # Determine grade based on final score
        if final_score >= 85:
            return "A"
        if final_score >= 70:
            return "B"
        if final_score >= 55:
            return "C"
        if final_score >= 40:
            return "D"
        return "F"


# Factory function for dependency injection
async def get_performance_analytics(session: AsyncSession) -> PerformanceAnalytics:
    """Factory function to create PerformanceAnalytics instance."""
    return PerformanceAnalytics(session)
