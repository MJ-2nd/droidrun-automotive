"""DroidAgent session management for WebSocket connections."""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Awaitable, Callable

from droidrun import DroidAgent
from droidrun.agent.codeact.events import (
    CodeActCodeEvent,
    CodeActInputEvent,
)
from droidrun.agent.common.events import RecordUIStateEvent, ScreenshotEvent
from droidrun.agent.executor.events import (
    ExecutorContextEvent,
    ExecutorResponseEvent,
)
from droidrun.agent.manager.events import (
    ManagerContextEvent,
    ManagerResponseEvent,
)
from droidrun.config_manager import DroidrunConfig

from .adb_service import AdbService
from .event_serializer import EventSerializer
from .models import ConnectionRequest, EventType, WebSocketMessage

logger = logging.getLogger("droidServer")

# Default config file path (relative to project root)
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"  # project root config


class DroidSession:
    """Manages a single DroidAgent session for a WebSocket client."""

    def __init__(
        self,
        request: ConnectionRequest,
        send_callback: Callable[[WebSocketMessage], Awaitable[None]],
        config_path: str | None = None,
    ):
        """Initialize a DroidAgent session.

        Args:
            request: The connection request with ip_port, is_automotive, query
            send_callback: Async callback to send messages to WebSocket client
            config_path: Path to config YAML file (default: config_example.yaml)
        """
        self.request = request
        self.send_callback = send_callback
        self.config_path = config_path or str(DEFAULT_CONFIG_PATH)
        self.adb_service = AdbService()
        self._cancelled = False
        self._agent = None

    async def run(self):
        """Execute the DroidAgent session.

        Flow:
        1. Connect to device via ADB
        2. Load and configure DroidrunConfig
        3. Create and run DroidAgent
        4. Stream events to WebSocket client
        5. Send final result
        """
        try:
            # Step 1: Connect to device via ADB
            await self._send_event(
                EventType.CONNECTION_STATUS,
                {"status": "connecting", "ip_port": self.request.ip_port},
            )

            success, message = await self.adb_service.connect(self.request.ip_port)
            if not success:
                await self._send_event(EventType.ADB_ERROR, {"error": message})
                return

            await self._send_event(EventType.ADB_CONNECTED, {"message": message})

            # Verify device is accessible
            if not await self.adb_service.verify_device(self.request.ip_port):
                await self._send_event(
                    EventType.ADB_ERROR,
                    {"error": f"Device {self.request.ip_port} not accessible after connect"},
                )
                return

            # Step 2: Ensure Portal is installed (skip for automotive mode)
            if not self.request.is_automotive:
                await self._send_event(
                    EventType.CONNECTION_STATUS,
                    {"status": "checking_portal", "message": "Checking Portal installation..."},
                )

                portal_ok, portal_msg = await self.adb_service.ensure_portal_installed(
                    self.request.ip_port
                )
                if not portal_ok:
                    await self._send_event(
                        EventType.AGENT_ERROR,
                        {"error": f"Portal setup failed: {portal_msg}"},
                    )
                    return

                await self._send_event(
                    EventType.CONNECTION_STATUS,
                    {"status": "portal_ready", "message": portal_msg},
                )

            # Step 3: Load and configure DroidrunConfig
            if not os.path.exists(self.config_path):
                await self._send_event(
                    EventType.AGENT_ERROR,
                    {"error": f"Config file not found: {self.config_path}"},
                )
                return

            config = DroidrunConfig.from_yaml(self.config_path)

            # Override device settings from request
            config.device.serial = self.request.ip_port
            config.device.automotive_mode = self.request.is_automotive

            logger.info(
                f"Starting DroidAgent with serial={config.device.serial}, "
                f"automotive_mode={config.device.automotive_mode}"
            )

            # Step 4: Create and run DroidAgent
            await self._send_event(
                EventType.AGENT_STARTED,
                {
                    "goal": self.request.query,
                    "serial": self.request.ip_port,
                    "automotive_mode": self.request.is_automotive,
                    "reasoning": config.agent.reasoning,
                },
            )

            logger.info("Creating DroidAgent instance...")
            self._agent = DroidAgent(
                goal=self.request.query,
                config=config,
                timeout=1200,  # 10 minutes timeout
            )
            logger.info("DroidAgent created, starting run...")

            handler = self._agent.run()
            logger.info("DroidAgent.run() handler created, starting event stream...")

            # Step 5: Stream events to WebSocket client
            event_count = 0
            async for event in handler.stream_events():
                event_count += 1
                logger.debug(f"Received event #{event_count}: {event.__class__.__name__}")
                if self._cancelled:
                    logger.info("Session cancelled, stopping event stream")
                    break

                # Skip verbose/unnecessary events (terminal-like filtering)
                # These events are either too large, redundant, or not user-facing
                if isinstance(event, (
                    RecordUIStateEvent,      # UI state tree (too large)
                    ScreenshotEvent,         # Base64 screenshot (too large)
                    ManagerContextEvent,     # Empty context prep event
                    ManagerResponseEvent,    # Full LLM response (redundant with plan details)
                    ExecutorContextEvent,    # Just subgoal (redundant)
                    ExecutorResponseEvent,   # Full LLM response (redundant with action)
                    CodeActInputEvent,       # Empty input event
                    CodeActCodeEvent,        # Code event (redundant with response)
                )):
                    continue

                try:
                    ws_message = EventSerializer.serialize(event)
                    await self.send_callback(ws_message)
                except Exception as e:
                    logger.warning(f"Failed to serialize event {event.__class__.__name__}: {e}")

            # Step 6: Get final result
            if not self._cancelled:
                result = await handler

                await self._send_event(
                    EventType.AGENT_COMPLETED,
                    {
                        "success": result.success,
                        "reason": result.reason,
                        "steps": result.steps,
                        "structured_output": (
                            result.structured_output.model_dump()
                            if result.structured_output
                            else None
                        ),
                    },
                )

        except asyncio.CancelledError:
            logger.info("Session task cancelled")
            await self._send_event(EventType.AGENT_ERROR, {"error": "Session cancelled by client"})
            raise

        except Exception as e:
            logger.exception("DroidSession error")
            await self._send_event(EventType.AGENT_ERROR, {"error": str(e)})

    async def cancel(self):
        """Cancel the running session."""
        self._cancelled = True
        logger.info("Session cancellation requested")

    async def _send_event(self, event_type: EventType, data: dict):
        """Helper to create and send a WebSocketMessage.

        Args:
            event_type: The type of event
            data: Event data dictionary
        """
        message = WebSocketMessage(
            event_type=event_type,
            timestamp=time.time(),
            data=data,
        )
        try:
            await self.send_callback(message)
        except Exception as e:
            logger.warning(f"Failed to send event {event_type}: {e}")
