"""Tests for the M5Stack approval hook - New API (>= 2.23).

mistral-vibe >= 2.23 est une dépendance dure du plugin : ces tests utilisent
les vrais modules vibe. Pas de stub sys.modules au niveau module : c'est
fragile (l'ordre de collecte pytest déciderait qui voit le mock) et inutile
depuis que vibe est installable.
"""

import asyncio
import sys
from unittest.mock import MagicMock, patch
from pydantic import BaseModel

import plugin.vibe_m5stack_hook as hook_module
from plugin.vibe_m5stack_hook import format_tool_info, _race_m5stack_approval
from vibe.core.types import ApprovalResponse
from vibe.core.tools.permissions import PermissionScope, RequiredPermission


def _fake_permission():
    return RequiredPermission(
        scope=PermissionScope.FILE_PATTERN,
        invocation_pattern="*",
        session_pattern="*",
        label="file edit",
    )


class MockArgs(BaseModel):
    path: str = "/test/file.txt"
    content: str = "Hello World"


def _make_event():
    return MagicMock(
        tool_name="write_file",
        tool_args=MockArgs(),
        tool_call_id="test-123",
        required_permissions=[_fake_permission()],
        request_id="req-456",
    )


def _make_loop():
    loop = MagicMock()
    # SYNCHRONE dans l'API réelle
    loop.resolve_approval_request = MagicMock()
    return loop


async def test_approval_event_triggers_device_race():
    agent_loop = _make_loop()

    with patch.object(hook_module, "get_or_init_broker", return_value=None):
        mock_bridge = MagicMock()
        mock_bridge.is_connected = lambda: True

        async def mock_request_approval(title, body, req_id=None):
            return {"approved": True, "cancelled": False}

        mock_bridge.request_approval = mock_request_approval

        with patch.object(hook_module, "_bridge", mock_bridge):
            await _race_m5stack_approval(agent_loop, _make_event())

            agent_loop.resolve_approval_request.assert_called_once()
            call_args = agent_loop.resolve_approval_request.call_args
            assert call_args[0][0] == "req-456"
            assert call_args[0][1] == ApprovalResponse.YES
            assert call_args[0][2] is None


async def test_device_timeout_no_resolution():
    agent_loop = _make_loop()

    with patch.object(hook_module, "get_or_init_broker", return_value=None):
        mock_bridge = MagicMock()
        mock_bridge.is_connected = lambda: True

        async def mock_request_approval(title, body, req_id=None):
            return None

        mock_bridge.request_approval = mock_request_approval

        with patch.object(hook_module, "_bridge", mock_bridge):
            await _race_m5stack_approval(agent_loop, _make_event())

            agent_loop.resolve_approval_request.assert_not_called()


async def test_exception_in_race_no_crash():
    agent_loop = _make_loop()

    with patch.object(
        hook_module, "m5stack_approval_callback", side_effect=Exception("Bridge error")
    ):
        await _race_m5stack_approval(agent_loop, _make_event())

        agent_loop.resolve_approval_request.assert_not_called()


async def test_device_reject_resolves():
    agent_loop = _make_loop()

    with patch.object(hook_module, "get_or_init_broker", return_value=None):
        mock_bridge = MagicMock()
        mock_bridge.is_connected = lambda: True

        async def mock_request_approval(title, body, req_id=None):
            return {"approved": False, "cancelled": True}

        mock_bridge.request_approval = mock_request_approval

        with patch.object(hook_module, "_bridge", mock_bridge):
            await _race_m5stack_approval(agent_loop, _make_event())

            agent_loop.resolve_approval_request.assert_called_once()
            call_args = agent_loop.resolve_approval_request.call_args
            assert call_args[0][0] == "req-456"
            assert call_args[0][1] == ApprovalResponse.NO
            assert "M5Stack" in call_args[0][2]


async def test_format_tool_info():
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
