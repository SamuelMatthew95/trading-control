"""Redis debug and observability endpoints for troubleshooting event flow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.events.bus import EventBus, STREAMS, _deserialize, _decode_bytes, _serialize
from api.redis_client import get_redis
from api.observability import log_structured
from api.services.websocket_broadcaster import get_broadcaster

router = APIRouter(prefix="/debug", tags=["debug"])


async def get_event_bus() -> EventBus:
    """Dependency to get EventBus with Redis connection."""
    try:
        redis = await get_redis()
        return EventBus(redis)
    except Exception as exc:
        log_structured("warning", "debug_redis_unavailable", error=str(exc))
        raise HTTPException(status_code=503, detail="Redis unavailable for debug endpoints")


@router.get("/streams")
async def list_streams(bus: EventBus = Depends(get_event_bus)) -> dict[str, Any]:
    """List all streams with stats: length, groups, pending count."""
    log_structured("info", "debug_list_streams_called")
    
    result = {}
    for stream in STREAMS:
        try:
            length = await bus.redis.xlen(stream)
            
            try:
                groups = await bus.redis.xinfo_groups(stream)
            except Exception:
                groups = []
            
            # Calculate pending from groups (Redis 6-7 compatible)
            pending = 0
            for g in groups:
                p = g.get("pending") or g.get(b"pending") or 0
                pending += int(p)
            
            result[stream] = {
                "length": int(length),
                "groups": len(groups),
                "pending": pending,
            }
        except Exception as e:
            result[stream] = {"error": str(e)}
    
    return {"streams": result}


@router.get("/streams/{stream}")
async def peek_stream(
    stream: str,
    count: int = 20,
    bus: EventBus = Depends(get_event_bus)
) -> dict[str, Any]:
    """Peek messages from stream using XRANGE."""
    log_structured("info", "debug_peek_stream_called", stream=stream, count=count)
    
    try:
        # XRANGE stream - + COUNT N
        messages = await bus.redis.xrange(stream, min="-", max="+", count=count)
        
        decoded = []
        for msg_id, fields in messages:
            # Decode message ID
            msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
            
            # Decode and deserialize fields
            decoded_fields = {}
            for k, v in fields.items():
                key = _decode_bytes(k)
                value_str = _decode_bytes(v)
                decoded_fields[key] = _deserialize(value_str)
            
            decoded.append({
                "message_id": msg_id_str,
                "fields": decoded_fields,
            })
        
        return {
            "stream": stream,
            "count": len(decoded),
            "messages": decoded,
        }
    except Exception as e:
        log_structured("error", "debug_peek_stream_failed", stream=stream, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to peek stream: {e}")


class PublishRequest(BaseModel):
    """Request body for publishing test event."""
    type: str = "debug_event"
    data: dict[str, Any] = {}


@router.post("/publish/{stream}")
async def publish_test_event(
    stream: str,
    request: PublishRequest,
    bus: EventBus = Depends(get_event_bus)
) -> dict[str, Any]:
    """Publish a test event to a stream."""
    log_structured("info", "debug_publish_called", stream=stream, type=request.type)
    
    try:
        # Build event
        from datetime import datetime, timezone
        event = {
            "msg_id": f"debug-{datetime.now(timezone.utc).isoformat()}",
            "type": request.type,
            "data": request.data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "schema_version": "v3",
            "source": "debug",
        }
        
        # Publish via EventBus
        message_id = await bus.publish(stream, event)
        
        if message_id:
            log_structured("info", "debug_publish_success", stream=stream, message_id=message_id)
            return {
                "success": True,
                "stream": stream,
                "message_id": message_id,
                "event": event,
            }
        else:
            log_structured("error", "debug_publish_failed", stream=stream)
            raise HTTPException(status_code=500, detail="Publish returned None")
    
    except Exception as e:
        log_structured("error", "debug_publish_exception", stream=stream, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to publish: {e}")


@router.get("/consume/{stream}")
async def consume_from_stream(
    stream: str,
    group: str = "workers",
    consumer: str = "debugger",
    count: int = 10,
    bus: EventBus = Depends(get_event_bus)
) -> dict[str, Any]:
    """Consume messages from stream via consumer group (XREADGROUP)."""
    log_structured("info", "debug_consume_called", stream=stream, group=group, consumer=consumer)
    
    try:
        # Ensure group exists
        try:
            await bus.create_consumer_group(stream, group)
        except Exception:
            pass  # Group might already exist
        
        # Consume messages
        messages = await bus.consume(stream, group, consumer, count=count, block_ms=1000)
        
        # Acknowledge all messages (so they're not stuck pending)
        if messages:
            msg_ids = [msg_id for msg_id, _ in messages]
            await bus.acknowledge(stream, group, *msg_ids)
        
        log_structured("info", "debug_consume_success", stream=stream, count=len(messages))
        
        return {
            "stream": stream,
            "group": group,
            "consumer": consumer,
            "count": len(messages),
            "messages": [
                {"message_id": msg_id, "data": data}
                for msg_id, data in messages
            ],
        }
    
    except Exception as e:
        log_structured("error", "debug_consume_failed", stream=stream, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to consume: {e}")


@router.get("/health")
async def stream_health(bus: EventBus = Depends(get_event_bus)) -> dict[str, Any]:
    """Overall stream health check."""
    log_structured("info", "debug_health_check_called")
    
    try:
        total_messages = 0
        total_pending = 0
        stream_stats = {}
        
        for stream in STREAMS:
            try:
                length = await bus.redis.xlen(stream)
                total_messages += int(length)
                
                try:
                    groups = await bus.redis.xinfo_groups(stream)
                except Exception:
                    groups = []
                
                pending = 0
                for g in groups:
                    p = g.get("pending") or g.get(b"pending") or 0
                    pending += int(p)
                
                total_pending += pending
                
                stream_stats[stream] = {
                    "length": int(length),
                    "pending": pending,
                    "groups": len(groups),
                }
            except Exception as e:
                stream_stats[stream] = {"error": str(e)}
        
        return {
            "status": "healthy",
            "total_messages": total_messages,
            "total_pending": total_pending,
            "streams": stream_stats,
        }
    
    except Exception as e:
        log_structured("error", "debug_health_check_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Health check failed: {e}")


@router.get("/lag")
async def consumer_lag(bus: EventBus = Depends(get_event_bus)) -> dict[str, Any]:
    """Consumer lag per stream - detect stuck consumers instantly."""
    log_structured("info", "debug_lag_check_called")
    
    result = {}
    for stream in STREAMS:
        try:
            try:
                groups = await bus.redis.xinfo_groups(stream)
            except Exception:
                groups = []
            
            consumers_info = []
            total_pending = 0
            
            for g in groups:
                group_name = g.get("name") or g.get(b"name") or "unknown"
                pending = g.get("pending") or g.get(b"pending") or 0
                total_pending += int(pending)
                
                # Get consumer details
                try:
                    consumers = await bus.redis.xinfo_consumers(stream, group_name)
                    for c in consumers:
                        consumers_info.append({
                            "name": c.get("name") or c.get(b"name") or "unknown",
                            "pending": c.get("pending") or c.get(b"pending") or 0,
                            "idle_ms": c.get("idle") or c.get(b"idle") or 0,
                        })
                except Exception:
                    pass
            
            result[stream] = {
                "pending": total_pending,
                "groups": len(groups),
                "consumers": consumers_info,
            }
        except Exception as e:
            result[stream] = {"error": str(e)}
    
    return {"lag": result}


@router.get("/pending/{stream}")
async def pending_messages(
    stream: str,
    group: str = "workers",
    count: int = 10,
    bus: EventBus = Depends(get_event_bus)
) -> dict[str, Any]:
    """Inspect pending messages - catch stuck/unacked messages."""
    log_structured("info", "debug_pending_called", stream=stream, group=group)
    
    try:
        # XPENDING to get summary and range
        pending_summary = await bus.redis.xpending(stream, group)
        
        # XPENDING RANGE to get details
        pending_range = await bus.redis.xpending_range(
            stream, group, min_id="-", max_id="+", count=count
        )
        
        messages = []
        for item in pending_range:
            messages.append({
                "id": item.get("message_id") or item.get(b"message_id"),
                "consumer": item.get("consumer") or item.get(b"consumer"),
                "idle_ms": item.get("time_since_delivered") or item.get(b"time_since_delivered"),
                "delivery_count": item.get("delivery_number") or item.get(b"delivery_number"),
            })
        
        return {
            "stream": stream,
            "group": group,
            "pending_count": pending_summary,  # This is the count
            "messages": messages,
        }
    except Exception as e:
        log_structured("error", "debug_pending_failed", stream=stream, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get pending: {e}")


@router.post("/reclaim/{stream}")
async def force_reclaim(
    stream: str,
    group: str = "workers",
    consumer: str = "debugger",
    min_idle_ms: int = 1000,
    count: int = 10,
    bus: EventBus = Depends(get_event_bus)
) -> dict[str, Any]:
    """Force reclaim stuck messages via XAUTOCLAIM - debug superpower."""
    log_structured("info", "debug_reclaim_called", stream=stream, group=group, consumer=consumer)
    
    try:
        # XAUTOCLAIM to reclaim messages
        reclaimed = await bus.reclaim_stale(stream, group, consumer, min_idle_ms)
        
        # Take only first N
        reclaimed = reclaimed[:count]
        
        return {
            "stream": stream,
            "group": group,
            "consumer": consumer,
            "min_idle_ms": min_idle_ms,
            "reclaimed_count": len(reclaimed),
            "messages": [
                {"message_id": msg_id, "data": data}
                for msg_id, data in reclaimed
            ],
        }
    except Exception as e:
        log_structured("error", "debug_reclaim_failed", stream=stream, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to reclaim: {e}")


@router.get("/tail/{stream}")
async def tail_stream(
    stream: str,
    count: int = 50,
    bus: EventBus = Depends(get_event_bus)
) -> dict[str, Any]:
    """Get last N messages from stream - live tail for UI panel."""
    log_structured("info", "debug_tail_called", stream=stream, count=count)
    
    try:
        # XRANGE with count to get tail
        messages = await bus.redis.xrange(stream, min="-", max="+", count=count)
        
        decoded = []
        for msg_id, fields in messages:
            msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
            
            decoded_fields = {}
            for k, v in fields.items():
                key = _decode_bytes(k)
                value_str = _decode_bytes(v)
                decoded_fields[key] = _deserialize(value_str)
            
            decoded.append({
                "message_id": msg_id_str,
                "fields": decoded_fields,
            })
        
        return {
            "stream": stream,
            "count": len(decoded),
            "messages": decoded,
        }
    except Exception as e:
        log_structured("error", "debug_tail_failed", stream=stream, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to tail: {e}")


@router.get("/ws")
async def websocket_debug() -> dict[str, Any]:
    """WebSocket debug status - connections, last broadcast, events sent."""
    log_structured("info", "debug_ws_called")
    
    try:
        broadcaster = get_broadcaster()
        
        return {
            "connections": len(broadcaster._connections),
            "running": broadcaster._running,
            "has_task": broadcaster._broadcast_task is not None,
        }
    except Exception as e:
        log_structured("error", "debug_ws_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get WS status: {e}")


@router.get("/pipeline")
async def pipeline_health(bus: EventBus = Depends(get_event_bus)) -> dict[str, Any]:
    """End-to-end pipeline health - single truth endpoint."""
    log_structured("info", "debug_pipeline_called")
    
    try:
        # Check Redis
        redis_ok = False
        try:
            await bus.redis.ping()
            redis_ok = True
        except Exception:
            pass
        
        # Check WebSocket broadcaster
        ws_ok = False
        ws_connections = 0
        try:
            broadcaster = get_broadcaster()
            ws_ok = broadcaster._running
            ws_connections = len(broadcaster._connections)
        except Exception:
            pass
        
        # Get stream health summary
        stream_count = 0
        pending_total = 0
        for stream in STREAMS:
            try:
                length = await bus.redis.xlen(stream)
                stream_count += int(length)
                
                try:
                    groups = await bus.redis.xinfo_groups(stream)
                    for g in groups:
                        p = g.get("pending") or g.get(b"pending") or 0
                        pending_total += int(p)
                except Exception:
                    pass
            except Exception:
                pass
        
        return {
            "status": "healthy" if (redis_ok and ws_ok) else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {
                "redis": "ok" if redis_ok else "error",
                "websocket": "running" if ws_ok else "stopped",
                "websocket_connections": ws_connections,
            },
            "streams": {
                "total_messages": stream_count,
                "total_pending": pending_total,
            },
        }
    except Exception as e:
        log_structured("error", "debug_pipeline_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Pipeline check failed: {e}")
