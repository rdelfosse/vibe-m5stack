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
""""""Tests for M5StackBridge._probe_port."""

import time
import pytest
from plugin.bridge import M5StackBridge


@pytest.fixture(autouse=True)
def speed_up_probe(monkeypatch):
    """Make _probe_port fast by patching time.sleep."""
    import time as time_module
    monkeypatch.setattr(time_module, "sleep", lambda *args, **kwargs: None)
    yield
    monkeypatch.undo()


class TestProbePort:
    """Tests for _probe_port method."""

    def test_probe_returns_true_when_ping_arrives(self, patch_serial):
        fake = patch_serial(lines_to_emit=[{"type": "ping"}])
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        assert b._probe_port("COM_TEST", timeout=0.1) is True

    def test_probe_returns_false_when_silent(self, patch_serial):
        fake = patch_serial(lines_to_emit=[])
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        assert b._probe_port("COM_TEST", timeout=0.05) is False

    def test_probe_returns_false_on_garbage(self, patch_serial):
        fake = patch_serial(lines_to_emit=["not json at all", "still not json"])
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        assert b._probe_port("COM_TEST", timeout=0.1) is False

    def test_probe_returns_false_on_invalid_json(self, patch_serial):
        fake = patch_serial(lines_to_emit=["{\"invalid: json}", "{no quotes}"])
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        assert b._probe_port("COM_TEST", timeout=0.1) is False

    def test_probe_returns_false_on_json_without_type(self, patch_serial):
        fake = patch_serial(lines_to_emit=[{"foo": "bar"}, {"id": 123}])
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        assert b._probe_port("COM_TEST", timeout=0.1) is False

    def test_probe_returns_true_on_approval_message(self, patch_serial):
        """Approval messages also have type field, should match."""
        fake = patch_serial(lines_to_emit=[{"type": "approval", "id": 1, "title": "test"}])
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        assert b._probe_port("COM_TEST", timeout=0.1) is True

    def test_probe_returns_false_on_open_exception(self, patch_serial):
        fake = patch_serial(raise_on_open=True)
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        assert b._probe_port("COM_TEST", timeout=0.1) is False

    def test_probe_returns_true_on_response_message(self, patch_serial):
        """Response messages also have type field, should match."""
        fake = patch_serial(lines_to_emit=[{"type": "response", "id": 1, "approved": True}])
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        assert b._probe_port("COM_TEST", timeout=0.1) is True

    def test_probe_returns_true_on_credit_info_message(self, patch_serial):
        """Credit info messages have type field, should match."""
        fake = patch_serial(lines_to_emit=[{"type": "credit_info", "percent": 50}])
        b = M5StackBridge(port="COM_TEST", auto_connect=False)
        assert b._probe_port("COM_TEST", timeout=0.1) is True
