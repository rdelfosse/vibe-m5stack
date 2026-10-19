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
"""Fake app server pour tests: protocole minimal, sans LLM ni materiel.

Simule le cycle: initialize -> session/start -> session/turn/enqueue ->
callback/call (approbation) -> callback/result -> turn/completed, et
journalise les decisions recues dans FAKE_SERVER_RECORD (JSONL).

Lance comme script autonome: python tests/fake_app_server.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin.app_server_client import JsonRpcPeer  # noqa: E402

SESSION_ID = "s-fake"


async def read_stdin() -> bytes:
    return await asyncio.to_thread(sys.stdin.buffer.read1, 65536)


async def write_stdout(line: bytes) -> None:
    await asyncio.to_thread(sys.stdout.buffer.write, line)
    await asyncio.to_thread(sys.stdout.buffer.flush)


def record(entry: dict) -> None:
    path = os.environ.get("FAKE_SERVER_RECORD")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
        fh.flush()


async def serve() -> None:
    peer = JsonRpcPeer(read_stdin, write_stdout, label="fake-server", request_timeout=60.0)
    completed = asyncio.Event()

    async def on_notification(method: str, params: dict) -> None:
        record({"event": "notification", "method": method})

    peer.on_notification = on_notification
    peer.serve()

    async def simulated_turn() -> None:
        """Un tour factice qui demande une approbation puis se termine."""
        await asyncio.sleep(0.1)
        await peer.notify("turn/started", {"sessionId": SESSION_ID, "eventId": 10})
        await peer.notify(
            "history/entryAdded",
            {
                "sessionId": SESSION_ID,
                "eventId": 11,
                "entry": {"type": "reasoning", "text": "reflexion factice"},
            },
        )
        await peer.notify(
            "history/entryAdded",
            {
                "sessionId": SESSION_ID,
                "eventId": 12,
                "entry": {"type": "effect", "title": "file_system.write_file"},
            },
        )
        callback = {
            "callbackId": "cb-fake-1",
            "sessionId": SESSION_ID,
            "detail": {
                "kind": "approval",
                "effect": {"toolName": "file_system.write_file"},
                "choices": ["approve", "deny"],
                "reason": None,
            },
        }
        ack = await peer.request("callback/call", {"callback": callback})
        record({"event": "callback_ack", "ack": ack.get("result")})
        await asyncio.sleep(0.1)
        await peer.notify("turn/completed", {"sessionId": SESSION_ID, "eventId": 13})
        completed.set()

    async def on_request(rid: int, method: str, params: dict) -> None:
        if method == "initialize":
            await peer.respond(rid, {"serverInfo": {"name": "fake-app-server", "version": "test"}})
        elif method == "session/start":
            await peer.respond(
                rid,
                {"state": {"session": {"id": SESSION_ID}}, "lastEventId": 1},
            )
        elif method == "session/turn/enqueue":
            await peer.respond(rid, {"queueItemId": "q-fake-1"})
            asyncio.get_running_loop().create_task(simulated_turn())
        elif method == "callback/result":
            result = params.get("result") or {}
            output = result.get("output") or {}
            decision = (output.get("decision") or {}).get("type")
            record({"event": "callback_result", "callbackId": result.get("callbackId"), "decision": decision})
            await peer.respond(rid, {"accepted": True, "lastEventId": 5})
        elif method == "session/read":
            await peer.respond(
                rid,
                {"state": {"session": {"id": SESSION_ID}, "history": []}, "lastEventId": 6},
            )
        else:
            await peer.respond_error(rid, -32601, f"method not found: {method}")

    peer.on_request = on_request

    await completed.wait()
    await asyncio.sleep(0.2)  # laisse filer les derniers messages
    await peer.close()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
