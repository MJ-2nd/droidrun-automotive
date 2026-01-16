"""Event serializer for converting DroidRun events to WebSocket messages."""

import base64
import logging
import time
from typing import Any, Dict

from llama_index.core.workflow import Event

from .models import EventType, WebSocketMessage

logger = logging.getLogger("droidServer")


class EventSerializer:
    """Converts DroidRun events to WebSocket-compatible messages."""

    # Event class name to EventType mapping
    EVENT_TYPE_MAPPING = {
        # Common events
        "ScreenshotEvent": EventType.SCREENSHOT,
        "RecordUIStateEvent": EventType.UI_STATE,
        # Manager events
        "ManagerContextEvent": EventType.MANAGER_CONTEXT,
        "ManagerResponseEvent": EventType.MANAGER_RESPONSE,
        "ManagerPlanDetailsEvent": EventType.MANAGER_PLAN,
        # Executor events
        "ExecutorContextEvent": EventType.EXECUTOR_CONTEXT,
        "ExecutorResponseEvent": EventType.EXECUTOR_RESPONSE,
        "ExecutorActionEvent": EventType.EXECUTOR_ACTION,
        "ExecutorActionResultEvent": EventType.EXECUTOR_ACTION_RESULT,
        # CodeAct events
        "CodeActInputEvent": EventType.CODEACT_RESPONSE,
        "CodeActResponseEvent": EventType.CODEACT_RESPONSE,
        "CodeActCodeEvent": EventType.CODEACT_RESPONSE,
        "CodeActOutputEvent": EventType.CODEACT_OUTPUT,
        "CodeActEndEvent": EventType.CODEACT_END,
        # Scripter events
        "ScripterThinkingEvent": EventType.SCRIPTER_THINKING,
        "ScripterExecutionEvent": EventType.SCRIPTER_EXECUTION,
        "ScripterExecutionResultEvent": EventType.SCRIPTER_RESULT,
        "ScripterEndEvent": EventType.SCRIPTER_END,
        # Droid coordination events
        "FinalizeEvent": EventType.FINALIZE,
        "ResultEvent": EventType.RESULT,
        # Macro events
        "TapActionEvent": EventType.TAP_ACTION,
        "SwipeActionEvent": EventType.SWIPE_ACTION,
        "DragActionEvent": EventType.SWIPE_ACTION,
        "InputTextActionEvent": EventType.INPUT_TEXT,
        "KeyPressActionEvent": EventType.KEY_PRESS,
        "StartAppEvent": EventType.START_APP,
        "WaitEvent": EventType.AGENT_STEP,
    }

    @classmethod
    def serialize(cls, event: Event) -> WebSocketMessage:
        """Convert a DroidRun event to a WebSocketMessage.

        Args:
            event: The DroidRun event to serialize

        Returns:
            WebSocketMessage ready for JSON serialization
        """
        event_class_name = event.__class__.__name__
        event_type = cls.EVENT_TYPE_MAPPING.get(event_class_name, EventType.AGENT_STEP)
        data = cls._extract_data(event)

        return WebSocketMessage(
            event_type=event_type,
            timestamp=time.time(),
            data=data,
        )

    @classmethod
    def _extract_data(cls, event: Event) -> Dict[str, Any]:
        """Extract serializable data from an event.

        Args:
            event: The event to extract data from

        Returns:
            Dictionary of serializable data
        """
        event_class_name = event.__class__.__name__

        # Handle special cases first
        if event_class_name == "ScreenshotEvent":
            return {"screenshot_base64": base64.b64encode(event.screenshot).decode("utf-8")}

        if event_class_name == "RecordUIStateEvent":
            return {"ui_state": event.ui_state}

        # Manager events
        if event_class_name == "ManagerContextEvent":
            return {}

        if event_class_name == "ManagerResponseEvent":
            return {
                "response": event.response,
                "usage": cls._serialize_usage(event.usage) if event.usage else None,
            }

        if event_class_name == "ManagerPlanDetailsEvent":
            return {
                "subgoal": event.subgoal,
                "thought": event.thought,
                "answer": event.answer,
                "success": event.success,
            }

        # Executor events
        if event_class_name == "ExecutorContextEvent":
            return {"subgoal": event.subgoal}

        if event_class_name == "ExecutorResponseEvent":
            return {
                "response": event.response,
                "usage": cls._serialize_usage(event.usage) if event.usage else None,
            }

        if event_class_name == "ExecutorActionEvent":
            return {
                "description": event.description,
                "thought": event.thought,
            }

        if event_class_name == "ExecutorActionResultEvent":
            return {
                "success": event.success,
                "summary": event.summary,
                "error": event.error,
            }

        # CodeAct events
        if event_class_name == "CodeActInputEvent":
            return {}

        if event_class_name == "CodeActResponseEvent":
            return {
                "thought": event.thought,
                "code": event.code,
            }

        if event_class_name == "CodeActCodeEvent":
            return {"code": event.code}

        if event_class_name == "CodeActOutputEvent":
            return {"output": event.output}

        if event_class_name == "CodeActEndEvent":
            return {
                "success": event.success,
                "reason": event.reason,
                "code_executions": event.code_executions,
            }

        # Finalization events
        if event_class_name == "FinalizeEvent":
            return {
                "success": event.success,
                "reason": event.reason,
            }

        if event_class_name == "ResultEvent":
            return {
                "success": event.success,
                "reason": event.reason,
                "steps": event.steps,
                "structured_output": (
                    event.structured_output.model_dump() if event.structured_output else None
                ),
            }

        # Macro events - simplified (only action type and description)
        if event_class_name in (
            "TapActionEvent",
            "SwipeActionEvent",
            "DragActionEvent",
            "InputTextActionEvent",
            "KeyPressActionEvent",
            "StartAppEvent",
            "WaitEvent",
        ):
            return {
                "action_type": getattr(event, "action_type", event_class_name),
                "description": getattr(event, "description", ""),
            }

        # Fallback: try to extract common attributes
        return cls._extract_generic(event)

    @classmethod
    def _extract_generic(cls, event: Event) -> Dict[str, Any]:
        """Extract data from unknown event types using generic approach.

        Args:
            event: The event to extract from

        Returns:
            Dictionary of serializable attributes
        """
        result = {}

        # Try Pydantic model_dump first
        if hasattr(event, "model_dump"):
            try:
                data = event.model_dump()
                # Filter out private fields and non-serializable types
                for key, value in data.items():
                    if not key.startswith("_") and cls._is_serializable(value):
                        result[key] = value
                return result
            except Exception:
                pass

        # Fallback to __dict__
        for key, value in vars(event).items():
            if not key.startswith("_") and cls._is_serializable(value):
                result[key] = value

        return result

    @classmethod
    def _is_serializable(cls, value: Any) -> bool:
        """Check if a value is JSON-serializable.

        Args:
            value: The value to check

        Returns:
            True if serializable, False otherwise
        """
        if value is None:
            return True
        if isinstance(value, (str, int, float, bool)):
            return True
        if isinstance(value, (list, tuple)):
            return all(cls._is_serializable(item) for item in value)
        if isinstance(value, dict):
            return all(
                isinstance(k, str) and cls._is_serializable(v) for k, v in value.items()
            )
        return False

    @classmethod
    def _serialize_usage(cls, usage) -> Dict[str, Any]:
        """Serialize UsageResult to dict.

        Args:
            usage: UsageResult object

        Returns:
            Dictionary representation
        """
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        return {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        }
