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
Vibe M5Stack Hook - Intercepts tool permission requests and forwards to M5Stack device.

This module monkey-patches Vibe's AgentLoop to wrap the approval callback
with a race between the native Textual UI modal and the M5Stack device.
Whichever responds first wins.

Usage:
    This module is automatically loaded by the vibe-m5stack wrapper script.
    It should NOT be imported directly.

Environment:
    - M5Stack must be connected via USB
    - Requires pyserial to be installed
    - Optional: M5STACK_PORT env var to specify port (e.g., "COM8")
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# Setup logging to file only - NO stderr to avoid TUI pollution
_log_dir = Path.home() / ".vibe" / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_handler = logging.FileHandler(_log_dir / "m5stack_hook.log", encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger = logging.getLogger("m5stack_hook")
logger.setLevel(logging.INFO)
logger.addHandler(_handler)
logger.propagate = False  # CRITICAL - prevents logs from bubbling to root logger (stderr)

# Add plugin directory to path
_PLUGIN_DIR = Path(__file__).parent.resolve()
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from plugin.bridge import M5StackBridge
from plugin.m5stack_utils import SessionManager
from vibe.core.types import ApprovalResponse
from vibe.core.tools.permissions import RequiredPermission

from vibe.core.types import (
    UserMessageEvent,
    AssistantEvent,
    ReasoningEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolStreamEvent,
    WaitingForInputEvent,
    CompactStartEvent,
    CompactEndEvent,
    PlanReviewRequestedEvent,
    SessionTitleUpdatedEvent,
)

# Global state tracking for status
_status_seq = 0
_last_status_state = "done"
_last_status_detail = ""

# Session manager singleton for multi-session support
_session_mgr = SessionManager()




def map_event_to_status(event) -> tuple:
    """Map Vibe events to agent states."""
    global _status_seq
    
    state = "thinking"
    detail = ""
    seq_increment = False
    
    event_type = type(event).__name__
    
    if event_type in ("ToolCallEvent", "AssistantEvent", "ReasoningEvent", "ToolStreamEvent"):
        state = "thinking"
        # Only ToolCallEvent carries a tool_name. For the others, leave detail
        # empty — never fall back to str(event), which is the Python object repr
        # and would be shown verbatim on the device screen.
        tool_name = getattr(event, "tool_name", None)
        detail = str(tool_name)[:40] if tool_name else ""
        seq_increment = True
    elif event_type == "WaitingForInputEvent":
        state = "waiting"
        detail = "awaiting input"
    elif event_type == "CompactStartEvent":
        state = "thinking"
        detail = "compacting"
        seq_increment = True
    elif event_type in ("CompactEndEvent", "SessionTitleUpdatedEvent", "PlanReviewRequestedEvent"):
        state = "thinking"
        seq_increment = True
    
    if seq_increment:
        _status_seq += 1
    
    return state, detail, _status_seq


# Owner-broker manager (lazily initialized on first use).
_broker_mgr: Any = None
_broker_init_attempted = False


def get_or_init_broker():
    """Lazily build and initialize the owner-broker manager.

    On first call: opens the M5Stack port (owner) or connects to an existing
    owner's socket (client). Returns the BrokerManager, or None if init failed
    (in which case the approval path falls back to the ephemeral bridge).
    """
    global _broker_mgr, _broker_init_attempted
    if _broker_mgr is not None:
        return _broker_mgr
    if _broker_init_attempted:
        return None  # already failed once; don't retry on every event
    _broker_init_attempted = True
    try:
        import atexit
        from plugin.broker import BrokerManager

        port = os.environ.get("M5STACK_PORT")
        raw_bridge = M5StackBridge(port=port, auto_connect=False)
        session = _session_mgr.session_name or "default"
        mgr = BrokerManager(raw_bridge, session)
        mgr.initialize()
        _broker_mgr = mgr
        atexit.register(_safe_close_broker)
        logger.info(f"Broker initialized: role={mgr.role}")
        return _broker_mgr
    except Exception as e:
        logger.error(f"Broker init failed: {e}")
        return None


def _safe_close_broker():
    try:
        if _broker_mgr is not None:
            _broker_mgr.close()
    except Exception:
        pass


def _broker_can_approve(mgr) -> bool:
    """True if the broker can actually reach the device for an approval."""
    if mgr is None or mgr.role is None:
        return False
    if mgr.is_owner():
        conn = getattr(mgr.bridge, "serial_conn", None)
        return conn is not None and conn.is_open
    if mgr.is_client():
        return mgr.client is not None and mgr.client.owner_port is not None
    return False


_last_push_state = None
_last_push_monotonic = 0.0
_PUSH_THROTTLE_S = 0.25  # min interval between same-state pushes


def push_status_to_device(state: str, detail: str = "", seq: int = 0) -> bool:
    """Push agent status to the M5Stack via the owner-broker (best-effort).

    Streaming events (assistant/tool chunks) can fire hundreds of times per turn;
    we throttle same-state pushes so we don't saturate the (BT) serial link.
    State transitions always go through immediately.
    """
    global _last_push_state, _last_push_monotonic
    import time

    now = time.monotonic()
    if state == _last_push_state and (now - _last_push_monotonic) < _PUSH_THROTTLE_S:
        return True
    _last_push_state = state
    _last_push_monotonic = now

    mgr = get_or_init_broker()
    if mgr is None:
        return False
    try:
        return mgr.push_status(state, detail, seq)
    except Exception as e:
        logger.error(f"Failed to push status: {e}")
        return False

class ThreadSafeM5StackBridge:
    """Thread-safe wrapper around M5StackBridge for async/sync boundary."""

    def __init__(self, bridge: M5StackBridge):
        self._bridge = bridge
        self._lock = asyncio.Lock()

    async def request_approval(
        self, title: str, body: str, timeout: float = 30.0
    ) -> dict[str, Any] | None:
        """
        Request approval from M5Stack with thread safety.
        
        Returns:
            dict with 'approved' (bool) and 'cancelled' (bool) keys
            or None on timeout/error
        """
        import threading

        async def _do_request() -> dict[str, Any] | None:
            loop = asyncio.get_event_loop()
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(
                        self._bridge.request_approval,
                        title[:40],  # M5Stack display limit
                        body[:200],
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("M5Stack approval timeout")
                return None
            except Exception as e:
                logger.error(f"M5Stack bridge error: {e}")
                return None

        async with self._lock:
            return await _do_request()

    def is_connected(self) -> bool:
        return self._bridge.is_connected


# Global bridge instance (initialized on first use)
_bridge: ThreadSafeM5StackBridge | None = None


def get_m5stack_bridge() -> ThreadSafeM5StackBridge | None:
    """Get or create the global M5Stack bridge instance.
    
    This function now does lazy initialization - the bridge is only created
    on the first approval request, not at module import time.
    Uses M5STACK_PORT env var if set.
    """
    global _bridge
    return _bridge


def format_tool_info(tool_name: str, args: BaseModel) -> tuple[str, str]:
    """Format tool info for M5Stack display.
    
    Returns:
        (title, body) tuple
    """
    title = tool_name[:40]
    
    # Extract relevant info from args
    body_parts = [f"Tool: {tool_name}"]
    
    if hasattr(args, 'model_dump'):
        args_dict = args.model_dump()
    elif hasattr(args, '__dict__'):
        args_dict = args.__dict__
    else:
        args_dict = {}
    
    # Common patterns for mutable tools
    if 'path' in args_dict:
        path = str(args_dict['path'])
        body_parts.append(f"Path: {path[:60]}")
    
    if 'content' in args_dict:
        content = str(args_dict.get('content', ''))
        preview = content[:50] + '...' if len(content) > 50 else content
        body_parts.append(f"Content: {preview}")
    
    if 'file_path' in args_dict:
        body_parts.append(f"File: {args_dict['file_path'][:60]}")
    
    if 'command' in args_dict:
        cmd = str(args_dict['command'])
        body_parts.append(f"Command: {cmd[:60]}")
    
    body = "\n".join(body_parts[:5])  # Limit to 5 lines
    return title, body


async def m5stack_approval_callback(
    tool_name: str,
    args: BaseModel,
    tool_call_id: str,
    required_permissions: list[RequiredPermission] | None = None,
) -> tuple[ApprovalResponse, str | None]:
    """
    Approval callback that forwards to M5Stack device.
    
    This is called as part of a race with the original Textual UI callback.
    
    Returns:
        tuple of (ApprovalResponse, optional_message)
        - YES: operation approved
        - NO: operation rejected
    """
    global _bridge

    title, body = format_tool_info(tool_name, args)
    # Prefix title with session name for multi-session identification
    title = _session_mgr.format_title(title)
    title = title[:40]  # safe truncate pour M5Stack
    logger.info(f"Permission requested: {title}")

    # Preferred path: route through the owner-broker so status + approval share
    # the single persistent connection (and multi-session works).
    mgr = get_or_init_broker()
    if _broker_can_approve(mgr):
        try:
            if mgr.is_owner():
                # broker.request_approval is blocking (serial) -> off the event loop
                response = await asyncio.to_thread(
                    mgr.broker.request_approval, title, body, None
                )
            else:
                req_id = int(asyncio.get_event_loop().time() * 1000) % 1_000_000
                response = await mgr.client.request_approval(title, body, req_id)
        except Exception as e:
            logger.error(f"Broker approval error: {e}")
            response = None
    else:
        # Fallback: ephemeral bridge (no broker / device unreachable via broker).
        if _bridge is None:
            try:
                port = os.environ.get("M5STACK_PORT")
                raw_bridge = M5StackBridge(port=port, auto_connect=False)
                _bridge = ThreadSafeM5StackBridge(raw_bridge)
                if raw_bridge.is_connected:
                    logger.info(f"M5Stack port detected (fallback): {raw_bridge.port}")
                else:
                    logger.error("M5Stack auto-detect failed. Set M5STACK_PORT=COMx explicitly.")
            except Exception as e:
                logger.error(f"Failed to initialize M5Stack bridge: {e}")
                return (ApprovalResponse.NO, "M5Stack unavailable")
        if not _bridge.is_connected():
            return (ApprovalResponse.NO, "M5Stack unavailable")
        response = await _bridge.request_approval(title, body)

    if response is None:
        logger.warning("M5Stack approval timeout or error - denying")
        return (ApprovalResponse.NO, "Approval timeout - operation blocked")

    if response.get("cancelled", False):
        logger.info("Permission DENIED via M5Stack (cancelled)")
        return (
            ApprovalResponse.NO,
            "User rejected via M5Stack - provide an alternative plan",
        )

    if response.get("approved", False):
        logger.info("Permission GRANTED via M5Stack")
        return (ApprovalResponse.YES, None)

    # Default deny
    logger.info("Permission DENIED via M5Stack (unknown response)")
    return (ApprovalResponse.NO, "Operation blocked")


# -- Monkey patching --------------------------------------------------------

_original_set_approval_callback: Any = None
_patched_agent_loop = False




def patch_act_for_status():
    """Patch AgentLoop.act to observe events and push status."""
    from vibe.core.agent_loop import AgentLoop
    
    _orig_act = AgentLoop.act
    
    async def patched_act(self, msg, *args, **kwargs):
        """Wrapped act that observes events and pushes status."""
        global _status_seq
        
        # Push thinking state at start of turn
        push_status_to_device("thinking", "", 0)
        _status_seq = 0  # Reset seq for new turn
        
        try:
            async for ev in _orig_act(self, msg, *args, **kwargs):
                # Map event to status and push
                state, detail, seq = map_event_to_status(ev)
                push_status_to_device(state, detail, seq)
                yield ev
            
            # Push done state at end of turn
            push_status_to_device("done", "", _status_seq + 1)
        except Exception as e:
            push_status_to_device("error", str(e)[:40], _status_seq + 1)
            raise
    
    AgentLoop.act = patched_act
    logger.info("AgentLoop.act patched for status tracking")


def patch_agent_loop():
    """Patch AgentLoop.set_approval_callback to wrap with M5Stack race."""
    global _original_set_approval_callback, _patched_agent_loop
    
    if _patched_agent_loop:
        return
    
    from vibe.core.agent_loop import AgentLoop
    
    _original_set_approval_callback = AgentLoop.set_approval_callback
    
    def patched_set_approval_callback(self, callback):
        """Wrap the original callback to race against M5Stack."""
        original_cb = callback  # bound method -> TextualUI._approval_callback
        tui_instance = getattr(callback, "__self__", None)  # TextualUI instance or None

        async def wrapped(tool, args, tool_call_id, required_permissions):
            # Visual notification in TUI (non-blocking)
            if tui_instance is not None and hasattr(tui_instance, "notify"):
                try:
                    tui_instance.notify(
                        f"Permission pending: {tool}",
                        title="M5Stack",
                        timeout=3,
                    )
                except Exception:
                    pass  # notify may fail outside event-loop, we don't care

            # Launch original AND M5Stack in parallel
            modal_task = asyncio.create_task(
                original_cb(tool, args, tool_call_id, required_permissions)
            )
            m5_task = asyncio.create_task(
                m5stack_approval_callback(tool, args, tool_call_id, required_permissions)
            )

            try:
                done, pending = await asyncio.wait(
                    {modal_task, m5_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if m5_task in done and modal_task not in done:
                    # M5Stack button pressed first -> resolve the Future that Textual
                    # waits on in tui_instance._pending_approval, this auto-closes the modal.
                    m5_result = m5_task.result()
                    for _ in range(50):  # <= 500 ms
                        pa = getattr(tui_instance, "_pending_approval", None)
                        if pa is not None and not pa.done():
                            pa.set_result(m5_result)
                            break
                        await asyncio.sleep(0.01)
                    return await modal_task

                # Modal won -> cancel M5Stack
                m5_task.cancel()
                try:
                    await m5_task
                except (asyncio.CancelledError, Exception):
                    pass
                return modal_task.result()
            except asyncio.CancelledError:
                modal_task.cancel()
                m5_task.cancel()
                raise

        self.approval_callback = wrapped
    
    AgentLoop.set_approval_callback = patched_set_approval_callback
    logger.info("AgentLoop.set_approval_callback patched successfully")
    _patched_agent_loop = True


# -- Initialization --------------------------------------------------------

def install_hook():
    """Install the M5Stack approval hook.
    
    Call this before starting Vibe CLI.
    """
    logger.info("Installing Vibe M5Stack approval hook...")
    
    # Patch AgentLoop - this wraps all future set_approval_callback calls
    patch_agent_loop()
    
    # Patch AgentLoop.act for status tracking
    patch_act_for_status()
    
    logger.info("Hook installation complete")


# Auto-install when imported
install_hook()
