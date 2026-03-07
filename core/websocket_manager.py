"""
WebSocket Manager - Simple WebSocket connection management
"""

import json
from datetime import datetime
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


class WebSocketManager:
    """Simple WebSocket connection manager"""

    def __init__(self) -> None:
        self.connections: Dict[str, Any] = {}

    async def connect(self, websocket: Any, client_id: str) -> None:
        """Connect a WebSocket client"""
        self.connections[client_id] = websocket
        logger.info(f"WebSocket client {client_id} connected")

    def disconnect(self, websocket: Any, client_id: str) -> None:
        """Disconnect a WebSocket client"""
        if client_id in self.connections:
            del self.connections[client_id]
            logger.info(f"WebSocket client {client_id} disconnected")

    async def send_personal_message(self, message: str, client_id: str) -> None:
        """Send a message to a specific client"""
        if client_id in self.connections:
            try:
                await self.connections[client_id].send_text(message)
            except Exception as e:
                logger.error(f"Error sending message to {client_id}: {e}")

    async def broadcast(self, message: str) -> None:
        """Broadcast a message to all connected clients"""
        disconnected_clients = []

        for client_id, connection in self.connections.items():
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to {client_id}: {e}")
                disconnected_clients.append(client_id)

        # Remove disconnected clients
        for client_id in disconnected_clients:
            self.disconnect(None, client_id)

    async def broadcast_json(self, data: Dict[str, Any]) -> None:
        """Broadcast JSON data to all clients"""
        message = json.dumps(data)
        await self.broadcast(message)

    def get_connection_count(self) -> int:
        """Get number of connected clients"""
        return len(self.connections)
