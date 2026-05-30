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
Tests for status tracking functionality.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Any

# Mock vibe core modules before importing
import sys

mock_vibe_core = MagicMock()
mock_vibe_core.agent_loop = MagicMock()
mock_vibe_core.types = MagicMock()
mock_vibe_core.tools = MagicMock()
mock_vibe_core.tools.permissions = MagicMock()

# Define mock event classes
class MockEvent:
    pass

class UserMessageEvent(MockEvent):
    pass

class AssistantEvent(MockEvent):
    def __init__(self, tool_name=""):
        self.tool_name = tool_name

class ReasoningEvent(MockEvent):
    pass

class ToolCallEvent(MockEvent):
    def __init__(self, tool_name=""):
        self.tool_name = tool_name

class ToolResultEvent(MockEvent):
    pass

class ToolStreamEvent(MockEvent):
    pass

class WaitingForInputEvent(MockEvent):
    pass

class CompactStartEvent(MockEvent):
    pass

class CompactEndEvent(MockEvent):
    pass

class PlanReviewRequestedEvent(MockEvent):
    pass

class SessionTitleUpdatedEvent(MockEvent):
    pass

# Set up mocks
mock_vibe_core.types.UserMessageEvent = UserMessageEvent
mock_vibe_core.types.AssistantEvent = AssistantEvent
mock_vibe_core.types.ReasoningEvent = ReasoningEvent
mock_vibe_core.types.ToolCallEvent = ToolCallEvent
mock_vibe_core.types.ToolResultEvent = ToolResultEvent
mock_vibe_core.types.ToolStreamEvent = ToolStreamEvent
mock_vibe_core.types.WaitingForInputEvent = WaitingForInputEvent
mock_vibe_core.types.CompactStartEvent = CompactStartEvent
mock_vibe_core.types.CompactEndEvent = CompactEndEvent
mock_vibe_core.types.PlanReviewRequestedEvent = PlanReviewRequestedEvent
mock_vibe_core.types.SessionTitleUpdatedEvent = SessionTitleUpdatedEvent

sys.modules['vibe.core'] = mock_vibe_core
sys.modules['vibe.core.agent_loop'] = mock_vibe_core.agent_loop
sys.modules['vibe.core.types'] = mock_vibe_core.types
sys.modules['vibe.core.tools'] = mock_vibe_core.tools
sys.modules['vibe.core.tools.permissions'] = mock_vibe_core.tools.permissions

# Now we can import the hook module
from plugin.vibe_m5stack_hook import map_event_to_status


class TestMapEventToStatus:
    """Tests for map_event_to_status function."""
    
    def setup_method(self):
        """Reset global seq counter before each test."""
        import plugin.vibe_m5stack_hook as hook_module
        hook_module._status_seq = 0
        hook_module._last_status_activity = ""
    
    def test_tool_call_event_maps_to_thinking(self):
        event = ToolCallEvent(tool_name="write_file")
        state, detail, seq, activity = map_event_to_status(event)
        assert state == "thinking"
        assert detail == "write_file"
        assert seq == 1
        assert activity == "tool_exec"
    
    def test_assistant_event_maps_to_thinking(self):
        event = AssistantEvent()
        state, detail, seq, activity = map_event_to_status(event)
        assert state == "thinking"
        assert detail == ""
        assert seq == 1
        assert activity == "streaming"
    
    def test_reasoning_event_maps_to_thinking(self):
        event = ReasoningEvent()
        state, detail, seq, activity = map_event_to_status(event)
        assert state == "thinking"
        assert detail == ""
        assert seq == 1
        assert activity == "reasoning"
    
    def test_waiting_for_input_event_maps_to_waiting(self):
        event = WaitingForInputEvent()
        state, detail, seq, activity = map_event_to_status(event)
        assert state == "waiting"
        assert detail == "awaiting input"
        assert seq == 0  # No seq increment
        assert activity == ""
    
    def test_compact_start_event_maps_to_thinking(self):
        event = CompactStartEvent()
        state, detail, seq, activity = map_event_to_status(event)
        assert state == "thinking"
        assert detail == "compacting"
        assert seq == 1
        assert activity == "reasoning"
    
    def test_unknown_event_maps_to_thinking(self):
        event = UserMessageEvent()
        state, detail, seq, activity = map_event_to_status(event)
        assert state == "thinking"
        assert seq == 0
        assert activity == "reasoning"


class TestStatusSequence:
    """Tests for sequence number incrementing."""
    
    def setup_method(self):
        import plugin.vibe_m5stack_hook as hook_module
        hook_module._status_seq = 0
    
    def test_seq_increments_on_multiple_events(self):
        events = [
            ToolCallEvent("write_file"),
            ToolCallEvent("read_file"),
            AssistantEvent(),
        ]
        seqs = []
        for event in events:
            _, _, seq, _ = map_event_to_status(event)
            seqs.append(seq)
        assert seqs == [1, 2, 3]
    
    def test_waiting_event_does_not_increment_seq(self):
        events = [
            ToolCallEvent("write_file"),
            WaitingForInputEvent(),
            ToolCallEvent("read_file"),
        ]
        seqs = []
        for event in events:
            _, _, seq, _ = map_event_to_status(event)
            seqs.append(seq)
        assert seqs == [1, 1, 2]


class TestActivityClassification:
    """Tests for thinking activity classification."""
    
    def setup_method(self):
        import plugin.vibe_m5stack_hook as hook_module
        hook_module._status_seq = 0
        hook_module._last_status_activity = ""
    
    def test_reading_tools_classified_correctly(self):
        """Test that reading tools are classified as 'reading' activity."""
        for tool_name in ["read_file", "read", "grep", "search", "web_fetch", "fetch"]:
            event = ToolCallEvent(tool_name=tool_name)
            _, _, _, activity = map_event_to_status(event)
            assert activity == "reading", f"Tool {tool_name} should be 'reading', got {activity}"
    
    def test_exec_tools_classified_correctly(self):
        """Test that execution tools are classified as 'tool_exec' activity."""
        for tool_name in ["bash", "write_file", "search_replace", "edit"]:
            event = ToolCallEvent(tool_name=tool_name)
            _, _, _, activity = map_event_to_status(event)
            assert activity == "tool_exec", f"Tool {tool_name} should be 'tool_exec', got {activity}"
    
    def test_unknown_tool_defaults_to_tool_exec(self):
        """Test that unknown tools default to 'tool_exec' activity."""
        event = ToolCallEvent(tool_name="unknown_tool_xyz")
        _, _, _, activity = map_event_to_status(event)
        assert activity == "tool_exec"
    
    def test_tool_without_name_defaults_to_tool_exec(self):
        """Test that tools without name default to 'tool_exec' activity."""
        event = ToolCallEvent(tool_name="")
        _, _, _, activity = map_event_to_status(event)
        assert activity == "tool_exec"


@pytest.mark.asyncio
async def test_act_patch():
    """Test that AgentLoop.act is properly patched."""
    from unittest.mock import patch
    
    # Import after async context
    from plugin.vibe_m5stack_hook import patch_act_for_status
    from vibe.core.agent_loop import AgentLoop
    
    # Save original
    original_act = AgentLoop.act
    
    # Patch
    patch_act_for_status()
    
    # Verify it was patched
    assert AgentLoop.act != original_act
    
    # Restore
    AgentLoop.act = original_act
