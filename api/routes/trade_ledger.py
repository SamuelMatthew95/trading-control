"""
Trade Ledger API Routes - Structured trade data endpoints.

These routes provide the frontend with structured trade data instead of raw log streams,
powering the transaction architecture dashboard with real P&L and agent performance data.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_async_session
from api.observability import log_structured
from api.services.performance_analytics import PerformanceAnalytics, get_performance_analytics
from api.services.trade_ledger_service import TradeLedgerService, get_trade_ledger_service

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("/summary")
async def get_portfolio_summary(
    agent_id: str | None = Query(None, description="Filter by specific agent"),
    strategy_id: str | None = Query(None, description="Filter by specific strategy"),
    session: AsyncSession = Depends(get_async_session),
    trade_service: TradeLedgerService = Depends(get_trade_ledger_service),
    analytics: PerformanceAnalytics = Depends(get_performance_analytics),
):
    """
    Get portfolio summary for dashboard stats.

    Returns the key metrics that populate the Overview cards:
    - Daily P&L
    - Win Rate
    - Active Positions
    - Total P&L
    """
    try:
        summary = await trade_service.get_portfolio_summary(
            agent_id=agent_id,
            strategy_id=uuid.UUID(strategy_id) if strategy_id else None,
        )

        return {
            "success": True,
            "data": {
                "daily_pnl": summary["daily_pnl"],
                "total_pnl": summary["total_pnl"],
                "win_rate": summary["win_rate"],
                "open_positions": summary["open_positions"],
                "total_trades": summary["total_trades"],
            }
        }
    except Exception as e:
        log_structured(
            "error",
            "trades_summary_error",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch portfolio summary")


@router.get("/recent")
async def get_recent_trades(
    limit: int = Query(50, ge=1, le=200, description="Number of trades to return"),
    agent_id: str | None = Query(None, description="Filter by specific agent"),
    symbol: str | None = Query(None, description="Filter by symbol"),
    session: AsyncSession = Depends(get_async_session),
    trade_service: TradeLedgerService = Depends(get_trade_ledger_service),
):
    """
    Get recent trades for the dashboard feed.

    Returns the terminal-style feed that shows:
    - Green rows for BUY trades
    - Red rows for SELL trades with P&L
    - Mock/Live tags
    - Proper timestamps
    """
    try:
        trades = await trade_service.get_recent_trades(
            limit=limit,
            agent_id=agent_id,
            symbol=symbol,
        )

        formatted_trades = []
        for trade in trades:
            trade_data = {
                "trade_id": str(trade.trade_id),
                "timestamp": trade.created_at.isoformat(),
                "symbol": trade.symbol,
                "trade_type": trade.trade_type,
                "status": trade.status,
                "quantity": float(trade.quantity),
                "execution_mode": trade.execution_mode,
                "confidence_score": float(trade.confidence_score) if trade.confidence_score else None,
                "agent_id": trade.agent_id,
            }

            if trade.trade_type == "BUY":
                trade_data.update({
                    "price": float(trade.entry_price),
                    "display_text": f"🟢 BUY {trade.symbol} @ ${trade.entry_price:.2f}",
                })
            elif trade.trade_type == "SELL":
                trade_data.update({
                    "entry_price": float(trade.entry_price),
                    "exit_price": float(trade.exit_price),
                    "pnl_realized": float(trade.pnl_realized),
                    "display_text": f"🔴 SELL {trade.symbol} @ ${trade.exit_price:.2f} | P&L: ${trade.pnl_realized:+.2f}",
                })

            formatted_trades.append(trade_data)

        return {
            "success": True,
            "data": formatted_trades,
        }

    except Exception as e:
        log_structured(
            "error",
            "trades_recent_error",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch recent trades")


@router.get("/positions")
async def get_open_positions(
    agent_id: str | None = Query(None, description="Filter by specific agent"),
    strategy_id: str | None = Query(None, description="Filter by specific strategy"),
    session: AsyncSession = Depends(get_async_session),
    trade_service: TradeLedgerService = Depends(get_trade_ledger_service),
):
    """
    Get currently open positions.

    Returns all BUY trades that haven't been closed yet,
    showing the current portfolio composition.
    """
    try:
        positions = await trade_service.get_open_positions(
            agent_id=agent_id,
            strategy_id=uuid.UUID(strategy_id) if strategy_id else None,
        )

        formatted_positions = []
        for position in positions:
            formatted_positions.append({
                "trade_id": str(position.trade_id),
                "symbol": position.symbol,
                "quantity": float(position.quantity),
                "entry_price": float(position.entry_price),
                "confidence_score": float(position.confidence_score) if position.confidence_score else None,
                "execution_mode": position.execution_mode,
                "agent_id": position.agent_id,
                "created_at": position.created_at.isoformat(),
                "display_text": f"{position.symbol}: {position.quantity} @ ${position.entry_price:.2f}",
            })

        return {
            "success": True,
            "data": formatted_positions,
        }

    except Exception as e:
        log_structured(
            "error",
            "trades_positions_error",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch open positions")


@router.get("/agents/performance")
async def get_agents_performance(
    lookback_days: int = Query(30, ge=1, le=365, description="Lookback period in days"),
    session: AsyncSession = Depends(get_async_session),
    analytics: PerformanceAnalytics = Depends(get_performance_analytics),
):
    """
    Get performance metrics for all agents.

    Returns agent grading data for the Agents tab,
    including win rates, P&L, and performance grades.
    """
    try:
        agents = await analytics.get_top_agents(
            limit=50,
            lookback_days=lookback_days,
            sort_by="total_pnl",
        )

        formatted_agents = []
        for agent in agents:
            formatted_agents.append({
                "agent_id": agent.agent_id,
                "grade": agent.grade,
                "total_trades": agent.total_trades,
                "win_rate": agent.win_rate,
                "total_pnl": float(agent.total_pnl),
                "avg_pnl": float(agent.avg_pnl),
                "profit_factor": agent.profit_factor,
                "risk_score": agent.risk_score,
                "consistency_score": agent.consistency_score,
                "recent_performance": agent.recent_performance,
            })

        return {
            "success": True,
            "data": formatted_agents,
        }

    except Exception as e:
        log_structured(
            "error",
            "trades_agents_performance_error",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch agent performance")


@router.get("/agents/{agent_id}/performance")
async def get_agent_performance(
    agent_id: str,
    lookback_days: int = Query(30, ge=1, le=365, description="Lookback period in days"),
    session: AsyncSession = Depends(get_async_session),
    analytics: PerformanceAnalytics = Depends(get_performance_analytics),
):
    """
    Get detailed performance for a specific agent.

    Returns comprehensive metrics for a single agent,
    useful for agent detail pages and debugging.
    """
    try:
        performance = await analytics.get_agent_performance(
            agent_id=agent_id,
            lookback_days=lookback_days,
        )

        return {
            "success": True,
            "data": {
                "agent_id": performance.agent_id,
                "grade": performance.grade,
                "total_trades": performance.total_trades,
                "win_rate": performance.win_rate,
                "total_pnl": float(performance.total_pnl),
                "avg_pnl": float(performance.avg_pnl),
                "winning_trades": performance.winning_trades,
                "losing_trades": performance.losing_trades,
                "avg_win": float(performance.avg_win),
                "avg_loss": float(performance.avg_loss),
                "profit_factor": performance.profit_factor,
                "risk_score": performance.risk_score,
                "consistency_score": performance.consistency_score,
                "recent_performance": performance.recent_performance,
            }
        }

    except Exception as e:
        log_structured(
            "error",
            "trades_agent_performance_error",
            agent_id=agent_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch agent performance")


@router.get("/portfolio/metrics")
async def get_portfolio_metrics(
    agent_id: str | None = Query(None, description="Filter by specific agent"),
    strategy_id: str | None = Query(None, description="Filter by specific strategy"),
    lookback_days: int = Query(30, ge=1, le=365, description="Lookback period in days"),
    session: AsyncSession = Depends(get_async_session),
    analytics: PerformanceAnalytics = Depends(get_performance_analytics),
):
    """
    Get comprehensive portfolio metrics.

    Returns advanced metrics including Sharpe ratio, max drawdown,
    and other risk-adjusted performance measures.
    """
    try:
        metrics = await analytics.get_portfolio_metrics(
            agent_id=agent_id,
            strategy_id=uuid.UUID(strategy_id) if strategy_id else None,
            lookback_days=lookback_days,
        )

        return {
            "success": True,
            "data": {
                "total_pnl": float(metrics.total_pnl),
                "daily_pnl": float(metrics.daily_pnl),
                "win_rate": metrics.win_rate,
                "total_trades": metrics.total_trades,
                "open_positions": metrics.open_positions,
                "winning_trades": metrics.winning_trades,
                "losing_trades": metrics.losing_trades,
                "avg_win": float(metrics.avg_win),
                "avg_loss": float(metrics.avg_loss),
                "profit_factor": metrics.profit_factor,
                "sharpe_ratio": metrics.sharpe_ratio,
                "max_drawdown": float(metrics.max_drawdown) if metrics.max_drawdown else None,
            }
        }

    except Exception as e:
        log_structured(
            "error",
            "trades_portfolio_metrics_error",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch portfolio metrics")
