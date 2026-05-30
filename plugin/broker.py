"""
Vibe M5Stack - M5Stack integration for Mistral Vibe CLI
Copyright 2026 Romain Delfosse

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
""""""
M5Stack Broker - Owner/Client multi-session coordination

Implements the owner-broker pattern for multi-session M5Stack communication.
- OWNER: Holds the serial port, runs socket server, aggregates status from all sessions
- CLIENT: Connects to owner's socket, forwards requests

See BRIEF_statut_ambiant_watchdog.md for architecture details.
"""

import asyncio
import json
import logging
import os
import signal
import socket
import threading
from pathlib import Path
from queue import Queue, Empty
from typing import Optional, Dict, Any, Tuple
from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)

# Lock files
OWNER_LOCK_PATH = Path.home() / ".vibe" / "m5stack.owner.lock"
BROKER_FILE_PATH = Path.home() / ".vibe" / "m5stack.broker"
OWNER_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

# Constants
HEARTBEAT_MS = 3000  # Heartbeat interval in milliseconds
WATCHDOG_DEAD_MS = 12000  # Watchdog timeout for DEAD state
WATCHDOG_STUCK_MS = 90000  # Watchdog timeout for STUCK state


class BrokerError(Exception):
    """Base exception for broker errors."""
    pass


class AgentState:
    """Agent states for status messages."""
    THINKING = "thinking"
    WAITING = "waiting"
    DONE = "done"
    ERROR = "error"


# State priority: WAITING > THINKING > DONE
STATE_PRIORITY = {
    AgentState.WAITING: 3,
    AgentState.THINKING: 2,
    AgentState.DONE: 1,
    AgentState.ERROR: 0,
}


def aggregate_states(states: Dict[str, str]) -> str:
    """
    Aggregate multiple session states using priority.
    Returns the highest priority state.
    """
    if not states:
        return AgentState.DONE
    
    # Check if any session is WAITING
    for state in states.values():
        if state == AgentState.WAITING:
            return AgentState.WAITING
    
    # Check if any session is THINKING
    for state in states.values():
        if state == AgentState.THINKING:
            return AgentState.THINKING
    
    # Default to DONE
    return AgentState.DONE


class OwnerBroker:
    """
    OWNER role: Holds the serial port and socket server.
    Aggregates status from all sessions and sends to device.
    """
    
    def __init__(self, bridge, session_name: str = "owner"):
        self.bridge = bridge
        self.session_name = session_name
        self.server: Optional[asyncio.Server] = None
        self.server_port: Optional[int] = None
        self.server_thread: Optional[threading.Thread] = None
        self.clients: Dict[int, asyncio.StreamWriter] = {}
        self.session_states: Dict[str, Dict[str, Any]] = {}  # session_name -> {state, detail, seq}
        self.aggregated_state = AgentState.DONE
        self.aggregated_detail = ""
        self.aggregated_seq = 0
        self.lock = threading.Lock()
        self.device_lock = threading.Lock()  # Serializes device approval access
        self.running = False
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.last_heartbeat_time = 0
        # While an approval is on screen, pause status/heartbeat sends so we
        # don't flood the device's RX buffer or interleave with the approval.
        self.approval_active = False

    def start(self) -> Tuple[int, int]:
        """
        Start the broker server.
        Returns (port, pid) for broker file.
        """
        # The owner holds the serial port persistently: this is what makes
        # continuous status + heartbeat possible. send() no-ops without it.
        if self.bridge.serial_conn is None or not self.bridge.serial_conn.is_open:
            if not self.bridge.connect():
                logger.error("Owner could not open the serial port — status/heartbeat disabled")
        async def _start_server():
            self.server = await asyncio.start_server(
                self._handle_client,
                host='127.0.0.1',
                port=0  # Ephemeral port
            )
            self.server_port = self.server.sockets[0].getsockname()[1]
            logger.info(f"Broker server started on port {self.server_port}")
            async with self.server:
                await self.server.serve_forever()
        
        self.running = True
        self.server_thread = threading.Thread(
            target=asyncio.run,
            args=(_start_server(),),
            daemon=True
        )
        self.server_thread.start()
        
        # Give it a moment to start
        import time
        time.sleep(0.5)
        
        # Write broker file
        self._write_broker_file()
        
        # Start heartbeat thread
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True
        )
        self.heartbeat_thread.start()
        
        return (self.server_port, os.getpid())
    
    def _write_broker_file(self):
        """Write broker info to file."""
        if self.server_port:
            broker_info = {
                "port": self.server_port,
                "pid": os.getpid()
            }
            with open(BROKER_FILE_PATH, 'w') as f:
                json.dump(broker_info, f)
            logger.debug(f"Broker file written: {broker_info}")
    
    def _remove_broker_file(self):
        """Remove broker file."""
        try:
            BROKER_FILE_PATH.unlink(missing_ok=True)
            logger.debug("Broker file removed")
        except Exception:
            pass
    
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a client connection."""
        client_id = id(writer)
        session_name = "unknown"
        
        try:
            with self.lock:
                self.clients[client_id] = writer
            
            logger.info(f"Client connected (id={client_id})")
            
            buffer = ""
            while self.running:
                try:
                    data = await reader.read(1024)
                    if not data:
                        break
                    buffer += data.decode('utf-8', errors='ignore')
                    
                    # Process complete lines
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        if line:
                            try:
                                msg = json.loads(line)
                                self._process_client_message(client_id, msg, writer)
                                if 'session' in msg:
                                    session_name = msg['session']
                            except json.JSONDecodeError:
                                logger.warning(f"Invalid JSON from client: {line[:100]}")
                except asyncio.CancelledError:
                    break
        except Exception as e:
            logger.error(f"Client handler error: {e}")
        finally:
            with self.lock:
                self.clients.pop(client_id, None)
                # Remove session state
                self.session_states.pop(session_name, None)
                self._update_aggregated_state()
            writer.close()
            await writer.wait_closed()
            logger.info(f"Client disconnected (id={client_id}, session={session_name})")
    
    def _process_client_message(self, client_id: int, msg: Dict[str, Any], writer: asyncio.StreamWriter):
        """Process a message from a client."""
        msg_type = msg.get('type')
        session = msg.get('session', 'unknown')
        
        if msg_type == 'status':
            state = msg.get('state', AgentState.DONE)
            detail = msg.get('detail', '')
            seq = msg.get('seq', 0)
            
            with self.lock:
                self.session_states[session] = {
                    'state': state,
                    'detail': detail,
                    'seq': seq
                }
                self._update_aggregated_state()
            
            logger.debug(f"Status from {session}: {state} (seq={seq})")
        
        elif msg_type == 'approval':
            # Forward to device and return response to client
            request_id = msg.get('id')
            title = msg.get('title', '')
            body = msg.get('body', '')
            
            # Run in thread to avoid blocking the client handler
            def handle_client_approval():
                try:
                    response = self.request_approval(title, body, request_id)
                    if response:
                        response['session'] = session
                        # Send response back to client
                        try:
                            import asyncio
                            loop = self.server.get_loop() if self.server else None
                            if loop and not loop.is_closed():
                                asyncio.run_coroutine_threadsafe(
                                    self._send_to_client(writer, response),
                                    loop
                                )
                        except Exception as e:
                            logger.error(f"Failed to send approval response to client: {e}")
                except Exception as e:
                    logger.error(f"Error handling client approval: {e}")
            
            threading.Thread(target=handle_client_approval, daemon=True).start()
            logger.debug(f"Approval from {session} forwarded to device")
        
        else:
            logger.warning(f"Unknown message type from client: {msg_type}")
    
    async def _send_to_client(self, writer: asyncio.StreamWriter, msg: Dict[str, Any]):
        """Send a message to a connected client."""
        try:
            msg_str = json.dumps(msg) + '\n'
            writer.write(msg_str.encode('utf-8'))
            await writer.drain()
            logger.debug(f"Sent to client: {msg}")
        except Exception as e:
            logger.error(f"Failed to send to client: {e}")
    
    def _update_aggregated_state(self):
        """Update aggregated state from all sessions."""
        states = {s: info['state'] for s, info in self.session_states.items()}
        new_state = aggregate_states(states)
        
        # Find the most recent seq and corresponding activity
        max_seq = 0
        best_detail = ""
        best_activity = ""
        for info in self.session_states.values():
            if info['seq'] > max_seq:
                max_seq = info['seq']
                best_detail = info['detail']
                best_activity = info.get('activity', '')
        
        self.aggregated_state = new_state
        self.aggregated_detail = best_detail
        self.aggregated_seq = max_seq
        self.aggregated_activity = best_activity
        
        # Send aggregated status to device
        self._send_aggregated_status()
    
    def _send_aggregated_status(self):
        """Send aggregated status to device."""
        # Don't send status while an approval is being shown (the device is in
        # SHOWING_REQUEST and status would pile up in its RX buffer).
        if self.approval_active:
            return
        try:
            msg = {
                "type": "status",
                "state": self.aggregated_state,
                "detail": self.aggregated_detail[:40],
                "seq": self.aggregated_seq
            }
            # Only include activity for thinking state
            if self.aggregated_state == "thinking" and self.aggregated_activity:
                msg["activity"] = self.aggregated_activity
            self.bridge.send(msg)
            logger.debug(f"Sent aggregated status: {self.aggregated_state} (seq={self.aggregated_seq}, activity={self.aggregated_activity})")
        except Exception as e:
            logger.error(f"Failed to send aggregated status: {e}")
    
    def _heartbeat_loop(self):
        """Send periodic heartbeat to device."""
        import time
        while self.running:
            try:
                self._send_aggregated_status()
                time.sleep(HEARTBEAT_MS / 1000.0)
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                break
    
    def request_approval(self, title: str, body: str, request_id: int = None) -> Optional[Dict[str, Any]]:
        """
        Show an approval on the device over the persistent connection.
        Pauses status/heartbeat sends while the request is on screen.
        FIFO serialized: only one approval touches the device at a time.
        """
        with self.device_lock:  # Serializes device approval access
            self.approval_active = True
            try:
                return self.bridge.request_approval_persistent(
                    title[:40], body[:200], request_id
                )
            finally:
                self.approval_active = False

    def push_status(self, state: str, detail: str = "", seq: int = 0, activity: str = "", session: str = "owner"):
        """Push status for this owner session."""
        with self.lock:
            self.session_states[session] = {
                'state': state,
                'detail': detail,
                'seq': seq,
                'activity': activity
            }
            self._update_aggregated_state()
    
    def close(self):
        """Close the broker."""
        self.running = False
        self._remove_broker_file()
        
        # Close server
        if self.server:
            self.server.close()
            try:
                asyncio.run(self.server.wait_closed())
            except Exception:
                pass
        
        # Close all client connections
        with self.lock:
            for client_id, writer in self.clients.items():
                try:
                    writer.close()
                except Exception:
                    pass
            self.clients.clear()
        
        logger.info("Broker closed")


class ClientProxy:
    """
    CLIENT role: Connects to owner's socket and forwards messages.
    """
    
    def __init__(self, session_name: str = "default"):
        self.session_name = session_name
        self.owner_port: Optional[int] = None
        self.owner_pid: Optional[int] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.running = False
        self.reconnect_thread: Optional[threading.Thread] = None
        self.connection_lock = threading.Lock()
        
    def _read_broker_file(self) -> Optional[Dict[str, Any]]:
        """Read broker info from file."""
        try:
            if BROKER_FILE_PATH.exists():
                with open(BROKER_FILE_PATH, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return None
    
    def connect(self) -> bool:
        """Connect to owner's socket. Returns True if successful."""
        broker_info = self._read_broker_file()
        if not broker_info:
            logger.warning("No broker file found")
            return False
        
        port = broker_info.get('port')
        if not port:
            logger.warning("No port in broker file")
            return False
        
        self.owner_port = port
        self.owner_pid = broker_info.get('pid')
        
        try:
            # Test connection synchronously first
            import socket as sock
            test_sock = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
            test_sock.settimeout(2.0)
            test_sock.connect(('127.0.0.1', port))
            test_sock.close()
            logger.info(f"Connected to broker at 127.0.0.1:{port}")
            return True
        except Exception as e:
            logger.warning(f"Failed to connect to broker: {e}")
            return False
    
    async def ensure_connected(self) -> bool:
        """Ensure async connection is established."""
        if self.writer and not self.writer.is_closing():
            return True
        
        if not self.owner_port:
            if not self.connect():
                return False
        
        try:
            self.reader, self.writer = await asyncio.open_connection(
                '127.0.0.1',
                self.owner_port
            )
            logger.debug(f"Async connection established to 127.0.0.1:{self.owner_port}")
            return True
        except Exception as e:
            logger.warning(f"Async connection failed: {e}")
            self.writer = None
            self.reader = None
            return False
    
    async def send_message(self, msg: Dict[str, Any]) -> bool:
        """Send a message to the owner."""
        # Add session name
        msg = msg.copy()
        msg['session'] = self.session_name
        
        if not await self.ensure_connected():
            return False
        
        try:
            msg_str = json.dumps(msg) + '\n'
            self.writer.write(msg_str.encode('utf-8'))
            await self.writer.drain()
            logger.debug(f"Sent to broker: {msg}")
            return True
        except Exception as e:
            logger.error(f"Failed to send to broker: {e}")
            self.writer = None
            self.reader = None
            return False
    
    async def request_approval(self, title: str, body: str, request_id: int) -> Optional[Dict[str, Any]]:
        """Request approval through broker."""
        msg = {
            "type": "approval",
            "id": request_id,
            "title": title,
            "body": body
        }
        
        if not await self.send_message(msg):
            return None
        
        # Wait for response
        try:
            if self.reader:
                deadline = asyncio.get_event_loop().time() + 35.0
                while asyncio.get_event_loop().time() < deadline:
                    line = await asyncio.wait_for(self.reader.readline(), timeout=0.5)
                    if not line:
                        break
                    line = line.decode('utf-8', errors='ignore').strip()
                    if line:
                        try:
                            response = json.loads(line)
                            if response.get('type') == 'response' and response.get('id') == request_id:
                                return response
                        except json.JSONDecodeError:
                            continue
        except asyncio.TimeoutError:
            logger.warning(f"Approval request {request_id} timed out")
        except Exception as e:
            logger.error(f"Error waiting for approval response: {e}")
        
        return None
    
    def push_status(self, state: str, detail: str = "", seq: int = 0, activity: str = "") -> bool:
        """Push status to owner (synchronous wrapper)."""
        import asyncio
        msg = {
            "type": "status",
            "state": state,
            "detail": detail,
            "seq": seq
        }
        if activity:
            msg["activity"] = activity
        
        # Run async in new event loop if needed
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop.is_running():
            # Already in event loop - schedule coroutine without blocking
            asyncio.run_coroutine_threadsafe(
                self._async_push_status(msg),
                loop
            )
            return True  # Non-blocking, fire-and-forget
        else:
            return loop.run_until_complete(self._async_push_status(msg))
    
    async def _async_push_status(self, msg: Dict[str, Any]) -> bool:
        """Async helper for push_status."""
        msg = msg.copy()
        msg['session'] = self.session_name
        # Ensure activity is included if present
        if 'activity' in msg:
            msg['activity'] = msg['activity']
        return await self.send_message(msg)
    
    def close(self):
        """Close the client connection."""
        self.running = False
        if self.writer:
            try:
                self.writer.close()
            except Exception:
                pass
        self.writer = None
        self.reader = None
        logger.info("Client proxy closed")


class BrokerManager:
    """
    Manages the owner/client election and provides a unified interface.
    """
    
    def __init__(self, bridge, session_name: str = "default"):
        self.bridge = bridge
        self.session_name = session_name
        self.owner_lock = FileLock(str(OWNER_LOCK_PATH))
        self.broker: Optional[OwnerBroker] = None
        self.client: Optional[ClientProxy] = None
        self.role: Optional[str] = None  # 'owner' or 'client'
        self._initialized = False
        
    def initialize(self) -> bool:
        """
        Initialize as owner or client based on lock acquisition.
        Returns True if successful.
        """
        if self._initialized:
            return True
        
        # Check M5STACK_OWNER=0
        if os.environ.get('M5STACK_OWNER') == '0':
            logger.info("M5STACK_OWNER=0: forcing client mode")
            return self._initialize_as_client()
        
        # Try to acquire owner lock (non-blocking)
        try:
            self.owner_lock.acquire(timeout=0)
            logger.info("Acquired owner lock - running as OWNER")
            self.role = 'owner'
            self.broker = OwnerBroker(self.bridge, self.session_name)
            port, pid = self.broker.start()
            logger.info(f"Broker started on port {port}, pid {pid}")
            self._initialized = True
            return True
        except Timeout:
            # Could not acquire lock - become client
            logger.info("Owner lock held - running as CLIENT")
            return self._initialize_as_client()
    
    def _initialize_as_client(self) -> bool:
        """Initialize as client."""
        self.role = 'client'
        self.client = ClientProxy(self.session_name)
        if self.client.connect():
            self._initialized = True
            logger.info(f"Connected to broker as client: {self.session_name}")
            return True
        else:
            logger.warning("Could not connect to broker - no owner running. "
                           "Client mode with no connection (approval falls back to TUI).")
            # Client mode is validly initialized even without a connection: the
            # session just falls back to TUI-only. Report success so the role is
            # honored; callers detect the missing connection via owner_port.
            self._initialized = True
            return True
    
    def is_owner(self) -> bool:
        return self.role == 'owner'
    
    def is_client(self) -> bool:
        return self.role == 'client'
    
    def push_status(self, state: str, detail: str = "", seq: int = 0, activity: str = "") -> bool:
        """Push status to device (routed to broker or directly)."""
        if not self._initialized:
            self.initialize()
        
        if self.is_owner() and self.broker:
            self.broker.push_status(state, detail, seq, activity, self.session_name)
            return True
        elif self.is_client() and self.client:
            return self.client.push_status(state, detail, seq, activity)
        return False
    
    async def request_approval(self, title: str, body: str, request_id: int) -> Optional[Dict[str, Any]]:
        """Request approval (routed to broker or directly)."""
        if not self._initialized:
            self.initialize()
        
        if self.is_owner() and self.broker:
            # Over the owner's persistent connection (NOT ephemeral — the port
            # is already held open by this owner).
            return self.broker.request_approval(title, body, request_id)
        elif self.is_client() and self.client:
            return await self.client.request_approval(title, body, request_id)
        return None
    
    def close(self):
        """Close broker or client."""
        if self.broker:
            self.broker.close()
            self.broker = None
        if self.client:
            self.client.close()
            self.client = None
        if self.owner_lock.is_locked:
            self.owner_lock.release()
        self._initialized = False
        self.role = None
    
    def __del__(self):
        self.close()
