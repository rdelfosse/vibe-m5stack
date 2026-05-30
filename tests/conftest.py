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
"""import json
import time
import pytest
from pathlib import Path





class FakeSerial:
    """Mock de serial.Serial pour les tests bridge.

    Émet `lines_to_emit` (list of str ou dict JSON-encodable) à la lecture.
    Capture ce qui est écrit dans `.written` pour assertion.
    """
    def __init__(self, lines_to_emit=None, raise_on_open=False):
        self._lines = list(lines_to_emit or [])
        self._buffer = b""
        self._raise = raise_on_open
        self.written: list[bytes] = []
        self.closed = False

    def __enter__(self):
        if self._raise:
            raise Exception("mock serial open failed")
        for line in self._lines:
            if isinstance(line, dict):
                line = json.dumps(line)
            self._buffer += line.encode() + b"\n"
        return self

    def __exit__(self, *args):
        self.closed = True

    @property
    def in_waiting(self):
        return len(self._buffer)

    def read(self, n=1):
        chunk = self._buffer[:n]
        self._buffer = self._buffer[n:]
        return chunk

    def write(self, data: bytes):
        self.written.append(data)
        return len(data)

    def flush(self):
        pass


@pytest.fixture
def patch_serial(monkeypatch):
    """Helper pour patcher serial.Serial dans plugin.bridge.

    Usage :
        def test_x(patch_serial):
            fake = patch_serial(lines_to_emit=[{"type":"ping"}])
            # ... appeler le code testé ...
            assert fake.written == [b'...']
    """
    def _factory(**kwargs):
        fake = FakeSerial(**kwargs)
        monkeypatch.setattr("plugin.bridge.serial.Serial", lambda *a, **kw: fake)
        return fake
    return _factory
