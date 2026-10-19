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
"""Client compagnon du Mistral Vibe app server (protocole public, Vibe 3.x).

Bibliotheque autonome: aucun import du package ``vibe``, uniquement le
protocole JSON-RPC documente par le code serveur (vibe/app_server). Validee
E2E par tools/spike_app_server_client.py.

Lecons du spike integrees ici:
  - lecture par tampon: les notifications de session depassent 64 KiB, la
    limite par defaut de StreamReader.readline() ne suffit pas;
  - les reponses aux requetes doivent etre livrees par une boucle de lecture
    distincte du code qui emet les requetes (deadlock sinon).
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

DECISION_APPROVE = "approve"
DECISION_APPROVE_SESSION = "approve_for_session"
DECISION_APPROVE_PERMANENT = "approve_permanently"
DECISION_DENY = "deny"
DECISION_CANCEL = "cancel_turn"

#: Decisions comprises par ApprovalCallbackOutput (vibe/app_server/models.py).
KNOWN_DECISIONS = {
    DECISION_APPROVE,
    DECISION_APPROVE_SESSION,
    DECISION_APPROVE_PERMANENT,
    DECISION_DENY,
    DECISION_CANCEL,
}


@dataclass
class ApprovalRequest:
    """Demande d'approbation recue via callback/call."""

    callback_id: str
    session_id: str
    tool: str
    choices: list[str] = field(default_factory=list)
    reason: str | None = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_callback(cls, callback: dict) -> "ApprovalRequest":
        detail = callback.get("detail") or {}
        effect = detail.get("effect") or {}
        return cls(
            callback_id=callback.get("callbackId", ""),
            session_id=callback.get("sessionId", ""),
            tool=str(effect.get("toolName") or "?"),
            choices=list(detail.get("choices") or []),
            reason=detail.get("reason"),
            raw=callback,
        )

    @property
    def title(self) -> str:
        return f"[m5stack] {self.tool}"

    @property
    def body(self) -> str:
        extra = f" — {self.reason}" if self.reason else ""
        return f"Approbation demandee pour {self.tool}{extra}"


class AppServerProtocolError(RuntimeError):
    pass


class JsonRpcPeer:
    """Pair JSON-RPC 2.0 sur trames ligne par ligne (JSON compact + \\n).

    Le transport est abstrait: deux callables asynchrones suffisent. Les
    trames sont lues par tampon (chunks de 64 KiB) puis decoupees sur \\n.
    """

    def __init__(
        self,
        read_chunk: Callable[[], Awaitable[bytes]],
        write_line: Callable[[bytes], Awaitable[None]],
        *,
        label: str = "rpc",
        request_timeout: float = 30.0,
    ) -> None:
        self._read_chunk = read_chunk
        self._write_line = write_line
        self.label = label
        self.request_timeout = request_timeout
        self.next_id = 1
        self.pending: dict[int, asyncio.Future[dict]] = {}
        self.on_request: Callable[[int, str, dict], Awaitable[None]] | None = None
        self.on_notification: Callable[[str, dict], Awaitable[None]] | None = None
        self.on_closed: Callable[[], None] | None = None
        self._closed = False
        self._serve_task: asyncio.Task[None] | None = None

    # -- emission ---------------------------------------------------------

    async def send(self, message: dict) -> None:
        if self._closed:
            raise AppServerProtocolError(f"{self.label}: transport ferme")
        line = json.dumps(message, separators=(",", ":")).encode() + b"\n"
        await self._write_line(line)

    async def request(self, method: str, params: dict) -> dict:
        rid = self.next_id
        self.next_id += 1
        fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        try:
            await self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            return await asyncio.wait_for(fut, timeout=self.request_timeout)
        finally:
            self.pending.pop(rid, None)

    async def notify(self, method: str, params: dict) -> None:
        await self.send({"jsonrpc": "2.0", "method": method, "params": params})

    async def respond(self, request_id: int, result: dict) -> None:
        await self.send({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def respond_error(self, request_id: int, code: int, message: str) -> None:
        await self.send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    def serve(self) -> asyncio.Task[None]:
        """Demarre la boucle de lecture; a appeler une seule fois."""
        self._serve_task = asyncio.get_running_loop().create_task(self._serve())
        return self._serve_task

    async def close(self) -> None:
        self._closed = True
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(AppServerProtocolError(f"{self.label}: transport ferme"))
        self.pending.clear()

    # -- reception --------------------------------------------------------

    async def _serve(self) -> None:
        buffer = b""
        while True:
            try:
                chunk = await self._read_chunk()
            except Exception:
                break
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                if raw:
                    try:
                        await self._dispatch(json.loads(raw))
                    except Exception as exc:  # noqa: BLE001 - la boucle ne doit pas mourir
                        print(f"[{self.label}] frame non traitee: {exc}", file=sys.stderr, flush=True)
        self._closed = True
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(AppServerProtocolError(f"{self.label}: EOF"))
        self.pending.clear()
        if self.on_closed:
            self.on_closed()

    async def _dispatch(self, message: dict) -> None:
        if "id" in message and ("result" in message or "error" in message):
            fut = self.pending.get(message["id"])
            if fut and not fut.done():
                fut.set_result(message)
        elif "id" in message and "method" in message:
            if self.on_request:
                await self.on_request(message["id"], message["method"], message.get("params") or {})
        elif "method" in message:
            if self.on_notification:
                await self.on_notification(message["method"], message.get("params") or {})


def _stream_transport(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> tuple[Callable[[], Awaitable[bytes]], Callable[[bytes], Awaitable[None]]]:
    async def read_chunk() -> bytes:
        return await reader.read(65536)

    async def write_line(line: bytes) -> None:
        writer.write(line)
        await writer.drain()

    return read_chunk, write_line


class AppServerClient:
    """Client compagnon d'un app server lance en processus enfant.

    Exemple::

        client = AppServerClient(app_server_path)
        await client.start()
        await client.initialize()
        await client.session_start(cwd=..., agent="ask")
        await client.turn_enqueue("fais ceci")
        ...
        await client.close()
    """

    def __init__(
        self,
        app_server: str | Path | list[str],
        *,
        client_name: str = "vibe-m5stack",
        callback_kinds: tuple[str, ...] = ("approval",),
        on_approval: Callable[[ApprovalRequest], Awaitable[str | None]] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        if isinstance(app_server, (str, Path)):
            self.command = [str(app_server)]
        else:
            self.command = list(app_server)
        self.client_name = client_name
        self.callback_kinds = list(callback_kinds)
        self.on_approval = on_approval
        self.env = env
        self.proc: asyncio.subprocess.Process | None = None
        self.peer: JsonRpcPeer | None = None
        self.session_id: str | None = None

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.env,
        )
        assert self.proc.stdout is not None
        assert self.proc.stdin is not None
        read_chunk, write_line = _stream_transport(self.proc.stdout, self.proc.stdin)
        self.peer = JsonRpcPeer(read_chunk, write_line, label="app-server")
        self.peer.on_request = self._on_server_request
        self.peer.serve()
        asyncio.get_running_loop().create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        while True:
            chunk = await self.proc.stderr.read(4096)
            if not chunk:
                break
            sys.stderr.write(chunk.decode(errors="replace"))
            sys.stderr.flush()

    async def _on_server_request(self, request_id: int, method: str, params: dict) -> None:
        if method == "callback/call" and self.peer:
            callback = params.get("callback") or {}
            approval = ApprovalRequest.from_callback(callback)
            # ack immediat de la requete (le serveur l'attend), puis
            # arbitrage en tache fond: l'approbation peut durer indefiniment.
            await self.peer.respond(request_id, {"callbackId": approval.callback_id, "accepted": True})
            asyncio.get_running_loop().create_task(self._handle_approval(request_id, approval))

    async def _handle_approval(self, request_id: int, approval: ApprovalRequest) -> None:
        decision: str | None = None
        if self.on_approval:
            decision = await self.on_approval(approval)
        if decision is None:
            # sans approveur, le client reste silencieux: un autre arbitre
            # (proxy, TUI) peut repondre au callback.
            return
        await self.respond_approval(approval, decision, feedback=f"m5stack:{decision}")

    # -- protocole -------------------------------------------------------

    async def initialize(self) -> dict:
        assert self.peer
        response = await self.peer.request(
            "initialize",
            {
                "clientInfo": {
                    "name": self.client_name,
                    "version": "0.7.0",
                    "entrypoint": "unknown",
                },
                "capabilities": {"callbackKinds": self.callback_kinds},
            },
        )
        if "error" in response:
            raise AppServerProtocolError(f"initialize: {response['error']}")
        await self.peer.notify("initialized", {})
        return response["result"]

    async def session_start(
        self,
        cwd: str,
        *,
        agent: str = "ask",
        auto_approve: bool = False,
        trust_workspace: bool = True,
    ) -> str:
        assert self.peer
        response = await self.peer.request(
            "session/start",
            {
                "agentConfig": {
                    "cwd": cwd,
                    "agent": agent,
                    "autoApprove": auto_approve,
                    "trustWorkspace": trust_workspace,
                },
                "historyLimit": 50,
            },
        )
        if "error" in response:
            raise AppServerProtocolError(f"session/start: {response['error']}")
        self.session_id = response["result"]["state"]["session"]["id"]
        return self.session_id

    async def turn_enqueue(self, text: str, session_id: str | None = None) -> str:
        assert self.peer
        sid = session_id or self.session_id
        if not sid:
            raise AppServerProtocolError("aucune session ouverte")
        response = await self.peer.request(
            "session/turn/enqueue",
            {
                "sessionId": sid,
                "entries": [{"role": "user", "content": [{"type": "text", "text": text}]}],
            },
        )
        if "error" in response:
            raise AppServerProtocolError(f"session/turn/enqueue: {response['error']}")
        return response["result"]["queueItemId"]

    async def respond_approval(
        self, approval: ApprovalRequest, decision: str, *, feedback: str | None = None
    ) -> dict:
        """Envoie callback/result — la reponse au bouton A/B/C du device."""
        if decision not in KNOWN_DECISIONS:
            raise AppServerProtocolError(f"decision inconnue: {decision}")
        assert self.peer
        sid = approval.session_id or self.session_id
        output: dict[str, Any] = {"type": "approval", "decision": {"type": decision}}
        if feedback:
            output["feedback"] = feedback
        response = await self.peer.request(
            "callback/result",
            {
                "sessionId": sid,
                "result": {"callbackId": approval.callback_id, "output": output},
            },
        )
        if "error" in response:
            raise AppServerProtocolError(f"callback/result: {response['error']}")
        return response["result"]

    async def wait_turn_done(self, timeout: float = 180.0) -> bool:
        """Attend turn/completed (notification consommee par le peer)."""
        assert self.peer
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

        async def on_notification(method: str, params: dict) -> None:
            if method == "turn/completed":
                if not fut.done():
                    fut.set_result(True)

        self.peer.on_notification = on_notification
        try:
            await asyncio.wait_for(fut, timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def session_read(self, history_limit: int = 30) -> dict | None:
        assert self.peer
        if not self.session_id:
            return None
        try:
            response = await self.peer.request(
                "session/read",
                {
                    "sessionId": self.session_id,
                    "history": {"limit": history_limit},
                    "turns": {"limit": 3},
                },
            )
        except TimeoutError:
            return None
        if "error" in response:
            return None
        return response["result"]

    async def close(self) -> None:
        if self.peer:
            await self.peer.close()
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.stdin.close()  # type: ignore[union-attr]
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except TimeoutError:
                self.proc.kill()
