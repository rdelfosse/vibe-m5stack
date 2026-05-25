"""
Vibe M5Stack Hook - Intercepts tool permission requests and forwards to M5Stack device.

This module monkey-patches Vibe's AgentLoop to replace the approval callback
with one that forwards permission requests to the M5Stack device for physical
button approval (A=Allow, B=Reject, C=Cancel).

Usage:
    This module is automatically loaded by the vibe-m5stack wrapper script.
    It should NOT be imported directly.

Environment:
    - M5Stack must be connected via USB (typically COM3 on Windows)
    - Requires pyserial to be installed
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# Setup logging early
logging.basicConfig(
    level=logging.INFO,
    format="[M5Stack Hook] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

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
    
    This replaces Vibe's default approval callback to require physical
    button press on M5Stack for mutable operations.
    
    Returns:
        tuple of (ApprovalResponse, optional_message)
        - YES: operation approved
        - NO: operation rejected
    """
    global _bridge
    
    # Lazy initialization - try to connect on first use
    if _bridge is None:
        try:
            raw_bridge = M5StackBridge(auto_connect=True)
            _bridge = ThreadSafeM5StackBridge(raw_bridge)
            if not _bridge.is_connected:
                logger.warning("M5Stack not connected - will block operations until connected")
        except Exception as e:
            logger.error(f"Failed to initialize M5Stack bridge: {e}")
            return (ApprovalResponse.NO, f"M5Stack bridge error: {e}")
    
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
_patched_vibe_app = False


def patch_agent_loop():
    """Patch AgentLoop.set_approval_callback to use our M5Stack callback."""
    global _original_set_approval_callback
    
    from vibe.core.agent_loop import AgentLoop
    
    if _original_set_approval_callback is not None:
        return  # Already patched
    
    _original_set_approval_callback = AgentLoop.set_approval_callback
    
    def patched_set_approval_callback(self, callback):
        """Intercept and replace with M5Stack callback."""
        logger.info("Intercepted set_approval_callback - installing M5Stack callback")
        # Replace the callback with ours
        self.approval_callback = m5stack_approval_callback
    
    AgentLoop.set_approval_callback = patched_set_approval_callback
    logger.info("AgentLoop.set_approval_callback patched successfully")


def patch_vibe_app():
    """Patch VibeApp to use our callback directly."""
    global _patched_vibe_app
    
    if _patched_vibe_app:
        return
    
    try:
        from vibe.cli.textual_ui.app import VibeApp
    except ImportError:
        logger.warning("VibeApp not found - will try AgentLoop patch only")
        return
    
    original_on_mount = VibeApp.on_mount
    
    async def patched_on_mount(self):
        """Patch VibeApp.on_mount to replace approval callback."""
        # First, let original on_mount run (it sets up the agent_loop)
        await original_on_mount(self)
        
        # Now replace the approval callback
        if hasattr(self, 'agent_loop') and self.agent_loop is not None:
            logger.info("Replacing VibeApp approval callback with M5Stack callback")
            self.agent_loop.set_approval_callback(m5stack_approval_callback)
        else:
            logger.warning("agent_loop not available in VibeApp - patch may have failed")
    
    VibeApp.on_mount = patched_on_mount
    _patched_vibe_app = True
    logger.info("VibeApp.on_mount patched successfully")


# -- Initialization --------------------------------------------------------

def install_hook():
    """Install the M5Stack approval hook.
    
    Call this before starting Vibe CLI.
    """
    logger.info("Installing Vibe M5Stack approval hook...")
    
    # Initialize bridge
    get_m5stack_bridge()
    
    # Patch both AgentLoop and VibeApp for maximum compatibility
    patch_agent_loop()
    patch_vibe_app()
    
    logger.info("Hook installation complete")


# Auto-install when imported
install_hook()
