"""DroidServer - WebSocket orchestrator for DroidRun.

Usage:
    uvicorn droidServer.main:app --host 0.0.0.0 --port 8000

    # Or with auto-reload for development:
    uvicorn droidServer.main:app --host 0.0.0.0 --port 8000 --reload

    # Or run directly:
    python -m droidServer.main
"""

import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .websocket_handler import handle_websocket, manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("droidServer")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("DroidServer starting up...")
    yield
    logger.info("DroidServer shutting down...")


# Create FastAPI application
app = FastAPI(
    title="DroidServer",
    description="WebSocket orchestrator for DroidRun - Control Android devices with natural language",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "DroidServer",
        "version": "0.1.0",
        "description": "WebSocket orchestrator for DroidRun",
        "endpoints": {
            "websocket": "/ws",
            "websocket_with_id": "/ws/{client_id}",
            "health": "/health",
            "status": "/status",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/status")
async def server_status():
    """Get server status including active connections."""
    return {
        "status": "running",
        "active_connections": manager.get_client_count(),
        "max_connections": manager.max_connections,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint with auto-generated client ID.

    Protocol:
        1. Connect to this endpoint
        2. Send JSON: {"ip_port": "IP:PORT", "is_automotive": bool, "query": "command"}
        3. Receive streaming events as JSON messages
        4. Final message will have event_type "agent_completed" or "agent_error"

    Example request:
        {
            "ip_port": "192.168.1.100:5555",
            "is_automotive": true,
            "query": "Open Settings app and find Battery menu"
        }

    Example response events:
        {"event_type": "connection_status", "timestamp": 1234567890.123, "data": {...}}
        {"event_type": "adb_connected", "timestamp": 1234567890.456, "data": {...}}
        {"event_type": "agent_started", "timestamp": 1234567890.789, "data": {...}}
        {"event_type": "manager_plan", "timestamp": 1234567891.123, "data": {...}}
        {"event_type": "executor_action", "timestamp": 1234567892.456, "data": {...}}
        {"event_type": "screenshot", "timestamp": 1234567893.789, "data": {"screenshot_base64": "..."}}
        {"event_type": "agent_completed", "timestamp": 1234567899.123, "data": {...}}
    """
    client_id = str(uuid.uuid4())
    config_path = os.environ.get("DROIDSERVER_CONFIG_PATH")
    await handle_websocket(websocket, client_id, config_path)


@app.websocket("/ws/{client_id}")
async def websocket_endpoint_with_id(websocket: WebSocket, client_id: str):
    """WebSocket endpoint with custom client ID.

    Same protocol as /ws but allows specifying a custom client ID.
    """
    config_path = os.environ.get("DROIDSERVER_CONFIG_PATH")
    await handle_websocket(websocket, client_id, config_path)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


def main():
    """Run the server using uvicorn."""
    import uvicorn

    host = os.environ.get("DROIDSERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("DROIDSERVER_PORT", "8000"))
    reload = os.environ.get("DROIDSERVER_RELOAD", "false").lower() == "true"

    logger.info(f"Starting DroidServer on {host}:{port}")

    uvicorn.run(
        "droidServer.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
