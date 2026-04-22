"""
Global time consistency model.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

TIME CONSISTENCY:
- Event ordering guarantees
- Timestamp source authority
- Latency tolerance
- Single source of truth for timing
"""

from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, validator
from enum import Enum

from api.observability import log_structured


class TimeSource(Enum):
    AGENT_RUNTIME = "agent_runtime"
    INGESTION_TIMESTAMP = "ingestion_timestamp"
    DATABASE_TIMESTAMP = "database_timestamp"
    WEBSOCKET_TIMESTAMP = "websocket_timestamp"


class EventOrder(BaseModel):
    """Event order with timing information."""
    signal_id: str = Field(..., description="Signal identifier")
    sequence_number: int = Field(..., ge=0, description="Event sequence number")
    timestamp: datetime = Field(..., description="Event timestamp")
    time_source: TimeSource = Field(..., description="Timestamp source")
    processing_latency_ms: Optional[int] = Field(None, ge=0, description="Processing latency")
    
    @property
    def is_ingestion_timestamp(self) -> bool:
        return self.time_source == TimeSource.INGESTION_TIMESTAMP
    
    @property
    def is_agent_runtime_timestamp(self) -> bool:
        return self.time_source == TimeSource.AGENT_RUNTIME


class TimeConsistencyWindow(BaseModel):
    """Time consistency window for validation."""
    window_start: datetime = Field(..., description="Window start time")
    window_end: datetime = Field(..., description="Window end time")
    max_latency_ms: int = Field(..., ge=0, description="Maximum allowed latency")
    out_of_order_events: List[Dict[str, Any]] = Field(default_factory=list, description="Out of order events")
    
    @property
    def duration_ms(self) -> int:
        """Get window duration in milliseconds."""
        return int((self.window_end - self.window_start).total_seconds() * 1000)
    
    @property
    def is_valid_window(self) -> bool:
        """Check if window is valid."""
        return self.window_end > self.window_start


class TimeConsistencyManager:
    """Manages global time consistency across the system."""
    
    def __init__(self):
        self._event_sequence = 0
        self._time_windows: Dict[str, TimeConsistencyWindow] = {}
        self._event_orders: List[EventOrder] = []
        self._source_authority = TimeSource.INGESTION_TIMESTAMP
        self._max_latency_ms = 5000  # 5 seconds max latency
        self._clock_skew_tolerance_ms = 1000  # 1 second clock skew tolerance
    
    def set_source_authority(self, source: TimeSource) -> None:
        """Set the authoritative time source."""
        self._source_authority = source
        
        log_structured(
            "info",
            "time_source_authority_set",
            source=source.value,
        )
    
    def create_event_order(
        self,
        signal_id: str,
        agent_timestamp: Optional[datetime] = None,
        max_latency_ms: Optional[int] = None,
    ) -> EventOrder:
        """Create event order with authoritative timestamp."""
        # Use ingestion timestamp as source of truth
        authoritative_timestamp = datetime.now(timezone.utc)
        
        # Calculate processing latency if agent timestamp provided
        processing_latency_ms = None
        if agent_timestamp:
            latency = (authoritative_timestamp - agent_timestamp).total_seconds() * 1000
            processing_latency_ms = int(latency)
        
        # Set max latency
        max_latency = max_latency or self._max_latency_ms
        
        # Create event order
        event_order = EventOrder(
            signal_id=signal_id,
            sequence_number=self._event_sequence,
            timestamp=authoritative_timestamp,
            time_source=self._source_authority,
            processing_latency_ms=processing_latency_ms,
        )
        
        self._event_sequence += 1
        self._event_orders.append(event_order)
        
        log_structured(
            "debug",
            "event_order_created",
            signal_id=signal_id,
            sequence_number=event_order.sequence_number,
            timestamp=authoritative_timestamp.isoformat(),
            time_source=self._source_authority.value,
            processing_latency_ms=processing_latency_ms,
        )
        
        return event_order
    
    def validate_event_sequence(self, event_orders: List[EventOrder]) -> Dict[str, Any]:
        """Validate event sequence ordering."""
        if not event_orders:
            return {
                "valid": True,
                "issues": [],
                "total_events": 0,
            }
        
        # Sort by sequence number
        sorted_events = sorted(event_orders, key=lambda x: x.sequence_number)
        
        issues = []
        
        # Check for gaps in sequence
        for i, event in enumerate(sorted_events):
            expected_sequence = i
            if event.sequence_number != expected_sequence:
                issues.append({
                    "type": "sequence_gap",
                    "signal_id": event.signal_id,
                    "expected_sequence": expected_sequence,
                    "actual_sequence": event.sequence_number,
                    "timestamp": event.timestamp.isoformat(),
                })
        
        # Check for out-of-order timestamps
        for i in range(1, len(sorted_events)):
            current_event = sorted_events[i]
            previous_event = sorted_events[i-1]
            
            if current_event.timestamp < previous_event.timestamp:
                issues.append({
                    "type": "timestamp_out_of_order",
                    "signal_id": current_event.signal_id,
                    "current_timestamp": current_event.timestamp.isoformat(),
                    "previous_timestamp": previous_event.timestamp.isoformat(),
                    "previous_signal_id": previous_event.signal_id,
                })
        
        # Check processing latency
        for event in sorted_events:
            if event.processing_latency_ms and event.processing_latency_ms > self._max_latency_ms:
                issues.append({
                    "type": "excessive_latency",
                    "signal_id": event.signal_id,
                    "processing_latency_ms": event.processing_latency_ms,
                    "max_allowed_ms": self._max_latency_ms,
                    "timestamp": event.timestamp.isoformat(),
                })
        
        is_valid = len(issues) == 0
        
        log_structured(
            "info",
            "event_sequence_validated",
            total_events=len(event_orders),
            issues_found=len(issues),
            is_valid=is_valid,
        )
        
        return {
            "valid": is_valid,
            "issues": issues,
            "total_events": len(event_orders),
            "validation_timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    def create_time_window(
        self,
        window_start: datetime,
        window_end: datetime,
        max_latency_ms: Optional[int] = None,
    ) -> TimeConsistencyWindow:
        """Create time consistency window."""
        window = TimeConsistencyWindow(
            window_start=window_start,
            window_end=window_end,
            max_latency_ms=max_latency or self._max_latency_ms,
        )
        
        self._time_windows[f"{window_start.isoformat()}_{window_end.isoformat()}"] = window
        
        log_structured(
            "info",
            "time_window_created",
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            duration_ms=window.duration_ms,
            max_latency_ms=window.max_latency_ms,
        )
        
        return window
    
    def validate_time_consistency(self, window: TimeConsistencyWindow, events: List[EventOrder]) -> Dict[str, Any]:
        """Validate time consistency within a window."""
        # Filter events within window
        window_events = [
            event for event in events
            if window.window_start <= event.timestamp <= window.window_end
        ]
        
        issues = []
        
        # Check for events outside window
        out_of_window_events = [
            event for event in events
            if not (window.window_start <= event.timestamp <= window.window_end)
        ]
        
        for event in out_of_window_events:
            issues.append({
                "type": "event_outside_window",
                "signal_id": event.signal_id,
                "event_timestamp": event.timestamp.isoformat(),
                "window_start": window.window_start.isoformat(),
                "window_end": window.window_end.isoformat(),
            })
        
        # Check for excessive processing latency
        for event in window_events:
            if event.processing_latency_ms and event.processing_latency_ms > window.max_latency_ms:
                issues.append({
                    "type": "excessive_latency_in_window",
                    "signal_id": event.signal_id,
                    "processing_latency_ms": event.processing_latency_ms,
                    "max_allowed_ms": window.max_latency_ms,
                    "timestamp": event.timestamp.isoformat(),
                })
        
        # Update window with out-of-order events
        out_of_order_events = [
            {
                "signal_id": event.signal_id,
                "timestamp": event.timestamp.isoformat(),
                "sequence_number": event.sequence_number,
            }
            for issue in issues
            if issue["type"] == "timestamp_out_of_order"
        ]
        
        window.out_of_order_events = out_of_order_events
        
        is_valid = len(issues) == 0
        
        log_structured(
            "info",
            "time_consistency_validated",
            window_start=window.window_start.isoformat(),
            window_end=window.window_end.isoformat(),
            events_in_window=len(window_events),
            issues_found=len(issues),
            is_valid=is_valid,
        )
        
        return {
            "valid": is_valid,
            "issues": issues,
            "window": window.dict(),
            "events_in_window": len(window_events),
            "validation_timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    def get_time_statistics(self, events: List[EventOrder]) -> Dict[str, Any]:
        """Get time statistics for events."""
        if not events:
            return {
                "total_events": 0,
                "avg_processing_latency_ms": 0,
                "max_processing_latency_ms": 0,
                "min_processing_latency_ms": 0,
                "time_span_seconds": 0,
            }
        
        # Calculate statistics
        processing_latencies = [
            event.processing_latency_ms for event in events
            if event.processing_latency_ms is not None
        ]
        
        time_span = (max(event.timestamp for event in events) - 
                    min(event.timestamp for event in events)).total_seconds()
        
        stats = {
            "total_events": len(events),
            "avg_processing_latency_ms": sum(processing_latencies) / len(processing_latencies) if processing_latencies else 0,
            "max_processing_latency_ms": max(processing_latencies) if processing_latencies else 0,
            "min_processing_latency_ms": min(processing_latencies) if processing_latencies else 0,
            "time_span_seconds": time_span,
            "source_authority": self._source_authority.value,
            "max_latency_ms": self._max_latency_ms,
            "clock_skew_tolerance_ms": self._clock_skew_tolerance_ms,
            "statistics_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        log_structured(
            "info",
            "time_statistics_calculated",
            total_events=stats["total_events"],
            avg_latency_ms=stats["avg_processing_latency_ms"],
            time_span_seconds=stats["time_span_seconds"],
        )
        
        return stats
    
    def detect_clock_skew(self, events: List[EventOrder]) -> Dict[str, Any]:
        """Detect clock skew between different time sources."""
        # Group events by time source
        source_events = {}
        for event in events:
            if event.time_source not in source_events:
                source_events[event.time_source] = []
            source_events[event.time_source].append(event)
        
        # Calculate average timestamps per source
        source_averages = {}
        for source, source_event_list in source_events.items():
            if source_event_list:
                avg_timestamp = sum(
                    (event.timestamp - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()
                    for event in source_event_list
                ) / len(source_event_list)
                source_averages[source] = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=avg_timestamp)
        
        # Detect skew
        skews = []
        if len(source_averages) > 1:
            sources = list(source_averages.keys())
            for i in range(len(sources)):
                for j in range(i + 1, len(sources)):
                    source1, source2 = sources[i], sources[j]
                    time_diff = abs((source_averages[source1] - source_averages[source2]).total_seconds())
                    
                    if time_diff > (self._clock_skew_tolerance_ms / 1000):
                        skews.append({
                            "source1": source1.value,
                            "source2": source2.value,
                            "time_diff_seconds": time_diff,
                            "tolerance_seconds": self._clock_skew_tolerance_ms / 1000,
                            "source1_avg": source_averages[source1].isoformat(),
                            "source2_avg": source_averages[source2].isoformat(),
                        })
        
        is_consistent = len(skews) == 0
        
        log_structured(
            "info",
            "clock_skew_detected",
            sources_analyzed=len(source_averages),
            skews_found=len(skews),
            is_consistent=is_consistent,
        )
        
        return {
            "consistent": is_consistent,
            "skews": skews,
            "sources_analyzed": len(source_averages),
            "source_averages": {
                source.value: avg.isoformat() 
                for source, avg in source_averages.items()
            },
            "tolerance_seconds": self._clock_skew_tolerance_ms / 1000,
            "detection_timestamp": datetime.now(timezone.utc).isoformat(),
        }
