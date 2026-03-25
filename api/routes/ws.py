"""Dashboard WebSocket fanout with single Redis connection."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.observability import log_structured

router = APIRouter(tags=["ws"])


@router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    log_structured("info", "ws_client_connected", client=str(websocket.client))

    # Get the global broadcaster
    broadcaster = getattr(websocket.app.state, "websocket_broadcaster", None)
    if broadcaster is None:
        log_structured("error", "ws_broadcaster_not_found")
        await websocket.close(code=1013)
        return

    # Add this connection to the broadcaster
    await broadcaster.add_connection(websocket)
    log_structured("info", "ws_client_added_to_broadcaster", client=str(websocket.client))

    try:
        # Keep the WebSocket alive and handle client messages
        while True:
            try:
                # Wait for client message or heartbeat
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                log_structured("info", "ws_event_received", payload=data[:100])  # Log first 100 chars
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break
            except WebSocketDisconnect:
                break
            except Exception as exc:
                log_structured("warning", "ws_receive_error", exc_info=True)
                break

    except WebSocketDisconnect:
        log_structured("info", "ws_client_disconnected", client=str(websocket.client))
    except Exception as exc:
        log_structured("error", "ws_handler_error", exc_info=True)
    finally:
        # Always remove the connection from broadcaster
        await broadcaster.remove_connection(websocket)
        log_structured("info", "ws_cleanup_completed", client=str(websocket.client))
