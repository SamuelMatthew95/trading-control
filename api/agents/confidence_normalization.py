"""
Confidence normalization system for agent outputs.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

NORMALIZATION:
- Derives confidence from measurable signals
- Normalizes confidence across agents (0-1 scale)
- Penalizes arbitrary confidence scores
- Provides performance-based confidence adjustment
"""

from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from api.observability import log_structured
from api.core.models.trade_ledger import TradeLedger


class ConfidenceNormalizer:
    """Normalizes and validates agent confidence scores."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def normalize_agent_confidence(
        self, 
        agent_id: str, 
        signal_confidence: Optional[float]
    ) -> float:
        """Normalize confidence score based on agent performance."""
        try:
            # Get agent's historical performance
            stmt = select(
                func.avg(TradeLedger.confidence_score),
                func.count(TradeLedger.trade_id),
                func.avg(TradeLedger.pnl_realized),
            ).where(
                and_(
                    TradeLedger.agent_id == agent_id,
                    TradeLedger.confidence_score.isnot(None),
                )
            )
            
            result = await self.session.execute(stmt)
            performance_data = result.first()
            
            if not performance_data:
                # No performance history - use default normalization
                return self._normalize_default_confidence(signal_confidence)
            
            avg_confidence = float(performance_data[0] or 0.5)
            avg_pnl = float(performance_data[2] or 0)
            trade_count = performance_data[1] or 1
            
            # Performance-based adjustment
            performance_multiplier = 1.0
            if avg_pnl > 0:
                performance_multiplier = min(1.2, 1 + (avg_pnl / 1000))
            elif avg_pnl < 0:
                performance_multiplier = max(0.8, 1 + (avg_pnl / 1000))
            
            # Normalize to 0-1 scale
            normalized_confidence = (signal_confidence or 0.5) * performance_multiplier
            
            # Clamp to valid range
            final_confidence = max(0.0, min(1.0, normalized_confidence))
            
            log_structured(
                "debug",
                "confidence_normalized",
                agent_id=agent_id,
                signal_confidence=signal_confidence,
                normalized_confidence=final_confidence,
                performance_multiplier=performance_multiplier,
            )
            
            return final_confidence
            
        except Exception as e:
            log_structured(
                "error",
                "confidence_normalization_error",
                agent_id=agent_id,
                error=str(e),
            )
            return self._normalize_default_confidence(signal_confidence)
    
    def _normalize_default_confidence(self, signal_confidence: Optional[float]) -> float:
        """Default normalization without performance data."""
        if signal_confidence is None:
            return 0.5
        
        # Penalize arbitrary high confidence scores
        if signal_confidence > 0.9:
            return 0.7  # Arbitrary high confidence penalty
        elif signal_confidence < 0.1:
            return 0.3  # Arbitrary low confidence penalty
        
        return min(1.0, max(0.0, signal_confidence))
    
    async def get_agent_confidence_stats(self, agent_id: str, days: int = 30) -> Dict[str, Any]:
        """Get agent confidence statistics for monitoring."""
        try:
            # Get recent confidence scores
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            stmt = select(
                func.avg(TradeLedger.confidence_score),
                func.min(TradeLedger.confidence_score),
                func.max(TradeLedger.confidence_score),
                func.count(TradeLedger.trade_id),
            ).where(
                and_(
                    TradeLedger.agent_id == agent_id,
                    TradeLedger.confidence_score.isnot(None),
                    TradeLedger.created_at >= cutoff_date,
                )
            )
            
            result = await self.session.execute(stmt)
            stats = result.first()
            
            if not stats:
                return {
                    "agent_id": agent_id,
                    "period_days": days,
                    "avg_confidence": 0.5,
                    "min_confidence": 0.5,
                    "max_confidence": 0.5,
                    "total_signals": 0,
                }
            
            return {
                "agent_id": agent_id,
                "period_days": days,
                "avg_confidence": float(stats[0] or 0.5),
                "min_confidence": float(stats[1] or 0.5),
                "max_confidence": float(stats[2] or 0.5),
                "total_signals": stats[3] or 0,
                "normalization_active": True,
            }
            
        except Exception as e:
            log_structured(
                "error",
                "confidence_stats_error",
                agent_id=agent_id,
                error=str(e),
            )
            return {
                "agent_id": agent_id,
                "error": str(e),
            }
    
    async def validate_confidence_range(self, confidence: float) -> bool:
        """Validate confidence is within acceptable range."""
        return 0.0 <= confidence <= 1.0
    
    async def detect_confidence_anomalies(self, agent_id: str, hours: int = 24) -> List[Dict[str, Any]]:
        """Detect anomalous confidence patterns."""
        try:
            # Get recent confidence scores
            cutoff_date = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            stmt = select(
                TradeLedger.confidence_score,
                TradeLedger.created_at,
            ).where(
                and_(
                    TradeLedger.agent_id == agent_id,
                    TradeLedger.confidence_score.isnot(None),
                    TradeLedger.created_at >= cutoff_date,
                )
            ).order_by(TradeLedger.created_at.desc())
            
            result = await self.session.execute(stmt)
            recent_scores = result.scalars().all()
            
            if len(recent_scores) < 10:
                return []
            
            # Calculate statistics
            scores = [float(score.confidence_score) for score in recent_scores]
            avg_score = sum(scores) / len(scores)
            
            # Detect anomalies (>2 std dev from mean)
            anomalies = []
            for i, score in enumerate(scores):
                if abs(score - avg_score) > 2 * (sum((s - avg_score) ** 2 for s in scores) / len(scores)) ** 0.5:
                    anomalies.append({
                        "timestamp": recent_scores[i].created_at.isoformat(),
                        "confidence_score": score,
                        "deviation_from_mean": score - avg_score,
                        "anomaly_type": "high_confidence" if score > avg_score else "low_confidence",
                    })
            
            log_structured(
                "info",
                "confidence_anomalies_detected",
                agent_id=agent_id,
                anomalies_count=len(anomalies),
                period_hours=hours,
            )
            
            return anomalies
            
        except Exception as e:
            log_structured(
                "error",
                "confidence_anomaly_detection_error",
                agent_id=agent_id,
                error=str(e),
            )
            return []
