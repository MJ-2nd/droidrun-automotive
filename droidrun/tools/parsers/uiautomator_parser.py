"""
UIAutomator XML Parser - Converts uiautomator dump XML to Portal-compatible JSON format.

This parser transforms the XML output from `adb shell uiautomator dump` into the same
JSON structure that Portal's Accessibility Service returns, enabling seamless
integration with existing TreeFilter and IndexedFormatter.
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

logger = logging.getLogger("droidrun")


class UIAutomatorParser:
    """
    Parses uiautomator dump XML and converts to Portal-compatible JSON format.

    Input XML format:
    <hierarchy rotation="0">
        <node index="0" text="" resource-id="" class="android.widget.FrameLayout"
              package="com.android.launcher3" content-desc="" checkable="false"
              checked="false" clickable="false" enabled="true" focusable="false"
              focused="false" scrollable="false" long-clickable="false" password="false"
              selected="false" bounds="[0,0][1080,2400]">
            <node ...>...</node>
        </node>
    </hierarchy>

    Output JSON format (Portal-compatible):
    {
        "className": "android.widget.FrameLayout",
        "text": "",
        "resourceId": "",
        "contentDescription": "",
        "boundsInScreen": {"left": 0, "top": 0, "right": 1080, "bottom": 2400},
        "clickable": false,
        "focusable": false,
        "focused": false,
        "enabled": true,
        "children": [...]
    }
    """

    # Bounds parsing regex: "[left,top][right,bottom]"
    BOUNDS_PATTERN = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

    def parse(self, xml_content: str) -> Optional[Dict[str, Any]]:
        """
        Parse uiautomator XML dump to Portal-compatible JSON.

        Args:
            xml_content: Raw XML string from uiautomator dump

        Returns:
            Parsed tree in Portal JSON format, or None if parsing fails
        """
        try:
            # Clean XML content (remove any trailing garbage)
            xml_content = xml_content.strip()
            if not xml_content.startswith(
                "<?xml"
            ) and not xml_content.startswith("<hierarchy"):
                # Try to find the start of XML
                start_idx = xml_content.find("<hierarchy")
                if start_idx == -1:
                    logger.error("No <hierarchy> tag found in uiautomator output")
                    return None
                xml_content = xml_content[start_idx:]

            root = ET.fromstring(xml_content)

            # hierarchy tag contains the root node(s)
            if root.tag == "hierarchy":
                children = [self._parse_node(child) for child in root]
                children = [c for c in children if c is not None]

                if len(children) == 1:
                    return children[0]
                elif len(children) > 1:
                    # Wrap multiple roots in a virtual container
                    return {
                        "className": "VirtualRoot",
                        "text": "",
                        "resourceId": "",
                        "contentDescription": "",
                        "boundsInScreen": self._get_screen_bounds(children),
                        "clickable": False,
                        "focusable": False,
                        "focused": False,
                        "enabled": True,
                        "children": children,
                    }
                else:
                    return None
            else:
                return self._parse_node(root)

        except ET.ParseError as e:
            logger.error(f"Failed to parse uiautomator XML: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing uiautomator XML: {e}")
            return None

    def _parse_node(self, element: ET.Element) -> Optional[Dict[str, Any]]:
        """
        Parse a single XML node element.

        Args:
            element: XML Element from uiautomator dump

        Returns:
            Portal-compatible dict representation
        """
        if element.tag != "node":
            return None

        # Parse bounds: "[0,66][1080,2400]" -> {left, top, right, bottom}
        bounds_str = element.get("bounds", "[0,0][0,0]")
        bounds = self._parse_bounds(bounds_str)

        # Convert attributes to Portal format
        result = {
            "className": element.get("class", ""),
            "text": element.get("text", ""),
            "resourceId": element.get("resource-id", ""),
            "contentDescription": element.get("content-desc", ""),
            "hint": element.get("hint", ""),
            "boundsInScreen": bounds,
            "clickable": element.get("clickable", "false").lower() == "true",
            "focusable": element.get("focusable", "false").lower() == "true",
            "focused": element.get("focused", "false").lower() == "true",
            "enabled": element.get("enabled", "true").lower() == "true",
            "scrollable": element.get("scrollable", "false").lower() == "true",
            "checkable": element.get("checkable", "false").lower() == "true",
            "checked": element.get("checked", "false").lower() == "true",
            "selected": element.get("selected", "false").lower() == "true",
            "longClickable": element.get("long-clickable", "false").lower() == "true",
            "password": element.get("password", "false").lower() == "true",
            "package": element.get("package", ""),
            "children": [],
        }

        # Recursively parse children
        for child in element:
            parsed_child = self._parse_node(child)
            if parsed_child is not None:
                result["children"].append(parsed_child)

        return result

    def _parse_bounds(self, bounds_str: str) -> Dict[str, int]:
        """
        Parse bounds string "[left,top][right,bottom]" to dict.

        Args:
            bounds_str: Bounds string from uiautomator

        Returns:
            Dict with left, top, right, bottom keys
        """
        match = self.BOUNDS_PATTERN.match(bounds_str)
        if match:
            return {
                "left": int(match.group(1)),
                "top": int(match.group(2)),
                "right": int(match.group(3)),
                "bottom": int(match.group(4)),
            }
        return {"left": 0, "top": 0, "right": 0, "bottom": 0}

    def _get_screen_bounds(self, children: List[Dict[str, Any]]) -> Dict[str, int]:
        """Calculate overall bounds from children for virtual root."""
        if not children:
            return {"left": 0, "top": 0, "right": 1080, "bottom": 2400}

        left = min(c["boundsInScreen"]["left"] for c in children)
        top = min(c["boundsInScreen"]["top"] for c in children)
        right = max(c["boundsInScreen"]["right"] for c in children)
        bottom = max(c["boundsInScreen"]["bottom"] for c in children)

        return {"left": left, "top": top, "right": right, "bottom": bottom}


class AutomotiveStateProvider:
    """
    Provides device state for AAOS using ADB commands instead of Accessibility Service.

    This class replaces Portal's get_state() functionality with ADB-only alternatives.
    """

    def __init__(self, device):
        """
        Initialize with ADB device.

        Args:
            device: async_adbutils device instance
        """
        self.device = device
        self.parser = UIAutomatorParser()

    async def get_ui_tree(self) -> Optional[Dict[str, Any]]:
        """
        Get UI tree using uiautomator dump.

        Returns:
            Parsed UI tree in Portal-compatible format
        """
        try:
            # Use /dev/tty to output directly instead of writing to file
            output = await self.device.shell("uiautomator dump /dev/tty")

            # uiautomator dump outputs the XML followed by "UI hierchary dumped to: /dev/tty"
            # We need to strip the trailing message
            if "UI hierchary dumped" in output or "UI hierarchy dumped" in output:
                # Find where XML ends (before the dump message)
                end_markers = ["UI hierchary dumped", "UI hierarchy dumped"]
                for marker in end_markers:
                    idx = output.find(marker)
                    if idx != -1:
                        output = output[:idx].strip()
                        break

            return self.parser.parse(output)

        except Exception as e:
            logger.error(f"Failed to get UI tree via uiautomator: {e}")
            # Retry once with a small delay
            await asyncio.sleep(0.3)
            try:
                output = await self.device.shell("uiautomator dump /dev/tty")
                if "UI hierchary dumped" in output or "UI hierarchy dumped" in output:
                    end_markers = ["UI hierchary dumped", "UI hierarchy dumped"]
                    for marker in end_markers:
                        idx = output.find(marker)
                        if idx != -1:
                            output = output[:idx].strip()
                            break
                return self.parser.parse(output)
            except Exception as e2:
                logger.error(f"Retry failed: {e2}")
                return None

    async def get_phone_state(self) -> Dict[str, Any]:
        """
        Get phone state using ADB commands.

        Returns:
            Dict with currentApp, packageName, isEditable, focusedElement
        """
        try:
            # Get current window/activity info
            window_output = await self.device.shell(
                "dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'"
            )

            # Get IME state (keyboard visibility)
            ime_output = await self.device.shell(
                "dumpsys input_method | grep -E 'mInputShown|mShowRequested'"
            )

            # Parse current app/activity
            current_app = "Unknown"
            package_name = "Unknown"

            # Parse mCurrentFocus=Window{...  com.example.app/com.example.app.MainActivity ...}
            for line in window_output.split("\n"):
                if "mCurrentFocus" in line or "mFocusedApp" in line:
                    # Extract package/activity from the line
                    parts = line.split()
                    for part in parts:
                        if "/" in part and "." in part:
                            pkg_act = part.strip("{}").strip()
                            if "/" in pkg_act:
                                package_name, activity = pkg_act.split("/", 1)
                                current_app = (
                                    activity.split(".")[-1]
                                    if "." in activity
                                    else activity
                                )
                                break

            # Parse keyboard visibility
            is_editable = False
            for line in ime_output.split("\n"):
                if "mInputShown=true" in line or "mShowRequested=true" in line:
                    is_editable = True
                    break

            return {
                "currentApp": current_app,
                "packageName": package_name,
                "isEditable": is_editable,
                "focusedElement": None,  # Cannot determine without Accessibility Service
            }

        except Exception as e:
            logger.error(f"Failed to get phone state: {e}")
            return {
                "currentApp": "Unknown",
                "packageName": "Unknown",
                "isEditable": False,
                "focusedElement": None,
                "error": str(e),
            }

    async def get_screen_size(self) -> Dict[str, int]:
        """
        Get screen dimensions using wm size.

        Returns:
            Dict with width and height
        """
        try:
            output = await self.device.shell("wm size")
            # Output format: "Physical size: 1080x2400"
            for line in output.split("\n"):
                if "Physical size:" in line or "Override size:" in line:
                    size_str = line.split(":")[-1].strip()
                    width, height = size_str.split("x")
                    return {"width": int(width), "height": int(height)}

            # Default fallback
            return {"width": 1080, "height": 2400}

        except Exception as e:
            logger.error(f"Failed to get screen size: {e}")
            return {"width": 1080, "height": 2400}

    async def get_state(self) -> Dict[str, Any]:
        """
        Get complete device state (UI tree + phone state + context).

        Returns:
            Combined state dict compatible with Portal format
        """
        a11y_tree = await self.get_ui_tree()
        phone_state = await self.get_phone_state()
        screen_size = await self.get_screen_size()

        return {
            "a11y_tree": a11y_tree,
            "phone_state": phone_state,
            "device_context": {
                "screen_bounds": screen_size,
                "filtering_params": {"min_element_size": 5},
            },
        }
