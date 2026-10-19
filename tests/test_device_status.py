# Vibe M5Stack - M5Stack integration for Mistral Vibe CLI
# Copyright 2026 Romain Delfosse
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests des statuts device (v0.7): mapper notifications -> etats firmware,
DeviceSession (approbation persistante), et poussage de statuts par le proxy.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
import threading
from pathlib import Path

import pytest

from plugin.app_server_client import DECISION_APPROVE, ApprovalRequest
from plugin.app_server_proxy import (
    AppServerProxy,
    EnvApprover,
    status_from_notification,
)
from plugin.device_session import DeviceSession

REPO_ROOT = Path(__file__).resolve().parents[1]
FAKE_SERVER = REPO_ROOT / "tests" / "fake_app_server.py"


# ---------------------------------------------------------------------------
# Mapper


def test_mapper_turn_lifecycle():
    assert status_from_notification("turn/started", {}) == ("thinking", "", "reasoning")
    assert status_from_notification("turn/completed", {"turn": {"error": None}}) == ("done", "", "")
    assert status_from_notification(
        "turn/completed", {"turn": {"error": "api timeout"}}
    ) == ("error", "api timeout", "")


def test_mapper_entries():
    reasoning = {"entry": {"type": "reasoning", "text": "je reflechis"}}
    assert status_from_notification("history/entryAdded", reasoning) == ("thinking", "", "reasoning")
    effect = {"entry": {"type": "effect", "title": "file_system.write_file"}}
    assert status_from_notification("history/entryAdded", effect) == (
        "thinking",
        "file_system.write_file",
        "tool_exec",
    )
    message = {"entry": {"role": "assistant", "type": "message"}}
    assert status_from_notification("history/entryAdded", message) == ("thinking", "", "streaming")


def test_mapper_ignored():
    assert status_from_notification("session/updated", {"patch": []}) is None
    assert status_from_notification("history/entryAdded", {"entry": {"type": "other"}}) is None


# ---------------------------------------------------------------------------
# DeviceSession avec fake bridge


class FakeBridge:
    def __init__(self, approval_response=None) -> None:
        self.approval_response = approval_response
        self.statuses = []
        self.connected = False

    def connect(self, port=None):
        self.connected = True
        return True

    def close(self):
        self.connected = False

    def send_status(self, state, detail="", seq=0, activity=""):
        self.statuses.append({"state": state, "detail": detail, "seq": seq, "activity": activity})
        return True

    def request_approval_persistent(self, title, body, request_id=None):
        if self.approval_response is None:
            return None  # simule un timeout: DeviceSession doit renvoyer
        return self.approval_response


def make_approval() -> ApprovalRequest:
    return ApprovalRequest(
        callback_id="cb-1", session_id="s", tool="file_system.write_file"
    )


async def test_device_session_decide_approve():
    bridge = FakeBridge(approval_response={"approved": True})
    session = DeviceSession(bridge=bridge, port="COM_FAKE")
    assert session.start() is True
    decision = await session.decide(make_approval(), threading.Event())
    assert decision == "approve"
    session.stop()


async def test_device_session_resends_until_button():
    """Timeout persistant: la demande est renvoyee, pas abandonnee."""
    bridge = FakeBridge(approval_response=None)
    bridge.request_approval_persistent = None  # type: ignore[assignment]

    calls = []

    def persistent(title, body, request_id=None):
        calls.append(request_id)
        if len(calls) >= 2:
            return {"approved": True}
        return None

    bridge.request_approval_persistent = persistent  # type: ignore[method-assign]
    session = DeviceSession(bridge=bridge, port="COM_FAKE")
    session.APPROVAL_RESEND_S = 0.05  # renvoi rapide pour le test
    assert session.start() is True
    decision = await session.decide(make_approval(), threading.Event())
    assert decision == "approve"
    assert len(calls) == 2
    assert calls[0] == calls[1]  # meme id: l'eccran reste affiche
    session.stop()


async def test_device_session_cancelled():
    bridge = FakeBridge(approval_response=None)
    session = DeviceSession(bridge=bridge, port="COM_FAKE")
    session.APPROVAL_RESEND_S = 10.0
    assert session.start() is True
    cancel = threading.Event()
    cancel.set()
    decision = await session.decide(make_approval(), cancel)
    assert decision is None
    session.stop()


def test_device_session_absent():
    class NoPortBridge(FakeBridge):
        def connect(self, port=None):
            return False

    session = DeviceSession(bridge=NoPortBridge(), port=None)
    session.port = None
    # resolve_port serait appele: on l'evite en forcant un port inexistant
    session.port = "COM_INEXISTANT"
    assert session.start() is False


# ---------------------------------------------------------------------------
# Proxy in-process: statuts pousses au device


class FakeDevice:
    def __init__(self) -> None:
        self.statuses = []

    def push_status(self, state, detail="", activity=""):
        self.statuses.append((state, detail, activity))

    def stop(self):
        pass


async def test_proxy_pushes_statuses(tmp_path):
    """Chaine complete in-process: le proxy pousse les statuts au device."""
    incoming: asyncio.Queue[bytes] = asyncio.Queue()
    outgoing: asyncio.Queue[bytes] = asyncio.Queue()

    async def left_read() -> bytes:
        return await incoming.get()

    async def left_write(line: bytes) -> None:
        await outgoing.put(line)

    async def send(message: dict) -> None:
        await incoming.put(json.dumps(message, separators=(",", ":")).encode() + b"\n")

    async def receive(timeout: float = 10.0) -> dict:
        line = await asyncio.wait_for(outgoing.get(), timeout=timeout)
        return json.loads(line)

    async def expect(predicate, timeout: float = 10.0) -> dict:
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            message = await receive(timeout=max(remaining, 0.1))
            if predicate(message):
                return message

    device = FakeDevice()
    proxy = AppServerProxy(approver=EnvApprover(DECISION_APPROVE), device=device)
    fake_command = [sys.executable, str(FAKE_SERVER)]
    task = asyncio.get_running_loop().create_task(
        proxy.run(fake_command, left_read=left_read, left_write=left_write)
    )

    try:
        await send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"clientInfo": {"name": "test", "version": "0", "entrypoint": "unknown"},
                               "capabilities": {"callbackKinds": ["approval"]}}})
        response = await expect(lambda m: m.get("id") == 1)
        assert "result" in response
        await send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        await send({"jsonrpc": "2.0", "id": 2, "method": "session/start",
                    "params": {"agentConfig": {"cwd": str(tmp_path), "trustWorkspace": True}}})
        await expect(lambda m: m.get("id") == 2)
        await send({"jsonrpc": "2.0", "id": 3, "method": "session/turn/enqueue",
                    "params": {"sessionId": "s-fake",
                               "entries": [{"role": "user", "content": [{"type": "text", "text": "go"}]}]}})
        await expect(lambda m: m.get("id") == 3)

        # le callback/call arrive du proxy: la "TUI" (test) ack puis se tait
        callback_call = await expect(lambda m: m.get("method") == "callback/call")
        await send({"jsonrpc": "2.0", "id": callback_call["id"],
                    "result": {"callbackId": callback_call["params"]["callback"]["callbackId"]}})

        await expect(lambda m: m.get("method") == "turn/completed")

        # le push "done" part en to_thread apres la notification: on attend
        # qu'il atteigne le device avant d'annuler le proxy.
        for _ in range(100):
            if ("done", "", "") in device.statuses:
                break
            await asyncio.sleep(0.05)

        states = [s[0] for s in device.statuses]
        assert ("thinking", "", "reasoning") in device.statuses
        assert ("thinking", "file_system.write_file", "tool_exec") in device.statuses
        assert ("waiting", "file_system.write_file", "") in device.statuses
        assert ("done", "", "") in device.statuses
        assert states[-1] == "done"
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, TimeoutError):
            pass
