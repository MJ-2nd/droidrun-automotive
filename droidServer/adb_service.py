"""ADB connection service for managing device connections."""

import asyncio
import logging

from async_adbutils import AdbClient

logger = logging.getLogger("droidServer")


class AdbService:
    """Service for managing ADB connections to devices."""

    def __init__(self, adb_host: str = "127.0.0.1", adb_port: int = 5037):
        """Initialize ADB service.

        Args:
            adb_host: ADB server host (default: 127.0.0.1)
            adb_port: ADB server port (default: 5037)
        """
        self.adb_host = adb_host
        self.adb_port = adb_port
        self.client = AdbClient(host=adb_host, port=adb_port)

    async def connect(self, ip_port: str) -> tuple[bool, str]:
        """Execute adb connect command to connect to a device.

        Args:
            ip_port: Device address in "IP:PORT" format (e.g., "192.168.1.100:5555")

        Returns:
            Tuple of (success, message)
        """
        try:
            # Use shell=True with explicit command string for better compatibility
            cmd = f"adb connect {ip_port}"
            logger.info(f"Executing: {cmd}")

            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            output = stdout.decode().strip()
            error = stderr.decode().strip()

            logger.info(f"ADB connect stdout: {output}")
            if error:
                logger.info(f"ADB connect stderr: {error}")

            # Check connection result
            if "connected" in output.lower() or "already" in output.lower():
                logger.info(f"ADB connected to {ip_port}: {output}")
                return True, f"Connected to {ip_port}"
            elif "refused" in output.lower():
                return False, f"Connection refused by {ip_port}"
            elif "unable" in output.lower() or "failed" in output.lower():
                return False, f"Connection failed: {output}"
            elif proc.returncode != 0:
                return False, f"ADB connect failed: {error or output}"
            else:
                # Assume success if no error indicators
                return True, output or f"Connected to {ip_port}"

        except FileNotFoundError:
            return False, "ADB command not found. Please install Android SDK."
        except Exception as e:
            logger.exception("ADB connection error")
            return False, f"ADB connection error: {str(e)}"

    async def verify_device(self, serial: str) -> bool:
        """Verify that a device is online and accessible.

        Args:
            serial: Device serial number or IP:PORT address

        Returns:
            True if device is online, False otherwise
        """
        try:
            device = await self.client.device(serial)
            state = await device.get_state()
            return state == "device"
        except Exception as e:
            logger.warning(f"Device verification failed for {serial}: {e}")
            return False

    async def disconnect(self, ip_port: str) -> tuple[bool, str]:
        """Disconnect from a device.

        Args:
            ip_port: Device address in "IP:PORT" format

        Returns:
            Tuple of (success, message)
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "adb",
                "disconnect",
                ip_port,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            output = stdout.decode().strip()
            return True, output or f"Disconnected from {ip_port}"
        except Exception as e:
            return False, f"Disconnect error: {str(e)}"
