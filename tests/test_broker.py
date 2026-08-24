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

    def test_heartbeat_before_first_push_sends_full_status(self):
        """Régression : aggregated_activity n'était pas initialisé dans
        __init__ — le premier heartbeat (avant tout push_status) levait une
        AttributeError avalée en ERROR log, et rien n'allait au device.
        """
        self.broker._send_aggregated_status()
        self.mock_bridge.send.assert_called_once()
        msg = self.mock_bridge.send.call_args[0][0]
        assert msg["type"] == "status"
        assert msg["state"] == "done"
        assert msg["seq"] == 0
        # L'activité n'est embarquée que pour l'état thinking
        assert "activity" not in msg

    def test_thinking_status_includes_activity(self):
        self.broker.push_status("thinking", "edit foo.py", 3, "tool_exec")
        self.mock_bridge.send.reset_mock()
        self.broker._send_aggregated_status()
        msg = self.mock_bridge.send.call_args[0][0]
        assert msg["activity"] == "tool_exec"
    
    def test_multiple_status_aggregation(self):
        self.broker.push_status("thinking", "session1", 1)
        self.broker.push_status("waiting", "session2", 2)
        # WAITING should override THINKING
        assert self.broker.aggregated_state == "waiting"
    
    def test_close_stops_broker(self):
        self.broker.start()
        self.broker.close()
        assert not self.broker.running


def test_client_proxy_connect_reads_broker_file(monkeypatch):
    """ClientProxy.connect lit le broker file et joint le serveur owner.

    Régression CI : l'ancien test écrivait un faux broker file pointant le
    port mort 12345 et assertait connect() — ça ne passe que si quelque
    chose écoute déjà sur 12345 (jamais le cas sur les runners). Ici on
    démarre un vrai OwnerBroker : start() écrit lui-même le fichier avec
    son port vivant, le client n'a plus qu'à le lire.
    """
    import plugin.broker as broker_module

    with tempfile.TemporaryDirectory() as tmp_dir:
        monkeypatch.setattr(
            broker_module, "BROKER_FILE_PATH", Path(tmp_dir) / "m5stack.broker"
        )
        broker = OwnerBroker(MagicMock(), "owner_session")
        try:
            port, pid = broker.start()

            client = ClientProxy("test_client")
            assert client.connect()
            assert client.owner_port == port
            assert client.owner_pid == pid
        finally:
            broker.close()


def test_client_proxy_connect_fails_without_broker_file(monkeypatch):
    """Sans broker file, connect() retourne False proprement."""
    import plugin.broker as broker_module

    with tempfile.TemporaryDirectory() as tmp_dir:
        monkeypatch.setattr(
            broker_module, "BROKER_FILE_PATH", Path(tmp_dir) / "absent.broker"
        )
        client = ClientProxy("test_client")
        assert client.connect() is False
        assert client.owner_port is None


class TestBrokerManager:
    """Tests for BrokerManager election logic."""
    
    def setup_method(self, method):
        # Use temporary directory for lock files to avoid conflicts with real sessions
        import plugin.broker as broker_module
        self._tmp_dir = tempfile.mkdtemp()
        self._orig_owner_lock = broker_module.OWNER_LOCK_PATH
        self._orig_broker_file = broker_module.BROKER_FILE_PATH
        
        # Patch module-level constants to use temp directory
        broker_module.OWNER_LOCK_PATH = Path(self._tmp_dir) / "m5stack.owner.lock"
        broker_module.BROKER_FILE_PATH = Path(self._tmp_dir) / "m5stack.broker"
        
        # Clean up any existing files in temp dir
        for p in [broker_module.OWNER_LOCK_PATH, broker_module.BROKER_FILE_PATH]:
            if p.exists():
                p.unlink(missing_ok=True)
    
    def teardown_method(self, method):
        # Restore original constants and clean up temp directory
        import plugin.broker as broker_module
        import shutil
        broker_module.OWNER_LOCK_PATH = self._orig_owner_lock
        broker_module.BROKER_FILE_PATH = self._orig_broker_file
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
    
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
