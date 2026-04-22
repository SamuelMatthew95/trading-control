"""
Global system consistency checker for anomaly detection.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

CONSISTENCY CHECKING:
- OPEN positions match CLOSE events
- P&L consistency across system
- Duplicate detection across all agents
- Anomaly detection for trading patterns
"""

from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_

from api.observability import log_structured
from api.core.models.trade_ledger import TradeLedger


class AnomalyType(Enum):
    DUPLICATE_TRADES = "duplicate_trades"
    MISSING_CLOSE = "missing_close"
    NEGATIVE_BALANCE_SPIKE = "negative_balance_spike"
    UNUSUAL_VOLUME = "unusual_volume"
    CONFIDENCE_ANOMALY = "confidence_anomaly"
    POSITION_MISMATCH = "position_mismatch"


@dataclass
class ConsistencyIssue:
    """System consistency issue detected."""
    anomaly_type: AnomalyType
    severity: str  # low, medium, high, critical
    description: str
    affected_agents: List[str]
    affected_symbols: List[str]
    data: Dict[str, Any]
    timestamp: datetime


class SystemConsistencyChecker:
    """Global system consistency checker for anomaly detection."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def run_full_consistency_check(self) -> List[ConsistencyIssue]:
        """Run comprehensive consistency check across all agents."""
        issues = []
        
        try:
            # Check 1: Duplicate trade detection
            duplicate_issues = await self._check_duplicate_trades()
            issues.extend(duplicate_issues)
            
            # Check 2: Missing close events
            missing_close_issues = await self._check_missing_closes()
            issues.extend(missing_close_issues)
            
            # Check 3: Negative balance spikes
            balance_issues = await self._check_balance_anomalies()
            issues.extend(balance_issues)
            
            # Check 4: Unusual volume patterns
            volume_issues = await self._check_volume_anomalies()
            issues.extend(volume_issues)
            
            # Check 5: Position mismatches
            position_issues = await self._check_position_mismatches()
            issues.extend(position_issues)
            
            log_structured(
                "info",
                "system_consistency_check_completed",
                total_issues=len(issues),
                issue_types=[issue.anomaly_type.value for issue in issues],
            )
            
            return issues
            
        except Exception as e:
            log_structured(
                "error",
                "system_consistency_check_error",
                error=str(e),
                exc_info=True,
            )
            
            return [ConsistencyIssue(
                anomaly_type=AnomalyType.NEGATIVE_BALANCE_SPIKE,
                severity="critical",
                description=f"Consistency check failed: {str(e)}",
                affected_agents=[],
                affected_symbols=[],
                data={"error": str(e)},
                timestamp=datetime.now(timezone.utc),
            )]
    
    async def _check_duplicate_trades(self) -> List[ConsistencyIssue]:
        """Check for duplicate trades across all agents."""
        # Find signal_ids appearing multiple times
        stmt = select(
            TradeLedger.trace_id,
            func.count(TradeLedger.trade_id).label('count'),
            func.array_agg(TradeLedger.agent_id).label('agents'),
        ).group_by(TradeLedger.trace_id).having(
            func.count(TradeLedger.trade_id) > 1
        )
        
        result = await self.session.execute(stmt)
        issues = []
        
        for row in result:
            issues.append(ConsistencyIssue(
                anomaly_type=AnomalyType.DUPLICATE_TRADES,
                severity="high",
                description=f"Signal ID {row.trace_id} appears {row.count} times",
                affected_agents=list(row.agents or []),
                affected_symbols=[],
                data={
                    "signal_id": row.trace_id,
                    "duplicate_count": row.count,
                    "agents": list(row.agents or []),
                },
                timestamp=datetime.now(timezone.utc),
            ))
        
        return issues
    
    async def _check_missing_closes(self) -> List[ConsistencyIssue]:
        """Check for BUY trades without corresponding SELL closes."""
        # Find BUY trades that have been open too long (>24 hours)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
        
        stmt = select(TradeLedger).where(
            and_(
                TradeLedger.trade_type == "BUY",
                TradeLedger.status == "OPEN",
                TradeLedger.created_at < cutoff_time,
            )
        )
        
        result = await self.session.execute(stmt)
        stale_buys = result.scalars().all()
        
        issues = []
        for trade in stale_buys:
            issues.append(ConsistencyIssue(
                anomaly_type=AnomalyType.MISSING_CLOSE,
                severity="medium",
                description=f"BUY trade {trade.trade_id} open for >24 hours",
                affected_agents=[trade.agent_id],
                affected_symbols=[trade.symbol],
                data={
                    "trade_id": str(trade.trade_id),
                    "symbol": trade.symbol,
                    "open_hours": (datetime.now(timezone.utc) - trade.created_at).total_seconds() / 3600,
                },
                timestamp=datetime.now(timezone.utc),
            ))
        
        return issues
    
    async def _check_balance_anomalies(self) -> List[ConsistencyIssue]:
        """Check for negative balance spikes or unusual P&L patterns."""
        # Calculate daily P&L changes
        daily_pnl_stmt = select(
            func.date(TradeLedger.created_at).label('date'),
            func.sum(TradeLedger.pnl_realized).label('daily_pnl'),
            func.count(TradeLedger.trade_id).label('trade_count'),
        ).where(
            and_(
                TradeLedger.pnl_realized.isnot(None),
                TradeLedger.created_at >= datetime.now(timezone.utc) - timedelta(days=7)
            )
        ).group_by(func.date(TradeLedger.created_at))
        
        result = await self.session.execute(daily_pnl_stmt)
        daily_data = result.all()
        
        issues = []
        for day_data in daily_data:
            if day_data.daily_pnl and day_data.daily_pnl < -10000:  # Large loss threshold
                issues.append(ConsistencyIssue(
                    anomaly_type=AnomalyType.NEGATIVE_BALANCE_SPIKE,
                    severity="high",
                    description=f"Large daily loss: ${day_data.daily_pnl}",
                    affected_agents=[],
                    affected_symbols=[],
                    data={
                        "date": str(day_data.date),
                        "daily_pnl": float(day_data.daily_pnl),
                        "trade_count": day_data.trade_count,
                    },
                    timestamp=datetime.now(timezone.utc),
                ))
        
        return issues
    
    async def _check_volume_anomalies(self) -> List[ConsistencyIssue]:
        """Check for unusual trading volume patterns."""
        # Calculate hourly trade volumes
        hourly_volume_stmt = select(
            func.date_trunc('hour', TradeLedger.created_at).label('hour'),
            func.count(TradeLedger.trade_id).label('trade_count'),
            func.array_agg(TradeLedger.agent_id).label('agents'),
        ).where(
            TradeLedger.created_at >= datetime.now(timezone.utc) - timedelta(hours=24)
        ).group_by(func.date_trunc('hour', TradeLedger.created_at))
        
        result = await self.session.execute(hourly_volume_stmt)
        hourly_data = result.all()
        
        # Calculate average and detect anomalies
        volumes = [row.trade_count for row in hourly_data]
        if not volumes:
            return []
        
        avg_volume = sum(volumes) / len(volumes)
        std_volume = (sum((v - avg_volume) ** 2 for v in volumes) / len(volumes)) ** 0.5
        
        issues = []
        for hour_data in hourly_data:
            if abs(hour_data.trade_count - avg_volume) > 3 * std_volume:  # 3 sigma threshold
                issues.append(ConsistencyIssue(
                    anomaly_type=AnomalyType.UNUSUAL_VOLUME,
                    severity="medium",
                    description=f"Unusual trading volume: {hour_data.trade_count} trades in hour {hour_data.hour}",
                    affected_agents=list(hour_data.agents or []),
                    affected_symbols=[],
                    data={
                        "hour": str(hour_data.hour),
                        "trade_count": hour_data.trade_count,
                        "avg_volume": avg_volume,
                        "std_volume": std_volume,
                    },
                    timestamp=datetime.now(timezone.utc),
                ))
        
        return issues
    
    async def _check_position_mismatches(self) -> List[ConsistencyIssue]:
        """Check for position mismatches between agents and symbols."""
        # Find cases where multiple agents have conflicting positions
        stmt = select(
            TradeLedger.symbol,
            func.array_agg(TradeLedger.agent_id).label('agents'),
            func.sum(
                func.case(
                    (TradeLedger.trade_type == "BUY", TradeLedger.quantity),
                    else_=0
                )
            ).label('total_buy_quantity'),
            func.sum(
                func.case(
                    (TradeLedger.trade_type == "SELL", TradeLedger.quantity),
                    else_=0
                )
            ).label('total_sell_quantity'),
        ).where(
            TradeLedger.status == "OPEN"
        ).group_by(TradeLedger.symbol).having(
            func.count(TradeLedger.agent_id) > 1
        )
        
        result = await self.session.execute(stmt)
        conflicts = result.all()
        
        issues = []
        for conflict in conflicts:
            net_position = conflict.total_buy_quantity - conflict.total_sell_quantity
            if abs(net_position) > 0.1:  # Small tolerance for rounding
                issues.append(ConsistencyIssue(
                    anomaly_type=AnomalyType.POSITION_MISMATCH,
                    severity="medium",
                    description=f"Position mismatch for {conflict.symbol}: {net_position}",
                    affected_agents=list(conflict.agents or []),
                    affected_symbols=[conflict.symbol],
                    data={
                        "symbol": conflict.symbol,
                        "total_buy": float(conflict.total_buy_quantity),
                        "total_sell": float(conflict.total_sell_quantity),
                        "net_position": float(net_position),
                        "agents": list(conflict.agents or []),
                    },
                    timestamp=datetime.now(timezone.utc),
                ))
        
        return issues
