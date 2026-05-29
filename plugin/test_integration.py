"""
Integration test for the M5Stack approval hook.

Tests that the hook properly patches AgentLoop and VibeApp.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# Add plugin to path
_PLUGIN_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_PLUGIN_DIR))

# Import the hook BEFORE importing vibe modules
import plugin.vibe_m5stack_hook as hook_module

from vibe.core.agent_loop import AgentLoop
from vibe.cli.textual_ui.app import VibeApp
from vibe.core.types import ApprovalResponse


async def test_agent_loop_patching():
    """Test that AgentLoop.set_approval_callback is properly patched."""
    
    # Verify the patch is in place
    assert hook_module._original_set_approval_callback is not None
    assert AgentLoop.set_approval_callback is not hook_module._original_set_approval_callback
    print("+ AgentLoop.set_approval_callback is patched")


async def test_vibe_app_patching():
    """Test that VibeApp.on_mount is properly patched."""
    
    # Verify the patch is in place
    assert hook_module._patched_vibe_app is True
    print("+ VibeApp.on_mount is patched")


async def test_callback_with_mock_bridge():
    """Test that the callback works with a mock bridge."""
    from pydantic import BaseModel
    
    callback = hook_module.m5stack_approval_callback
    
    class MockArgs(BaseModel):
        path: str = "/test/file.txt"
    
    # Create a real ThreadSafeM5StackBridge with mocked internal bridge
    raw_bridge = Mock()
    raw_bridge.is_connected = True
    
    # The request_approval method must be SYNC (not async) because
    # ThreadSafeM5StackBridge uses asyncio.to_thread which expects sync functions
    def mock_request_approval(title, body, timeout=30.0):
        return {"approved": True, "cancelled": False}
    
    raw_bridge.request_approval = mock_request_approval

    hook_module._bridge = hook_module.ThreadSafeM5StackBridge(raw_bridge)

    # Force the ephemeral _bridge fallback (no owner-broker / no hardware).
    with patch.object(hook_module, "get_or_init_broker", return_value=None):
        # Call the callback
        result = await callback(
            tool_name="write_file",
            args=MockArgs(),
            tool_call_id="test-123",
            required_permissions=None
        )

        assert result[0] == ApprovalResponse.YES
        assert result[1] is None
        print("+ Callback works with mock bridge (approval)")

        # Test rejection
        def mock_request_reject(title, body, timeout=30.0):
            return {"approved": False, "cancelled": True}

        raw_bridge.request_approval = mock_request_reject

        result = await callback(
            tool_name="write_file",
            args=MockArgs(),
            tool_call_id="test-123",
            required_permissions=None
        )

        assert result[0] == ApprovalResponse.NO
        assert "M5Stack" in result[1]
        print("+ Callback works with mock bridge (rejection)")


async def test_callback_error_handling():
    """Test that the callback handles errors properly."""
    from pydantic import BaseModel
    
    callback = hook_module.m5stack_approval_callback
    
    class MockArgs(BaseModel):
        path: str = "/test/file.txt"
    
    # Set bridge to None to trigger initialization
    hook_module._bridge = None
    
    # Mock M5StackBridge to raise error
    with patch('plugin.vibe_m5stack_hook.M5StackBridge', side_effect=Exception("Test error")):
        result = await callback(
            tool_name="write_file",
            args=MockArgs(),
            tool_call_id="test-123",
            required_permissions=None
        )
    
    assert result[0] == ApprovalResponse.NO
    assert "error" in result[1].lower()
    print("+ Callback handles bridge errors properly")


async def main():
    """Run all integration tests."""
    print("Running integration tests...\n")
    
    try:
        await test_agent_loop_patching()
        await test_vibe_app_patching()
        await test_callback_with_mock_bridge()
        await test_callback_error_handling()
        
        print("\n+ All integration tests passed!")
        return 0
    except Exception as e:
        print(f"\n- Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
