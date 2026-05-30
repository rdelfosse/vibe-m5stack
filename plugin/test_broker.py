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
Tests for the owner-broker multi-session coordination.
"""

import asyncio
import json
import os
import pytest
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

# Mock the bridge before importing
import sys
mock_bridge_module = MagicMock()
mock_bridge_class = MagicMock()
mock_bridge_instance = MagicMock()
mock_bridge_instance.send.return_value = True
mock_bridge_instance.is_connected.return_value = True
mock_bridge_class.return_value = mock_bridge_instance
mock_bridge_module.M5StackBridge = mock_bridge_class

sys.modules['plugin.bridge'] = mock_bridge_module

from plugin.broker import (
    OwnerBroker,
    ClientProxy,
    BrokerManager,
    AgentState,
    aggregate_states,
)


class TestAggregateStates:
    """Tests for state aggregation logic."""
    
    def test_empty_states_returns_done(self):
        assert aggregate_states({}) == AgentState.DONE
    
    def test_waiting_has_highest_priority(self):
        states = {"sess1": AgentState.THINKING, "sess2": AgentState.WAITING}
        assert aggregate_states(states) == AgentState.WAITING
    
    def test_thinking_beats_done(self):
        states = {"sess1": AgentState.DONE, "sess2": AgentState.THINKING}
        assert aggregate_states(states) == AgentState.THINKING
    
    def test_multiple_sessions_waiting(self):
        states = {
            "sess1": AgentState.WAITING,
            "sess2": AgentState.THINKING,
            "sess3": AgentState.DONE,
        }
        assert aggregate_states(states) == AgentState.WAITING


class TestOwnerBroker:
    """Tests for OwnerBroker functionality."""
    
    def setup_method(self):
        self.mock_bridge = MagicMock()
        self.mock_bridge.send.return_value = True
        self.broker = OwnerBroker(self.mock_bridge, "test_session")
    
    def test_start_creates_server(self):
        port, pid = self.broker.start()
        assert port > 0
        assert pid > 0
        assert self.broker.server_port == port
    
    def test_push_status_updates_aggregated_state(self):
        self.broker.push_status("thinking", "test", 1, "session1")
        assert self.broker.aggregated_state == "thinking"
        assert self.broker.aggregated_detail == "test"
        assert self.broker.aggregated_seq == 1
    
    def test_multiple_status_aggregation(self):
        self.broker.push_status("thinking", "session1", 1)
        self.broker.push_status("waiting", "session2", 2)
        # WAITING should override THINKING
        assert self.broker.aggregated_state == "waiting"
    
    def test_close_stops_broker(self):
        self.broker.start()
        self.broker.close()
        assert not self.broker.running


@pytest.mark.asyncio
async def test_client_proxy_send_message():
    """Test ClientProxy message sending."""
    # Create a mock broker file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.broker') as f:
        broker_info = {"port": 12345, "pid": os.getpid()}
        json.dump(broker_info, f)
        temp_broker_file = f.name
    
    # Mock the read
    with patch('plugin.broker.BROKER_FILE_PATH', Path(temp_broker_file)):
        client = ClientProxy("test_client")
        assert client.connect()  # Should read broker file
    
    # Cleanup
    os.unlink(temp_broker_file)


class TestBrokerManager:
    """Tests for BrokerManager election logic."""
    
    def setup_method(self):
        # Clean up any existing lock files
        lock_path = Path.home() / ".vibe" / "m5stack.owner.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        if lock_path.exists():
            lock_path.unlink()
        
        broker_path = Path.home() / ".vibe" / "m5stack.broker"
        if broker_path.exists():
            broker_path.unlink()
    
    def test_first_session_becomes_owner(self):
        mock_bridge = MagicMock()
        manager = BrokerManager(mock_bridge, "session1")
        assert manager.initialize()
        assert manager.is_owner()
        manager.close()
    
    def test_second_session_becomes_client(self):
        mock_bridge = MagicMock()
        
        # First session becomes owner
        manager1 = BrokerManager(mock_bridge, "session1")
        manager1.initialize()
        assert manager1.is_owner()
        
        # Second session should become client
        manager2 = BrokerManager(mock_bridge, "session2")
        assert manager2.initialize()
        assert manager2.is_client()
        
        manager1.close()
        manager2.close()
    
    def test_owner_0_forces_client_mode(self):
        os.environ['M5STACK_OWNER'] = '0'
        mock_bridge = MagicMock()
        manager = BrokerManager(mock_bridge, "session1")
        try:
            assert manager.initialize()
            assert manager.is_client()
        finally:
            del os.environ['M5STACK_OWNER']
            manager.close()
