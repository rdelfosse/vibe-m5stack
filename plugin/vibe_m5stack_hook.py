"""
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
from vibe.core.types import ApprovalResponse
from vibe.core.tools.permissions import RequiredPermission


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
    
    # Lazy initialization - try to connect on first use
    if _bridge is None:
        try:
            # Use M5STACK_PORT env var if set
            port = os.environ.get("M5STACK_PORT")
            raw_bridge = M5StackBridge(port=port, auto_connect=True)
            _bridge = ThreadSafeM5StackBridge(raw_bridge)
            if raw_bridge.is_connected:
                logger.info(f"M5Stack bridge ready on port {raw_bridge.port}")
            else:
                logger.error("M5Stack auto-detect failed. Set M5STACK_PORT=COMx explicitly.")
        except Exception as e:
            logger.error(f"Failed to initialize M5Stack bridge: {e}")
            return (ApprovalResponse.NO, "M5Stack unavailable")
    
    # Short-circuit: if not connected, return immediately so the race lets the
    # Textual modal win and the user falls back to it.
    if not _bridge.is_connected():
        return (ApprovalResponse.NO, "M5Stack unavailable")
    
    bridge = _bridge
    
    title, body = format_tool_info(tool_name, args)
    logger.info(f"Permission requested: {title}")

    # Request approval from M5Stack
    response = await bridge.request_approval(title, body)
    
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
    
    logger.info("Hook installation complete")


# Auto-install when imported
install_hook()
