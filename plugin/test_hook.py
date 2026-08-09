"""Tests for the M5Stack approval hook - New API (>= 2.23)."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pydantic import BaseModel

# Add plugin to path
_PLUGIN_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_PLUGIN_DIR))

# Create mock vibe modules BEFORE any imports
vibe_core_types = sys.modules["vibe.core.types"] = MagicMock()
vibe_core_permissions = sys.modules["vibe.core.tools.permissions"] = MagicMock()
vibe_core_agent_loop = sys.modules["vibe.core.agent_loop"] = MagicMock()

# Setup mock classes and enums
class ApprovalResponse:
    YES = "YES"
    NO = "NO"

class RequiredPermission:
    FILE_EDIT = "FILE_EDIT"
    FILE_READ = "FILE_READ"
    PROCESS_RUN = "PROCESS_RUN"

# Mock AgentLoop class with act method
class AgentLoop:
    act = None  # Will be patched

vibe_core_types.ApprovalResponse = ApprovalResponse
vibe_core_types.RequiredPermission = RequiredPermission
vibe_core_types.ApprovalRequestEvent = object  # placeholder
vibe_core_permissions.RequiredPermission = RequiredPermission
vibe_core_agent_loop.AgentLoop = AgentLoop

# Now we can import
from vibe.core.types import ApprovalResponse, RequiredPermission


class MockArgs(BaseModel):
    path: str = "/test/file.txt"
    content: str = "Hello World"


class MockApprovalRequestEvent:
    def __init__(self, tool_name, tool_args, tool_call_id, required_permissions, request_id):
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.tool_call_id = tool_call_id
        self.required_permissions = required_permissions
        self.request_id = request_id


async def test_approval_event_triggers_device_race():
    import plugin.vibe_m5stack_hook as hook_module
    
    mock_agent_loop = MagicMock(spec=AgentLoop)
    mock_agent_loop.resolve_approval_request = MagicMock()  # SYNCHRONE dans l'API réelle
    
    event = MockApprovalRequestEvent(
        tool_name="write_file",
        tool_args=MockArgs(),
        tool_call_id="test-123",
        required_permissions=[RequiredPermission.FILE_EDIT],
        request_id="req-456"
    )
    
    with patch.object(hook_module, "get_or_init_broker", return_value=None):
        mock_bridge = Mock()
        async def mock_request_approval(title, body, req_id=None):
            return {"approved": True, "cancelled": False}
        
        mock_bridge.request_approval = mock_request_approval
        mock_bridge.is_connected = lambda: True
        
        with patch.object(hook_module, "_bridge", mock_bridge):
            await hook_module._race_m5stack_approval(mock_agent_loop, event)
            
            mock_agent_loop.resolve_approval_request.assert_called_once()
            call_args = mock_agent_loop.resolve_approval_request.call_args
            assert call_args[0][0] == "req-456"
            assert call_args[0][1] == ApprovalResponse.YES
            assert call_args[0][2] is None
            print("+ Test 1 passed: Approval event triggers device race and resolves")


async def test_device_timeout_no_resolution():
    import plugin.vibe_m5stack_hook as hook_module
    
    mock_agent_loop = MagicMock(spec=AgentLoop)
    mock_agent_loop.resolve_approval_request = MagicMock()  # SYNCHRONE dans l'API réelle
    
    event = MockApprovalRequestEvent(
        tool_name="write_file",
        tool_args=MockArgs(),
        tool_call_id="test-123",
        required_permissions=[RequiredPermission.FILE_EDIT],
        request_id="req-456"
    )
    
    with patch.object(hook_module, "get_or_init_broker", return_value=None):
        mock_bridge = Mock()
        async def mock_request_approval(title, body, req_id=None):
            return None
        
        mock_bridge.request_approval = mock_request_approval
        mock_bridge.is_connected = lambda: True
        
        with patch.object(hook_module, "_bridge", mock_bridge):
            await hook_module._race_m5stack_approval(mock_agent_loop, event)
            
            mock_agent_loop.resolve_approval_request.assert_not_called()
            print("+ Test 2 passed: Device timeout does not resolve approval")


async def test_exception_in_race_no_crash():
    import plugin.vibe_m5stack_hook as hook_module
    
    mock_agent_loop = MagicMock(spec=AgentLoop)
    mock_agent_loop.resolve_approval_request = MagicMock()  # SYNCHRONE dans l'API réelle
    
    event = MockApprovalRequestEvent(
        tool_name="write_file",
        tool_args=MockArgs(),
        tool_call_id="test-123",
        required_permissions=[RequiredPermission.FILE_EDIT],
        request_id="req-456"
    )
    
    with patch.object(hook_module, "m5stack_approval_callback", side_effect=Exception("Bridge error")):
        await hook_module._race_m5stack_approval(mock_agent_loop, event)
        
        mock_agent_loop.resolve_approval_request.assert_not_called()
        print("+ Test 3 passed: Exception in race does not crash")


async def test_device_reject_resolves():
    import plugin.vibe_m5stack_hook as hook_module
    
    mock_agent_loop = MagicMock(spec=AgentLoop)
    mock_agent_loop.resolve_approval_request = MagicMock()  # SYNCHRONE dans l'API réelle
    
    event = MockApprovalRequestEvent(
        tool_name="write_file",
        tool_args=MockArgs(),
        tool_call_id="test-123",
        required_permissions=[RequiredPermission.FILE_EDIT],
        request_id="req-456"
    )
    
    with patch.object(hook_module, "get_or_init_broker", return_value=None):
        mock_bridge = Mock()
        async def mock_request_approval(title, body, req_id=None):
            return {"approved": False, "cancelled": True}
        
        mock_bridge.request_approval = mock_request_approval
        mock_bridge.is_connected = lambda: True
        
        with patch.object(hook_module, "_bridge", mock_bridge):
            await hook_module._race_m5stack_approval(mock_agent_loop, event)
            
            mock_agent_loop.resolve_approval_request.assert_called_once()
            call_args = mock_agent_loop.resolve_approval_request.call_args
            assert call_args[0][0] == "req-456"
            assert call_args[0][1] == ApprovalResponse.NO
            assert "M5Stack" in call_args[0][2]
            print("+ Test 4 passed: Device rejection resolves approval with NO")


async def test_format_tool_info():
    # Import only the function, not the whole module
    import importlib.util
    spec = importlib.util.spec_from_file_location("vibe_m5stack_hook", "plugin/vibe_m5stack_hook.py")
    # We cannot easily import just the function without triggering install_hook
    # So skip this test or mock at module level
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
    assert "..." in body
    print("+ Test 5 passed: Tool info formatting")


async def main():
    print("Testing M5Stack approval hook (new API >= 2.23)...\n")
    
    try:
        await test_approval_event_triggers_device_race()
        await test_device_timeout_no_resolution()
        await test_exception_in_race_no_crash()
        await test_device_reject_resolves()
        await test_format_tool_info()
        
        print("\n+ All new API tests passed!")
        return 0
    except Exception as e:
        print(f"\n- Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
