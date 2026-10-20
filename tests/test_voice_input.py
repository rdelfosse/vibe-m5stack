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
"""Tests de la voix entrante v0.7: refus vocal (deny_latest), capture de
session et injection d'un tour dicte.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path

from plugin.app_server_client import ApprovalRequest
from plugin.app_server_proxy import (
    AppServerProxy,
    ApprovalRouter,
    EnvApprover,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FAKE_SERVER = REPO_ROOT / "tests" / "fake_app_server.py"


class BlockingApprover(EnvApprover):
    """Approuveur qui attend: laisse l'approbation en attente (pending)."""

    async def decide(self, approval, cancel):
        cancel.wait(5.0)
        return None


def make_approval(cid: str) -> ApprovalRequest:
    return ApprovalRequest(callback_id=cid, session_id="s", tool="t", choices=["approve", "deny"])


def test_transcriber_override_bypasses_legacy_gate(monkeypatch):
    """Régression: la barriere transcription_available() du legacy (cle via
    vibe 2.x, indisponible sous Vibe 3) ne doit pas bloquer le chemin REST."""
    import base64
    import time
    from unittest.mock import MagicMock

    from plugin.voice_handler import VoiceHandler

    # VoiceInput touche PortAudio (absent sur les runners CI) : mock du
    # singleton — le chemin override ne l'utilise de toute facon pas.
    monkeypatch.setattr("plugin.voice_handler.get_voice_input", lambda: MagicMock())

    class LegacyIndisponible:
        def transcription_available(self):
            return False  # c'est le bug: import vibe 2.x en echec

        def availability_detail(self):
            return "sounddevice=False mistralai=True api_key=NON"

        def transcribe_sync(self, wav):
            raise AssertionError("le chemin legacy ne doit pas etre pris")

    handler = VoiceHandler()
    handler._voice_input = LegacyIndisponible()  # type: ignore[assignment]
    handler.set_transcriber(lambda wav: "crée le fichier test voix")
    injectes: list[str] = []
    handler.set_inject_callback(injectes.append)
    handler.set_send_voice_ack_callback(lambda state, text="": None)

    from plugin.tts_handler import wav_to_ulaw_16k
    from tests.test_tts_speaker import make_wav

    ulaw = wav_to_ulaw_16k(make_wav(samples=4096))  # ~256 ms

    handler.handle_voice_message(
        {"type": "voice", "action": "start", "mode": "prompt", "id": 0, "mic": "device"}
    )
    for i in range(0, len(ulaw), 256):
        handler.handle_audio_chunk({"type": "audio", "data": base64.b64encode(ulaw[i:i + 256]).decode()})
    handler.handle_audio_end({"type": "audio_end", "total": len(ulaw), "ms": len(ulaw) // 16})

    for _ in range(100):  # le thread de transcription est asynchrone
        if injectes:
            break
        time.sleep(0.05)
    assert injectes == ["crée le fichier test voix"]


async def test_router_deny_latest():
    sent: list[dict] = []

    async def send_result(params: dict) -> dict:
        sent.append(params)
        return {"accepted": True}

    router = ApprovalRouter(BlockingApprover(None), send_result)
    await router.offer(make_approval("cb-1"))

    ok = await router.deny_latest("pas sans revue")
    assert ok is True
    assert len(sent) == 1
    output = sent[0]["result"]["output"]
    assert output["decision"]["type"] == "deny"
    assert "pas sans revue" in output["feedback"]
    assert "cb-1" in router.answered

    # plus rien en attente: le deuxieme refus vocal est ignore
    assert await router.deny_latest("encore") is False


async def test_proxy_voice_turn(tmp_path, monkeypatch):
    """Dictee -> session capturee au session/start -> turn/enqueue injecte."""
    record = tmp_path / "record.jsonl"
    monkeypatch.setenv("FAKE_SERVER_RECORD", str(record))  # le fake server herite l'env du proxy

    def read_events():
        if not record.exists():
            return []
        return [json.loads(l) for l in record.read_text(encoding="utf-8").splitlines() if l]

    incoming: asyncio.Queue[bytes] = asyncio.Queue()
    outgoing: asyncio.Queue[bytes] = asyncio.Queue()

    async def left_read() -> bytes:
        return await incoming.get()

    async def left_write(line: bytes) -> None:
        await outgoing.put(line)

    async def send(message: dict) -> None:
        await incoming.put(json.dumps(message, separators=(",", ":")).encode() + b"\n")

    async def expect(predicate, timeout: float = 10.0) -> dict:
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            line = await asyncio.wait_for(outgoing.get(), timeout=max(remaining, 0.1))
            message = json.loads(line)
            if predicate(message):
                return message

    proxy = AppServerProxy(approver=EnvApprover(None))  # device silencieux
    task = asyncio.get_running_loop().create_task(
        proxy.run([sys.executable, str(FAKE_SERVER)], left_read=left_read, left_write=left_write)
    )

    try:
        await send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"clientInfo": {"name": "test", "version": "0", "entrypoint": "unknown"},
                               "capabilities": {"callbackKinds": ["approval"]}}})
        await expect(lambda m: m.get("id") == 1)
        await send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        await send({"jsonrpc": "2.0", "id": 2, "method": "session/start",
                    "params": {"agentConfig": {"cwd": str(tmp_path), "trustWorkspace": True}}})
        await expect(lambda m: m.get("id") == 2)

        # le proxy a capture l'id de session au passage
        assert proxy.session_id == "s-fake"

        # une dictee arrive depuis le thread de transcription
        proxy.queue_voice_turn("dis bonjour par la voix du M5Stack")
        # ack du callback/call declenche par le tour simule, fin du tour
        callback_call = await expect(lambda m: m.get("method") == "callback/call")
        await send({"jsonrpc": "2.0", "id": callback_call["id"],
                    "result": {"callbackId": callback_call["params"]["callback"]["callbackId"]}})
        await expect(lambda m: m.get("method") == "turn/completed")

        enqueues = [e for e in read_events() if e["event"] == "turn_enqueue"]
        assert "dis bonjour par la voix du M5Stack" in [e["text"] for e in enqueues]
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, TimeoutError):
            pass
