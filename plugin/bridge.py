"""
M5Stack Serial Bridge

Handles communication between PC and M5Stack Core 2 via USB Serial.
Multi-session safe via file lock - opens port per-request, not permanently.
"""

import logging
import serial
import serial.tools.list_ports
import json
import time
import threading
from pathlib import Path
from typing import Optional, Callable, Dict, Any
from queue import Queue, Empty

from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)

# Global lock file for multi-session coordination
_LOCK_PATH = Path.home() / ".vibe" / "m5stack.lock"
_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)


class M5StackBridge:
    """
    Manages serial communication with M5Stack Core 2 device.
    
    Automatically detects the device and handles JSON message exchange.
    """
    
    BAUD_RATE = 115200
    TIMEOUT = 1.0  # Read timeout in seconds
    
    def __init__(self, port: Optional[str] = None, auto_connect: bool = True):
        """
        Initialize the bridge.
        
        Note: By default, auto_connect=True will establish a persistent connection
        for backwards compatibility (e.g., test_bridge.py).
        For multi-session usage, set auto_connect=False and use request_approval()
        which handles connections ephemerally with file locking.
        
        Args:
            port: Specific serial port to use (e.g., 'COM3' or '/dev/ttyUSB0')
            auto_connect: If True, automatically find and connect to M5Stack
        """
        self.serial_conn: Optional[serial.Serial] = None
        self.port = port
        self.message_queue = Queue()
        self.response_queue = Queue()
        self.running = False
        self.reader_thread: Optional[threading.Thread] = None
        
        if auto_connect:
            self.connect()
    
    def connect(self, port: Optional[str] = None) -> bool:
        """
        Connect to M5Stack device and open a persistent connection.
        
        Note: This method opens a persistent connection for backwards compatibility
        with code that uses send()/receive() directly (e.g., test_bridge.py).
        For normal usage, request_approval() handles connections ephemerally with locking.
        
        Args:
            port: Specific port to connect to. If None, auto-detects.
        
        Returns:
            True if connection succeeded, False otherwise
        """
        if port:
            self.port = port
        elif not self.port:
            self.port = self._auto_detect_port()
            if not self.port:
                logger.error("M5Stack device not found. Please connect via USB.")
                return False
        
        try:
            self.serial_conn = serial.Serial(
                self.port,
                baudrate=self.BAUD_RATE,
                timeout=self.TIMEOUT
            )
            self.running = True
            self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.reader_thread.start()
            
            # Wait for device to initialize
            time.sleep(0.5)
            
            logger.info(f"Connected to M5Stack on {self.port} (persistent connection)")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {self.port}: {e}")
            self.serial_conn = None
            return False
    
    def _probe_port(self, port_name: str, timeout: float = 1.0) -> bool:
        """
        Probe a serial port to check if it's an M5Stack device.
        
        Opens the port and listens for JSON messages with a "type" key.
        Our firmware sends {"type":"ping"} every 5 seconds in IDLE mode.
        
        Args:
            port_name: Name of the port to probe
            timeout: Maximum time to wait for a valid message
            
        Returns:
            True if the port responds with valid M5Stack JSON, False otherwise
        """
        import json as _json
        import time as _time
        try:
            with serial.Serial(port_name, baudrate=self.BAUD_RATE, timeout=0.1) as s:
                deadline = _time.time() + timeout
                buf = b""
                while _time.time() < deadline:
                    # Read available data
                    if s.in_waiting:
                        buf += s.read(s.in_waiting or 1)
                    # Process complete lines
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        try:
                            data = _json.loads(line.decode("utf-8", errors="ignore"))
                            if isinstance(data, dict) and "type" in data:
                                return True
                        except Exception:
                            pass
                    _time.sleep(0.05)
            return False
        except Exception:
            return False

    def _auto_detect_port(self) -> Optional[str]:
        """
        Auto-detect M5Stack Core 2 serial port.
        
        Returns:
            Port name if found, None otherwise
        """
        ports = list(serial.tools.list_ports.comports())
        
        # M5Stack Core 2 typically appears as:
        # - Windows: CP210x or CH340 (Silicon Labs CP210x USB to UART Bridge)
        # - Linux/Mac: /dev/ttyUSB0 or /dev/ttyACM0
        
        candidates = []
        for port in ports:
            port_str = str(port)
            
            # Check for common M5Stack identifiers
            if any(keyword in port_str.upper() for keyword in 
                   ['CP210', 'CH340', 'M5STACK', 'SILABS']):
                candidates.append(port.device)
            
            # Also try generic USB serial ports
            elif 'ttyUSB' in port.device or 'ttyACM' in port.device or 'COM' in port.device:
                candidates.append(port.device)
        
        # Probe each candidate to validate it's actually an M5Stack
        for port_name in candidates:
            if self._probe_port(port_name):
                return port_name
        
        return None
    
    def _read_loop(self):
        """Background thread that reads from serial and queues messages."""
        buffer = ""
        while self.running:
            try:
                if self.serial_conn and self.serial_conn.in_waiting:
                    # Read all available data
                    data = self.serial_conn.read_all().decode('utf-8', errors='ignore')
                    buffer += data
                    
                    # Process complete lines (JSON messages are newline-terminated)
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        if line:
                            try:
                                msg = json.loads(line)
                                self.message_queue.put(msg)
                            except json.JSONDecodeError:
                                # Not valid JSON, might be partial
                                pass
                    
                time.sleep(0.01)
            except Exception as e:
                logger.error(f"Serial read error: {e}")
                break
    
    def send(self, message: Dict[str, Any]) -> bool:
        """
        Send a JSON message to M5Stack.
        
        Args:
            message: Dictionary to send as JSON
        
        Returns:
            True if message was sent successfully
        """
        if not self.serial_conn:
            return False
        
        try:
            json_str = json.dumps(message)
            self.serial_conn.write(json_str.encode('utf-8') + b'\n')
            self.serial_conn.flush()
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False
    
    def receive(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Receive a message from M5Stack.
        
        Args:
            timeout: Maximum time to wait for a message (None = no timeout)
        
        Returns:
            Parsed JSON message or None if timeout/error
        """
        try:
            return self.message_queue.get(timeout=timeout)
        except Empty:
            return None
    
    def request_approval(self, title: str, body: str, request_id: int | None = None) -> Optional[Dict[str, Any]]:
        """
        Send an approval request to M5Stack.
        
        Acquires global lock -> connects -> sends -> waits response -> closes -> releases.
        This enables multi-session safety: multiple vibe instances serialize their
        approvals via the file lock (FIFO).
        
        Args:
            title: Short title for the request
            body: Detailed description  
            request_id: Optional unique identifier (auto-generated if None)
        
        Returns:
            Response message from M5Stack or None on timeout/error
        """
        if request_id is None:
            request_id = int(time.monotonic() * 1000) % 1_000_000
        
        # Resolve port first (outside lock to avoid blocking other sessions during probe)
        port = self.port or self._auto_detect_port()
        if not port:
            logger.warning("M5Stack port not found")
            return None
        
        lock = FileLock(str(_LOCK_PATH))
        try:
            # Wait up to 60s for another session to release the M5Stack
            lock.acquire(timeout=60)
        except Timeout:
            logger.warning("M5Stack lock timeout — another vibe session is holding it")
            return None
        
        try:
            # Open a fresh connection just for this approval
            with serial.Serial(port, baudrate=self.BAUD_RATE, timeout=self.TIMEOUT) as conn:
                # Send request
                message = {"type": "approval", "id": request_id, "title": title, "body": body}
                conn.write(json.dumps(message).encode("utf-8") + b"\n")
                conn.flush()
                
                # Wait for matching response, filter pings
                deadline = time.monotonic() + 35.0
                buf = b""
                while time.monotonic() < deadline:
                    if conn.in_waiting:
                        buf += conn.read(conn.in_waiting or 1)
                    
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        try:
                            msg = json.loads(line.decode("utf-8", errors="ignore"))
                        except Exception:
                            continue
                        
                        if msg.get("type") == "response" and msg.get("id") == request_id:
                            logger.debug(f"Received approval response for request {request_id}")
                            return msg
                    
                    time.sleep(0.01)
                
                logger.warning(f"Approval request {request_id} timed out")
                return None
        finally:
            lock.release()
    
    def send_credit_info(self, percent: int) -> bool:
        """
        Send credit usage percentage to M5Stack.
        
        Args:
            percent: Credit usage percentage (0-100)
        
        Returns:
            True if message was sent successfully
        """
        message = {
            "type": "credit_info",
            "percent": max(0, min(100, percent))
        }
        return self.send(message)
    
    def close(self):
        """Close the serial connection."""
        self.running = False
        if self.reader_thread:
            self.reader_thread.join(timeout=1.0)
        if self.serial_conn:
            self.serial_conn.close()
            self.serial_conn = None
    
    def __del__(self):
        self.close()
    
    @property
    def is_connected(self) -> bool:
        """True if device is connected (persistent connection) or port is detectable."""
        # For persistent connections (backwards compatibility)
        if self.serial_conn is not None and self.serial_conn.is_open:
            return True
        # For ephemeral mode: port is resolvable
        return (self.port or self._auto_detect_port()) is not None
