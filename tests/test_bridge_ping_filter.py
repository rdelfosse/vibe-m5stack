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
""""""Tests for M5StackBridge.request_approval ping filtering and ID matching."""

import time
import tempfile
import pytest
from pathlib import Path
from plugin.bridge import M5StackBridge


@pytest.fixture(autouse=True)
def speed_up_request_approval(monkeypatch):
    """Make request_approval fast by patching time.sleep and FileLock."""
    import time as time_module
    monkeypatch.setattr(time_module, "sleep", lambda *args, **kwargs: None)
    
    # Patch FileLock.acquire to return immediately
    from filelock import FileLock
    def instant_acquire(self, timeout=None, poll_interval=0.05):
        return True
    monkeypatch.setattr(FileLock, "acquire", instant_acquire)
    yield
    monkeypatch.undo()


class TestRequestApprovalPingFilter:
    """Tests for request_approval with ping vs response filtering."""

    def test_returns_matching_response(self, patch_serial, monkeypatch, tmp_path):
        fake = patch_serial(lines_to_emit=[
            {"type": "response", "id": 12345, "approved": True}
        ])
        lock_path = tmp_path / "m5.lock"
        monkeypatch.setattr("plugin.bridge._LOCK_PATH", Path(lock_path))
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        resp = b.request_approval("title", "body", request_id=12345)
        assert resp["approved"] is True
        assert resp["id"] == 12345

    def test_ignores_pings_before_response(self, patch_serial, monkeypatch, tmp_path):
        fake = patch_serial(lines_to_emit=[
            {"type": "ping"},
            {"type": "ping"},
            {"type": "response", "id": 99, "approved": False},
        ])
        lock_path = tmp_path / "m5.lock"
        monkeypatch.setattr("plugin.bridge._LOCK_PATH", Path(lock_path))
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        resp = b.request_approval("t", "b", request_id=99)
        assert resp["id"] == 99
        assert resp["approved"] is False

    def test_ignores_response_with_wrong_id(self, patch_serial, monkeypatch, tmp_path):
        fake = patch_serial(lines_to_emit=[
            {"type": "response", "id": 1, "approved": True},   # wrong id
            {"type": "response", "id": 42, "approved": False}, # right id
        ])
        lock_path = tmp_path / "m5.lock"
        monkeypatch.setattr("plugin.bridge._LOCK_PATH", Path(lock_path))
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        resp = b.request_approval("t", "b", request_id=42)
        assert resp["id"] == 42
        assert resp["approved"] is False

    def test_ignores_multiple_pings(self, patch_serial, monkeypatch, tmp_path):
        fake = patch_serial(lines_to_emit=[
            {"type": "ping"},
            {"type": "ping"},
            {"type": "ping"},
            {"type": "response", "id": 77, "approved": True},
        ])
        lock_path = tmp_path / "m5.lock"
        monkeypatch.setattr("plugin.bridge._LOCK_PATH", Path(lock_path))
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        resp = b.request_approval("t", "b", request_id=77)
        assert resp["id"] == 77
        assert resp["approved"] is True

    def test_returns_response_with_cancelled(self, patch_serial, monkeypatch, tmp_path):
        fake = patch_serial(lines_to_emit=[
            {"type": "response", "id": 55, "approved": False, "cancelled": True}
        ])
        lock_path = tmp_path / "m5.lock"
        monkeypatch.setattr("plugin.bridge._LOCK_PATH", Path(lock_path))
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        resp = b.request_approval("t", "b", request_id=55)
        assert resp["id"] == 55
        assert resp["approved"] is False
        assert resp["cancelled"] is True



    def test_empty_lines_handled(self, patch_serial, monkeypatch, tmp_path):
        fake = patch_serial(lines_to_emit=[
            "",
            {"type": "response", "id": 100, "approved": True},
        ])
        lock_path = tmp_path / "m5.lock"
        monkeypatch.setattr("plugin.bridge._LOCK_PATH", Path(lock_path))
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        resp = b.request_approval("t", "b", request_id=100)
        assert resp["id"] == 100
