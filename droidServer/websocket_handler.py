"""WebSocket connection handler for DroidServer."""

import asyncio
import logging
import time
from typing import Dict

from fastapi import WebSocket, WebSocketDisconnect

from .droid_session import DroidSession
from .models import ConnectionRequest, EventType, WebSocketMessage

logger = logging.getLogger("droidServer")


class ConnectionManager:
    """Manages active WebSocket connections and DroidAgent sessions."""

    def __init__(self, max_connections: int = 10):
        """Initialize the connection manager.

        Args:
            max_connections: Maximum number of concurrent connections
        """
        self.active_connections: Dict[str, WebSocket] = {}
        self.active_sessions: Dict[str, DroidSession] = {}
        self.session_tasks: Dict[str, asyncio.Task] = {}
        self.max_connections = max_connections
        self._semaphore = asyncio.Semaphore(max_connections)

    async def connect(self, websocket: WebSocket, client_id: str) -> bool:
        """Accept a new WebSocket connection.

        Args:
            websocket: The WebSocket connection
            client_id: Unique identifier for the client

        Returns:
            True if connection was accepted, False if limit reached
        """
        if len(self.active_connections) >= self.max_connections:
            logger.warning(f"Connection limit reached, rejecting client {client_id}")
            return False

        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"Client {client_id} connected. Active connections: {len(self.active_connections)}")
        return True

    def disconnect(self, client_id: str):
        """Handle client disconnection and cleanup.

        Args:
            client_id: The disconnecting client's ID
        """
        # Cancel running session task
        if client_id in self.session_tasks:
            task = self.session_tasks[client_id]
            if not task.done():
                task.cancel()
            del self.session_tasks[client_id]

        # Cancel session
        if client_id in self.active_sessions:
            session = self.active_sessions[client_id]
            asyncio.create_task(session.cancel())
            del self.active_sessions[client_id]

        # Remove connection
        if client_id in self.active_connections:
            del self.active_connections[client_id]

        logger.info(f"Client {client_id} disconnected. Active connections: {len(self.active_connections)}")

    async def send_message(self, client_id: str, message: WebSocketMessage):
        """Send a message to a specific client.

        Args:
            client_id: Target client ID
            message: Message to send
        """
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]
            try:
                await websocket.send_json(message.model_dump())
            except Exception as e:
                logger.warning(f"Failed to send message to {client_id}: {e}")

    async def broadcast(self, message: WebSocketMessage):
        """Broadcast a message to all connected clients.

        Args:
            message: Message to broadcast
        """
        for client_id in list(self.active_connections.keys()):
            await self.send_message(client_id, message)

    def get_client_count(self) -> int:
        """Get the number of active connections.

        Returns:
            Number of active connections
        """
        return len(self.active_connections)


# Global connection manager instance
manager = ConnectionManager()


async def handle_websocket(websocket: WebSocket, client_id: str, config_path: str | None = None):
    """Handle a WebSocket connection from connection to disconnection.

    Protocol:
    1. Client connects to WebSocket
    2. Client sends ConnectionRequest JSON
    3. Server runs DroidAgent and streams events
    4. Server sends final result
    5. Connection closes

    Args:
        websocket: The WebSocket connection
        client_id: Unique identifier for this client
        config_path: Optional path to config file
    """
    # Accept connection
    if not await manager.connect(websocket, client_id):
        await websocket.close(code=1008, reason="Connection limit reached")
        return

    try:
        # Send welcome message
        await manager.send_message(
            client_id,
            WebSocketMessage(
                event_type=EventType.CONNECTION_STATUS,
                timestamp=time.time(),
                data={"status": "connected", "client_id": client_id},
            ),
        )

        # Wait for ConnectionRequest from client
        try:
            data = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)
        except asyncio.TimeoutError:
            await manager.send_message(
                client_id,
                WebSocketMessage(
                    event_type=EventType.AGENT_ERROR,
                    timestamp=time.time(),
                    error="Timeout waiting for connection request",
                ),
            )
            return

        # Validate request
        try:
            request = ConnectionRequest(**data)
        except Exception as e:
            await manager.send_message(
                client_id,
                WebSocketMessage(
                    event_type=EventType.AGENT_ERROR,
                    timestamp=time.time(),
                    error=f"Invalid request: {str(e)}",
                ),
            )
            return

        logger.info(
            f"Client {client_id} request: ip_port={request.ip_port}, "
            f"is_automotive={request.is_automotive}, query={request.query[:50]}..."
        )

        # Create send callback
        async def send_callback(msg: WebSocketMessage):
            await manager.send_message(client_id, msg)

        # Create and run DroidSession
        session = DroidSession(request, send_callback, config_path)
        manager.active_sessions[client_id] = session

        # Run session in a task so we can cancel it
        session_task = asyncio.create_task(session.run())
        manager.session_tasks[client_id] = session_task

        # Wait for session to complete or client to disconnect
        try:
            await session_task
        except asyncio.CancelledError:
            logger.info(f"Session for {client_id} was cancelled")

    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected during session")

    except Exception as e:
        logger.exception(f"Error handling WebSocket for {client_id}")
        try:
            await manager.send_message(
                client_id,
                WebSocketMessage(
                    event_type=EventType.AGENT_ERROR,
                    timestamp=time.time(),
                    error=str(e),
                ),
            )
        except Exception:
            pass

    finally:
        manager.disconnect(client_id)
