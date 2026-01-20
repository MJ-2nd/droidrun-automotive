"""
UIAutomator XML Parser - Converts uiautomator dump XML to Portal-compatible JSON format.

This parser transforms the XML output from `adb shell uiautomator dump` into the same
JSON structure that Portal's Accessibility Service returns, enabling seamless
integration with existing TreeFilter and IndexedFormatter.

Also includes DumpsysParser for parsing `dumpsys activity top` output as a fallback
when uiautomator dump fails (common on AAOS/Automotive devices).
"""

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

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


class DumpsysParser:
    """
    Parses `dumpsys activity top` output and converts to Portal-compatible JSON format.

    This parser is used as a fallback when uiautomator dump fails with
    "could not get idle state" error, which is common on AAOS/Automotive devices.

    Input format (dumpsys activity top View Hierarchy section):
        View Hierarchy:
          DecorView@12345678[MainActivity]
            android.widget.LinearLayout{abc123 V.E...... ........ 0,0-1080,2400}
              android.widget.FrameLayout{def456 V.E...... ........ 0,0-1080,2400 #1020002 android:id/content}
                ...

    View line format:
        ClassName{hashCode flags bounds [resourceId]}
        - flags: V=Visible, I=Invisible, G=Gone, E=Enabled, F=Focused, etc.
        - bounds: left,top-right,bottom (e.g., 0,0-1080,2400)
        - resourceId: #hexid package:id/name (optional)

    Output JSON format (Portal-compatible):
        {
            "className": "android.widget.FrameLayout",
            "text": "",
            "resourceId": "android:id/content",
            "contentDescription": "",
            "boundsInScreen": {"left": 0, "top": 0, "right": 1080, "bottom": 2400},
            "clickable": false,
            "focusable": false,
            "focused": false,
            "enabled": true,
            "children": [...]
        }
    """

    # Pattern to match view lines: ClassName{hashCode flags bounds [resourceId]}
    # Example: android.widget.LinearLayout{abc123 V.E...... ........ 0,0-1080,2400 #1020002 android:id/content}
    VIEW_PATTERN = re.compile(
        r"^(\s*)"  # Group 1: Leading whitespace (indentation)
        r"([a-zA-Z0-9_.]+(?:\$[a-zA-Z0-9_]+)?)"  # Group 2: Class name (e.g., android.widget.LinearLayout or inner class)
        r"\{"  # Opening brace
        r"([a-fA-F0-9]+)"  # Group 3: Hash code
        r"\s+"  # Space
        r"([VIGEFDS.]+)"  # Group 4: Visibility/state flags
        r"\s+"  # Space
        r"([.LCPXSHOD]+)"  # Group 5: Other flags (clickable, focusable, etc.)
        r"\s+"  # Space
        r"(\d+),(\d+)-(\d+),(\d+)"  # Groups 6-9: Bounds (left,top-right,bottom)
        r"(?:\s+#[a-fA-F0-9]+\s+([a-zA-Z0-9_.:$/]+))?"  # Group 10: Optional resource ID
        r"(?:\s+(.+?))?"  # Group 11: Optional text content
        r"\}",  # Closing brace
        re.MULTILINE,
    )

    # Alternative simpler pattern for views without full flags
    VIEW_SIMPLE_PATTERN = re.compile(
        r"^(\s*)"  # Group 1: Indentation
        r"([a-zA-Z0-9_.$]+)"  # Group 2: Class name
        r"\{"  # Opening brace
        r"([^}]+)"  # Group 3: Content inside braces
        r"\}",
        re.MULTILINE,
    )

    # Pattern to extract bounds from content
    BOUNDS_PATTERN = re.compile(r"(\d+),(\d+)-(\d+),(\d+)")

    # Pattern to extract resource ID
    RESOURCE_ID_PATTERN = re.compile(r"#[a-fA-F0-9]+\s+([a-zA-Z0-9_.:$/]+)")

    def parse(self, dumpsys_output: str) -> Optional[Dict[str, Any]]:
        """
        Parse dumpsys activity top output to Portal-compatible JSON.

        Args:
            dumpsys_output: Raw output from `adb shell dumpsys activity top`

        Returns:
            Parsed tree in Portal JSON format, or None if parsing fails
        """
        try:
            # Extract View Hierarchy section
            view_hierarchy = self._extract_view_hierarchy(dumpsys_output)
            if not view_hierarchy:
                logger.warning("No View Hierarchy section found in dumpsys output")
                return None

            # Parse the hierarchy into a tree
            lines = view_hierarchy.split("\n")
            root_nodes = self._parse_lines(lines)

            if not root_nodes:
                logger.warning("No view nodes parsed from dumpsys output")
                return None

            # Return single root or wrap multiple roots
            if len(root_nodes) == 1:
                return root_nodes[0]
            else:
                return {
                    "className": "VirtualRoot",
                    "text": "",
                    "resourceId": "",
                    "contentDescription": "",
                    "boundsInScreen": self._calculate_bounds(root_nodes),
                    "clickable": False,
                    "focusable": False,
                    "focused": False,
                    "enabled": True,
                    "children": root_nodes,
                }

        except Exception as e:
            logger.error(f"Failed to parse dumpsys output: {e}")
            return None

    def _extract_view_hierarchy(self, dumpsys_output: str) -> Optional[str]:
        """
        Extract the View Hierarchy section from dumpsys output.

        Args:
            dumpsys_output: Full dumpsys activity top output

        Returns:
            View Hierarchy section content, or None if not found
        """
        # Find "View Hierarchy:" marker
        markers = ["View Hierarchy:", "TASK ", "ACTIVITY "]
        start_idx = -1

        for marker in markers:
            idx = dumpsys_output.find(marker)
            if idx != -1:
                if marker == "View Hierarchy:":
                    start_idx = idx + len(marker)
                    break
                # For TASK/ACTIVITY, look for View Hierarchy after it
                vh_idx = dumpsys_output.find("View Hierarchy:", idx)
                if vh_idx != -1:
                    start_idx = vh_idx + len("View Hierarchy:")
                    break

        if start_idx == -1:
            # Try to find any view pattern in the output
            if self.BOUNDS_PATTERN.search(dumpsys_output):
                return dumpsys_output
            return None

        # Find end of View Hierarchy section (next section or end of output)
        end_markers = [
            "\n  Looper ",
            "\n  mHandler",
            "\n  ViewRoot",
            "\nTASK ",
            "\nACTIVITY ",
            "\n\n",
        ]
        end_idx = len(dumpsys_output)

        for marker in end_markers:
            idx = dumpsys_output.find(marker, start_idx)
            if idx != -1 and idx < end_idx:
                end_idx = idx

        return dumpsys_output[start_idx:end_idx].strip()

    def _parse_lines(self, lines: List[str]) -> List[Dict[str, Any]]:
        """
        Parse view hierarchy lines into a tree structure.

        Args:
            lines: Lines from View Hierarchy section

        Returns:
            List of root node dictionaries
        """
        if not lines:
            return []

        # Stack to track parent nodes at each indentation level
        # Each entry: (indent_level, node_dict)
        stack: List[Tuple[int, Dict[str, Any]]] = []
        root_nodes: List[Dict[str, Any]] = []

        for line in lines:
            if not line.strip():
                continue

            node = self._parse_view_line(line)
            if not node:
                continue

            indent = len(line) - len(line.lstrip())

            # Pop nodes from stack that are at same or deeper level
            while stack and stack[-1][0] >= indent:
                stack.pop()

            if stack:
                # Add as child to parent
                parent = stack[-1][1]
                parent["children"].append(node)
            else:
                # This is a root node
                root_nodes.append(node)

            # Push current node to stack
            stack.append((indent, node))

        return root_nodes

    def _parse_view_line(self, line: str) -> Optional[Dict[str, Any]]:
        """
        Parse a single view line into Portal-compatible dict.

        Args:
            line: Single line from View Hierarchy

        Returns:
            Portal-compatible dict or None if parsing fails
        """
        line = line.rstrip()
        if not line.strip():
            return None

        # Skip DecorView and non-standard lines
        if "DecorView@" in line or line.strip().startswith("DecorView"):
            # Parse DecorView specially
            return self._parse_decor_view(line)

        # Try main pattern first
        match = self.VIEW_PATTERN.match(line)
        if match:
            return self._create_node_from_match(match)

        # Try simpler pattern
        match = self.VIEW_SIMPLE_PATTERN.match(line)
        if match:
            return self._create_node_from_simple_match(match)

        return None

    def _parse_decor_view(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse DecorView line which has different format."""
        # DecorView@12345678[ActivityName]
        class_name = "DecorView"

        # Try to find bounds if present
        bounds = {"left": 0, "top": 0, "right": 1080, "bottom": 2400}
        bounds_match = self.BOUNDS_PATTERN.search(line)
        if bounds_match:
            bounds = {
                "left": int(bounds_match.group(1)),
                "top": int(bounds_match.group(2)),
                "right": int(bounds_match.group(3)),
                "bottom": int(bounds_match.group(4)),
            }

        return {
            "className": class_name,
            "text": "",
            "resourceId": "",
            "contentDescription": "",
            "boundsInScreen": bounds,
            "clickable": False,
            "focusable": False,
            "focused": False,
            "enabled": True,
            "scrollable": False,
            "checkable": False,
            "checked": False,
            "selected": False,
            "longClickable": False,
            "password": False,
            "package": "",
            "children": [],
        }

    def _create_node_from_match(self, match: re.Match) -> Dict[str, Any]:
        """Create node dict from main regex match."""
        class_name = match.group(2)
        vis_flags = match.group(4)
        other_flags = match.group(5)
        left = int(match.group(6))
        top = int(match.group(7))
        right = int(match.group(8))
        bottom = int(match.group(9))
        resource_id = match.group(10) or ""
        text = match.group(11) or ""

        # Parse flags
        # Visibility: V=Visible, I=Invisible, G=Gone
        # State: E=Enabled, D=Disabled, F=Focused, S=Selected
        is_enabled = "E" in vis_flags
        is_focused = "F" in vis_flags or "F" in other_flags
        is_selected = "S" in vis_flags

        # Other flags: C=Clickable, L=LongClickable, X=ContextClickable, P=Focusable, etc.
        is_clickable = "C" in other_flags
        is_long_clickable = "L" in other_flags
        is_focusable = "P" in other_flags or "F" in other_flags

        return {
            "className": class_name,
            "text": text.strip() if text else "",
            "resourceId": resource_id,
            "contentDescription": "",
            "boundsInScreen": {
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
            },
            "clickable": is_clickable,
            "focusable": is_focusable,
            "focused": is_focused,
            "enabled": is_enabled,
            "scrollable": False,
            "checkable": False,
            "checked": False,
            "selected": is_selected,
            "longClickable": is_long_clickable,
            "password": False,
            "package": "",
            "children": [],
        }

    def _create_node_from_simple_match(self, match: re.Match) -> Optional[Dict[str, Any]]:
        """Create node dict from simple regex match."""
        class_name = match.group(2)
        content = match.group(3)

        # Try to extract bounds
        bounds_match = self.BOUNDS_PATTERN.search(content)
        if not bounds_match:
            return None

        bounds = {
            "left": int(bounds_match.group(1)),
            "top": int(bounds_match.group(2)),
            "right": int(bounds_match.group(3)),
            "bottom": int(bounds_match.group(4)),
        }

        # Try to extract resource ID
        resource_id = ""
        res_match = self.RESOURCE_ID_PATTERN.search(content)
        if res_match:
            resource_id = res_match.group(1)

        # Check for visibility/state flags
        is_enabled = " E" in content or ".E" in content
        is_focused = " F" in content or ".F" in content
        is_clickable = " C" in content or ".C" in content

        return {
            "className": class_name,
            "text": "",
            "resourceId": resource_id,
            "contentDescription": "",
            "boundsInScreen": bounds,
            "clickable": is_clickable,
            "focusable": False,
            "focused": is_focused,
            "enabled": is_enabled,
            "scrollable": False,
            "checkable": False,
            "checked": False,
            "selected": False,
            "longClickable": False,
            "password": False,
            "package": "",
            "children": [],
        }

    def _calculate_bounds(self, nodes: List[Dict[str, Any]]) -> Dict[str, int]:
        """Calculate combined bounds from multiple nodes."""
        if not nodes:
            return {"left": 0, "top": 0, "right": 1080, "bottom": 2400}

        left = min(n["boundsInScreen"]["left"] for n in nodes)
        top = min(n["boundsInScreen"]["top"] for n in nodes)
        right = max(n["boundsInScreen"]["right"] for n in nodes)
        bottom = max(n["boundsInScreen"]["bottom"] for n in nodes)

        return {"left": left, "top": top, "right": right, "bottom": bottom}


class AutomotiveStateProvider:
    """
    Provides device state for AAOS using ADB commands instead of Accessibility Service.

    This class replaces Portal's get_state() functionality with ADB-only alternatives.

    Strategy for UI tree retrieval:
    1. First try uiautomator dump (standard method)
    2. If uiautomator fails with "could not get idle state", fallback to dumpsys activity top
    """

    def __init__(self, device):
        """
        Initialize with ADB device.

        Args:
            device: async_adbutils device instance
        """
        self.device = device
        self.uiautomator_parser = UIAutomatorParser()
        self.dumpsys_parser = DumpsysParser()
        # Track which method works to optimize future calls
        self._preferred_method: Optional[str] = None  # "uiautomator" or "dumpsys"

    async def get_ui_tree(self) -> Optional[Dict[str, Any]]:
        """
        Get UI tree with automatic fallback.

        Strategy:
        1. If preferred method is known, try that first
        2. Otherwise, try uiautomator dump first
        3. If uiautomator fails (idle state error), fallback to dumpsys activity top
        4. Remember which method worked for future calls

        Returns:
            Parsed UI tree in Portal-compatible format
        """
        # If we already know which method works, try that first
        if self._preferred_method == "dumpsys":
            result = await self._get_ui_tree_dumpsys()
            if result:
                return result
            # Dumpsys failed, try uiautomator as backup
            return await self._get_ui_tree_uiautomator()

        # Default: Try uiautomator first, then dumpsys
        result = await self._get_ui_tree_uiautomator()
        if result:
            self._preferred_method = "uiautomator"
            return result

        # Uiautomator failed, try dumpsys
        logger.info("uiautomator failed, falling back to dumpsys activity top")
        result = await self._get_ui_tree_dumpsys()
        if result:
            self._preferred_method = "dumpsys"
            logger.info("dumpsys fallback successful, will use dumpsys for future calls")
        return result

    async def _get_ui_tree_uiautomator(self) -> Optional[Dict[str, Any]]:
        """
        Get UI tree using uiautomator dump.

        Returns:
            Parsed UI tree or None if failed
        """
        # Try multiple strategies for uiautomator
        strategies = [
            "uiautomator dump /dev/tty",
            "uiautomator dump --compressed /dev/tty",
            "uiautomator dump /sdcard/window_dump.xml && cat /sdcard/window_dump.xml && rm -f /sdcard/window_dump.xml",
        ]

        for strategy in strategies:
            try:
                output = await self.device.shell(strategy)

                # Check for error conditions
                if "ERROR" in output or "could not get idle state" in output.lower():
                    logger.debug(f"uiautomator strategy failed: {strategy}")
                    continue

                # Clean up success message
                if "UI hierchary dumped" in output or "UI hierarchy dumped" in output:
                    end_markers = ["UI hierchary dumped", "UI hierarchy dumped"]
                    for marker in end_markers:
                        idx = output.find(marker)
                        if idx != -1:
                            output = output[:idx].strip()
                            break

                # Try to parse
                if "<hierarchy" in output or '<?xml' in output:
                    result = self.uiautomator_parser.parse(output)
                    if result:
                        logger.debug(f"uiautomator strategy succeeded: {strategy}")
                        return result

            except Exception as e:
                logger.debug(f"uiautomator strategy exception ({strategy}): {e}")
                continue

        return None

    async def _get_ui_tree_dumpsys(self) -> Optional[Dict[str, Any]]:
        """
        Get UI tree using dumpsys activity top (fallback method).

        Returns:
            Parsed UI tree or None if failed
        """
        try:
            # Get the View Hierarchy from dumpsys activity top
            output = await self.device.shell("dumpsys activity top")

            if not output or "View Hierarchy" not in output:
                logger.warning("dumpsys activity top returned no View Hierarchy")
                return None

            result = self.dumpsys_parser.parse(output)
            if result:
                logger.debug("dumpsys activity top parsing successful")
            return result

        except Exception as e:
            logger.error(f"Failed to get UI tree via dumpsys: {e}")
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
