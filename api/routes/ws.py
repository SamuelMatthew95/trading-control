"""Dashboard WebSocket fanout with single Redis connection."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.observability import log_structured

router = APIRouter(tags=["ws"])


@router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket) -> None:
    await websocket.accept()

    # Get the global broadcaster
    broadcaster = getattr(websocket.app.state, "websocket_broadcaster", None)
    if broadcaster is None:
        await websocket.close(code=1013)
        return

    # Add this connection to the broadcaster
    await broadcaster.add_connection(websocket)

    try:
        # Keep the WebSocket alive and handle client messages
        while True:
            try:
                # Wait for client message or heartbeat
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break
            except WebSocketDisconnect:
                break
            except Exception as exc:
                log_structured("warning", "WebSocket receive error", exc_info=True)
                break

    except WebSocketDisconnect:
        log_structured("info", "WebSocket client disconnected")
    except Exception as exc:
        log_structured("error", "WebSocket handler error", exc_info=True)
    finally:
        # Always remove the connection from broadcaster
        await broadcaster.remove_connection(websocket)
        log_structured("info", "WebSocket cleanup completed")
