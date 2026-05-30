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
Test script for the M5Stack approval hook.

This script tests the hook without requiring a physical M5Stack device.
It simulates M5Stack responses.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, patch
from pydantic import BaseModel

# Add plugin to path
_PLUGIN_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_PLUGIN_DIR))

from vibe.core.types import ApprovalResponse
from vibe.core.tools.permissions import RequiredPermission


class MockArgs(BaseModel):
    path: str = "/test/file.txt"
    content: str = "Hello World"


async def test_callback_with_mock_bridge():
    """Test callback with mocked bridge responses."""
    from plugin.vibe_m5stack_hook import m5stack_approval_callback
    
    # Create a mock bridge with async request_approval
    mock_bridge = Mock()
    
    async def mock_request_approval_approved(title, body, timeout=30.0):
        return {"approved": True, "cancelled": False}
    
    async def mock_request_approval_rejected(title, body, timeout=30.0):
        return {"approved": False, "cancelled": True}
    
    # Patch the global _bridge in the module
    import plugin.vibe_m5stack_hook as hook_module

    # Force the ephemeral _bridge fallback path (no owner-broker / no hardware).
    with patch.object(hook_module, "get_or_init_broker", return_value=None):
        # Test approval
        hook_module._bridge = Mock()
        hook_module._bridge.request_approval = mock_request_approval_approved
        hook_module._bridge.is_connected = lambda: True

        result = await m5stack_approval_callback(
            tool_name="write_file",
            args=MockArgs(),
            tool_call_id="test-123",
            required_permissions=None
        )

        assert result[0] == ApprovalResponse.YES, f"Expected YES, got {result[0]}"
        assert result[1] is None
        print("+ Test 1 passed: Callback approves with mock bridge")

        # Test rejection
        hook_module._bridge.request_approval = mock_request_approval_rejected

        result = await m5stack_approval_callback(
            tool_name="write_file",
            args=MockArgs(),
            tool_call_id="test-123",
            required_permissions=None
        )

        assert result[0] == ApprovalResponse.NO, f"Expected NO, got {result[0]}"
        assert "M5Stack" in result[1]
        print("+ Test 2 passed: Callback rejects with mock bridge")

        # Test timeout (bridge returns None)
        async def mock_request_timeout(title, body, timeout=30.0):
            return None

        hook_module._bridge.request_approval = mock_request_timeout

        result = await m5stack_approval_callback(
            tool_name="write_file",
            args=MockArgs(),
            tool_call_id="test-123",
            required_permissions=None
        )

        assert result[0] == ApprovalResponse.NO, f"Expected NO, got {result[0]}"
        assert "timeout" in result[1].lower()
        print("+ Test 3 passed: Callback handles timeout")


async def test_callback_without_bridge():
    """Test callback when bridge initialization fails."""
    from plugin.vibe_m5stack_hook import m5stack_approval_callback
    import plugin.vibe_m5stack_hook as hook_module
    
    # Set _bridge to None to trigger initialization
    hook_module._bridge = None

    # Force ephemeral fallback (no broker), and make bridge construction fail.
    with patch.object(hook_module, "get_or_init_broker", return_value=None), \
         patch('plugin.vibe_m5stack_hook.M5StackBridge', side_effect=Exception("Port not found")):
        result = await m5stack_approval_callback(
            tool_name="write_file",
            args=MockArgs(),
            tool_call_id="test-123",
            required_permissions=None
        )

    assert result[0] == ApprovalResponse.NO, f"Expected NO, got {result[0]}"
    # On a construction error the callback denies with an "unavailable" message.
    assert "unavailable" in result[1].lower()
    print("+ Test 4 passed: Callback handles bridge initialization error")


async def test_patching():
    """Test that the monkey patching works."""
    from vibe.core.agent_loop import AgentLoop
    
    # Import hook to apply patches
    import plugin.vibe_m5stack_hook
    
    # Verify that set_approval_callback has been patched
    # The original should be stored in _original_set_approval_callback
    assert plugin.vibe_m5stack_hook._original_set_approval_callback is not None
    assert AgentLoop.set_approval_callback is not plugin.vibe_m5stack_hook._original_set_approval_callback
    print("+ Test 5 passed: Monkey patching applied")


async def test_format_tool_info():
    """Test the tool info formatting."""
    from plugin.vibe_m5stack_hook import format_tool_info
    
    class TestArgs(BaseModel):
        path: str = "/very/long/path/to/file.txt"
        content: str = "A" * 100
        other: str = "value"
    
    title, body = format_tool_info("write_file", TestArgs())
    
    assert "write_file" in title
    assert len(title) <= 40
    assert "Path:" in body
    assert "Content:" in body
    assert "..." in body  # Should truncate long content
    print("+ Test 6 passed: Tool info formatting")


async def main():
    """Run all tests."""
    print("Testing M5Stack approval hook...\n")
    
    try:
        await test_callback_with_mock_bridge()
        await test_callback_without_bridge()
        await test_patching()
        await test_format_tool_info()
        
        print("\n+ All tests passed!")
        return 0
    except Exception as e:
        print(f"\n- Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
