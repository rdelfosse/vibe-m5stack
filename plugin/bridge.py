"""
M5Stack Serial Bridge

Handles communication between PC and M5Stack Core 2 via USB Serial.
"""

import logging
import serial
import serial.tools.list_ports
import json
import time
import threading
from typing import Optional, Callable, Dict, Any
from queue import Queue, Empty

logger = logging.getLogger(__name__)


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
        Connect to M5Stack device.
        
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
            
            logger.info(f"Connected to M5Stack on {self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {self.port}: {e}")
            self.serial_conn = None
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
        
        for port in ports:
            port_str = str(port)
            
            # Check for common M5Stack identifiers
            if any(keyword in port_str.upper() for keyword in 
                   ['CP210', 'CH340', 'M5STACK', 'SILABS']):
                return port.device
            
            # Also try generic USB serial ports
            if 'ttyUSB' in port.device or 'ttyACM' in port.device or 'COM' in port.device:
                return port.device
        
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
    
    def request_approval(self, title: str, body: str, request_id: int = None) -> Optional[Dict[str, Any]]:
        """
        Send an approval request to M5Stack.
        
        Args:
            title: Short title for the request
            body: Detailed description
            request_id: Optional unique identifier
        
        Returns:
            Response message from M5Stack or None on timeout
        """
        if request_id is None:
            request_id = int(time.time() * 1000) % 1000000
        
        message = {
            "type": "approval",
            "id": request_id,
            "title": title,
            "body": body
        }
        
        if not self.send(message):
            return None
        
        # Wait for response with matching request_id, filtering out pings
        # Total timeout: 35 seconds
        deadline = time.time() + 35
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                logger.warning(f"Approval request {request_id} timed out")
                return None
            
            msg = self.receive(timeout=min(1.0, remaining))
            if msg is None:
                continue
            
            msg_type = msg.get("type")
            msg_id = msg.get("id")
            
            # Filter out ping messages and other unrelated messages
            if msg_type == "ping":
                logger.debug(f"Ignoring ping message")
                continue
            
            # Check if this is our response
            if msg_type == "response" and msg_id == request_id:
                logger.debug(f"Received approval response for request {request_id}")
                return msg
            
            # Log unexpected messages
            logger.debug(f"Unexpected message: type={msg_type}, id={msg_id}")
        
        logger.warning(f"Approval request {request_id} timed out")
        return None
    
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
        """Check if device is connected."""
        return self.serial_conn is not None and self.serial_conn.is_open
