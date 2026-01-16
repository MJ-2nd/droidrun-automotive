"""Pydantic models for WebSocket request/response."""

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ConnectionRequest(BaseModel):
    """Client request sent when WebSocket connection is established."""

    ip_port: str = Field(..., description="ADB connection address (e.g., 192.168.1.100:5555)")
    is_automotive: bool = Field(default=False, description="Whether to use AAOS mode")
    query: str = Field(..., description="Command to execute via DroidAgent")


class EventType(str, Enum):
    """Event types for WebSocket messages."""

    # Connection lifecycle events
    CONNECTION_STATUS = "connection_status"
    ADB_CONNECTED = "adb_connected"
    ADB_ERROR = "adb_error"

    # Agent lifecycle events
    AGENT_STARTED = "agent_started"
    AGENT_STEP = "agent_step"
    AGENT_COMPLETED = "agent_completed"
    AGENT_ERROR = "agent_error"

    # DroidRun events - Manager
    MANAGER_CONTEXT = "manager_context"
    MANAGER_RESPONSE = "manager_response"
    MANAGER_PLAN = "manager_plan"

    # DroidRun events - Executor
    EXECUTOR_CONTEXT = "executor_context"
    EXECUTOR_RESPONSE = "executor_response"
    EXECUTOR_ACTION = "executor_action"
    EXECUTOR_ACTION_RESULT = "executor_action_result"

    # DroidRun events - CodeAct
    CODEACT_RESPONSE = "codeact_response"
    CODEACT_OUTPUT = "codeact_output"
    CODEACT_END = "codeact_end"

    # DroidRun events - Scripter
    SCRIPTER_THINKING = "scripter_thinking"
    SCRIPTER_EXECUTION = "scripter_execution"
    SCRIPTER_RESULT = "scripter_result"
    SCRIPTER_END = "scripter_end"

    # DroidRun events - Common
    SCREENSHOT = "screenshot"
    UI_STATE = "ui_state"
    FINALIZE = "finalize"
    RESULT = "result"

    # Macro events
    TAP_ACTION = "tap_action"
    SWIPE_ACTION = "swipe_action"
    INPUT_TEXT = "input_text"
    KEY_PRESS = "key_press"
    START_APP = "start_app"


class WebSocketMessage(BaseModel):
    """Base format for all WebSocket messages."""

    event_type: EventType
    timestamp: float
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
