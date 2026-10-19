#!/usr/bin/env python3
# Vibe M5Stack - Spike: app-server companion client
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
"""Spike v0.7.0 : client compagnon minimal du app server Mistral Vibe 3.x.

Valide, sans materiel et sans importer le package ``vibe`` :
  1. handshake JSON-RPC (initialize + callbackKinds: ["approval"]) ;
  2. ouverture de session (session/start, agent "ask") ;
  3. injection d'un tour (session/turn/enqueue) ;
  4. interception du callback d'approbation (callback/call) et reponse
     (callback/result) -- cote M5Stack ce sera le bouton A/B/C.

Usage (python du venv mistral-vibe, l'app server est son voisin) :
    <venv-mistral-vibe>/Scripts/python.exe tools/spike_app_server_client.py [approve|deny] [prompt]
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

DECISION = sys.argv[1] if len(sys.argv) > 1 else "deny"
if DECISION not in {"approve", "deny"}:
    sys.exit(f"decision invalide: {DECISION} (approve|deny)")

DEFAULT_PROMPT = (
    "Cree le fichier cible.txt dans le repertoire de travail avec le contenu "
    "'spike m5stack'. Utilise l'outil write_file. Reponds juste OK ensuite."
)
PROMPT = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PROMPT


def find_app_server() -> Path:
    candidate = Path(sys.executable).resolve().parent / "vibe-app-server.exe"
    if sys.platform != "win32":
        candidate = candidate.with_name("vibe-app-server")
    if not candidate.exists():
        sys.exit(f"vibe-app-server introuvable pres de {sys.executable}")
    return candidate


class Rpc:
    """JSON-RPC 2.0 minimaliste : lignes JSON compactes sur stdio."""

    def __init__(self, proc: asyncio.subprocess.Process, trace: Path) -> None:
        self.proc = proc
        self.trace = trace
        self.next_id = 1
        self.pending: dict[int, asyncio.Future[dict]] = {}
        self.approvals: list[dict] = []
        self.turn_done = asyncio.Event()

    async def send(self, message: dict) -> None:
        line = json.dumps(message, separators=(",", ":")) + "\n"
        with self.trace.open("a", encoding="utf-8") as fh:
            fh.write("-> " + line)
        assert self.proc.stdin
        self.proc.stdin.write(line.encode())
        await self.proc.stdin.drain()

    async def request(self, method: str, params: dict) -> dict:
        rid = self.next_id
        self.next_id += 1
        fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        await self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        return await asyncio.wait_for(fut, timeout=30)

    async def notify(self, method: str, params: dict) -> None:
        await self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def log(self, msg: str) -> None:
        print(f"[spike {time.strftime('%H:%M:%S')}] {msg}", flush=True)

    async def answer_approval(self, request_id: int, callback: dict) -> None:
        cid = callback["callbackId"]
        detail = callback.get("detail", {})
        effect = detail.get("effect", {})
        self.log(
            f"APPROBATION recue: tool={effect.get('toolName')} "
            f"choices={detail.get('choices')} reason={detail.get('reason')}"
        )
        self.approvals.append(callback)
        # 1) ack de la requete callback/call
        await self.send({"jsonrpc": "2.0", "id": request_id, "result": {"callbackId": cid}})
        # 2) decision, comme le ferait le bouton A (approve) ou B (deny)
        decision = {"type": DECISION}
        await self.request(
            "callback/result",
            {
                "sessionId": callback["sessionId"],
                "result": {
                    "callbackId": cid,
                    "output": {
                        "type": "approval",
                        "decision": decision,
                        "feedback": f"m5stack-spike:{DECISION}",
                    },
                },
            },
        )
        self.log(f"decision envoyee: {DECISION}")


async def handle_frame(rpc: Rpc, raw: bytes) -> None:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return
    with rpc.trace.open("a", encoding="utf-8") as fh:
        fh.write("<- " + raw.decode(errors="replace"))
    if "id" in message and ("result" in message or "error" in message):
        fut = rpc.pending.get(message["id"])
        if fut and not fut.done():
            fut.set_result(message)
    elif "id" in message and "method" in message:
        if message["method"] == "callback/call":
            # tache separee : answer_approval attend la reponse a sa propre
            # requete, que seule la boucle de lecture peut livrer.
            asyncio.create_task(
                rpc.answer_approval(message["id"], message["params"]["callback"])
            )
        else:
            rpc.log(f"requete serveur ignoree: {message['method']}")
            await rpc.send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
    elif "method" in message:
        method = message["method"]
        if method == "turn/completed":
            rpc.log("notification: turn/completed")
            rpc.turn_done.set()
        elif method == "turn/started":
            rpc.log("notification: turn/started")
        elif method in {"session/updated"}:
            pass  # bruit frequent
        else:
            rpc.log(f"notification: {method}")


async def read_loop(rpc: Rpc, proc: asyncio.subprocess.Process) -> None:
    """Lecture par tampon : les notifications de session depassent 64 KiB,
    la limite par defaut de StreamReader.readline()."""
    assert proc.stdout
    buffer = b""
    while True:
        chunk = await proc.stdout.read(65536)
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            raw, buffer = buffer.split(b"\n", 1)
            if raw:
                await handle_frame(rpc, raw)


async def main() -> None:
    if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    workdir = Path(tempfile.mkdtemp(prefix="m5stack-spike-"))
    trace = workdir / "trace.jsonl"
    trace.write_text("", encoding="utf-8")
    app_server = find_app_server()
    proc = await asyncio.create_subprocess_exec(
        str(app_server),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    rpc = Rpc(proc, trace)
    assert proc.stderr
    async def drain_stderr() -> None:
        with (workdir / "app_server_stderr.log").open("wb") as fh:
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    break
                fh.write(chunk)

    async def watchdog() -> None:
        await asyncio.sleep(240)
        rpc.log("TIMEOUT global")
        proc.kill()

    asyncio.create_task(drain_stderr())
    asyncio.create_task(watchdog())
    reader = asyncio.create_task(read_loop(rpc, proc))

    rpc.log(f"app server: {app_server}")
    rpc.log(f"workdir: {workdir} | decision: {DECISION}")

    init = await rpc.request(
        "initialize",
        {
            "clientInfo": {
                "name": "vibe-m5stack-spike",
                "version": "0.7.0-spike",
                "entrypoint": "unknown",
            },
            "capabilities": {"callbackKinds": ["approval"]},
        },
    )
    if "error" in init:
        sys.exit(f"initialize: {init['error']}")
    rpc.log(f"initialize OK: server={init['result']['serverInfo']}")
    await rpc.notify("initialized", {})

    start = await rpc.request(
        "session/start",
        {
            "agentConfig": {
                "cwd": str(workdir),
                "agent": "ask",
                "autoApprove": False,
                "trustWorkspace": True,
            },
            "historyLimit": 50,
        },
    )
    if "error" in start:
        with (workdir / "session_start_error.json").open("w", encoding="utf-8") as fh:
            json.dump(start["error"], fh, indent=2)
        sys.exit(f"session/start: {start['error'].get('message')}")
    state = start["result"]["state"]
    session_id = state["session"]["id"]
    rpc.log(f"session ouverte: {session_id} (titre: {state['session'].get('title')!r})")

    enq = await rpc.request(
        "session/turn/enqueue",
        {
            "sessionId": session_id,
            "entries": [{"role": "user", "content": [{"type": "text", "text": PROMPT}]}],
        },
    )
    if "error" in enq:
        sys.exit(f"session/turn/enqueue: {enq['error']}")
    rpc.log(f"tour enfile: {enq['result']}")

    # attend la fin du tour (le callback d'approbation est traite par read_loop)
    try:
        await asyncio.wait_for(rpc.turn_done.wait(), timeout=180)
    except TimeoutError:
        rpc.log("pas de turn/completed en 180s")
    await asyncio.sleep(1)
    rpc.log(f"returncode app server: {proc.returncode}")

    if proc.returncode is None:
        try:
            read = await asyncio.wait_for(
                rpc.request(
                    "session/read",
                    {"sessionId": session_id, "history": {"limit": 30}, "turns": {"limit": 3}},
                ),
                timeout=10,
            )
        except TimeoutError:
            read = None
            rpc.log("session/read sans reponse")
        if read and "error" not in read:
            with (workdir / "session_state.json").open("w", encoding="utf-8") as fh:
                json.dump(read["result"], fh, indent=2)
            for entry in read["result"].get("state", {}).get("history") or []:
                role = entry.get("role")
                if role in {"assistant", "user"}:
                    for block in entry.get("content") or []:
                        text = block.get("text") or block.get("thinking") or ""
                        if block.get("type") in {"text", "thinking"} and text:
                            rpc.log(f"{role}: {text[:200]}")

    cible = workdir / "cible.txt"
    rpc.log(f"approbations recues: {len(rpc.approvals)}")
    rpc.log(f"fichier cible.txt present: {cible.exists()}")
    rpc.log(f"trace complete: {trace}")
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except TimeoutError:
        proc.kill()


if __name__ == "__main__":
    asyncio.run(main())
