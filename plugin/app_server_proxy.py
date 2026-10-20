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
"""Proxy MITM entre le client Vibe (TUI vibe-rs) et l'app server reel.

Insertion (Vibe 3.x) : le wrapper ``vibe-m5stack`` positionne
``VIBE_APP_SERVER_BIN`` sur l'entrypoint ``vibe-m5stack-app-server``. Le
client Rust lance alors ce proxy comme s'il lancait l'app server; le proxy
lance le vrai ``vibe-app-server`` en enfant et relaie le protocole.

Le proxy termine les deux sessions JSON-RPC (ids remappes de chaque cote) et
intercepte les callbacks d'approbation::

    client (TUI) <--> proxy <--> vibe-app-server
                          |
                          +--> approver (device M5Stack / auto / off)

Course TUI/device: le premier qui repond gagne; la decision loser est
silencieusement ignoree (cote TUI: callback/result avale et acquitte).

Modes (M5STACK_APPROVAL_MODE):
    off           : relais pur, aucune interception (defaut)
    auto-approve  : decision immediate approve (tests)
    auto-deny     : decision immediate deny (tests)
    device        : M5Stack arbitre, en course avec la TUI
M5STACK_APPROVAL_TUI=0 : la TUI ne voit jamais les approbations
(le device arbitre seul; ses ecrans restent la reference).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable

from plugin.app_server_client import (
    DECISION_APPROVE,
    DECISION_DENY,
    ApprovalRequest,
    AppServerProtocolError,
    JsonRpcPeer,
)
from plugin.device_session import (
    STATE_DONE,
    STATE_ERROR,
    STATE_THINKING,
    STATE_WAITING,
    DeviceSession,
)

logger = logging.getLogger("vibe-m5stack.proxy")

REQUEST_TIMEOUT_S = 3600.0  # les approvals restent ouvertes indefiniment
_ENV_MODE = "M5STACK_APPROVAL_MODE"
_ENV_TUI = "M5STACK_APPROVAL_TUI"
_ENV_REAL_SERVER = "VIBE_M5STACK_REAL_APP_SERVER"
_ENV_STATUS = "M5STACK_STATUS"


def status_from_notification(method: str, params: dict) -> tuple[str, str, str] | None:
    """Mappe une notification app server vers (state, detail, activity).

    Etats attendus par le firmware: thinking/waiting/done/error, activites
    reasoning/tool_exec/reading/streaming (cf. bridge.send_status).
    """
    if method == "turn/started":
        return (STATE_THINKING, "", "reasoning")
    if method == "turn/completed":
        turn = params.get("turn") or {}
        error = turn.get("error")
        if error:
            return (STATE_ERROR, str(error)[:40], "")
        return (STATE_DONE, "", "")
    if method == "history/entryAdded":
        entry = params.get("entry") or {}
        kind = entry.get("type")
        if kind == "reasoning":
            return (STATE_THINKING, "", "reasoning")
        if kind == "effect":
            return (STATE_THINKING, str(entry.get("title") or "")[:40], "tool_exec")
        if entry.get("role") == "assistant":
            return (STATE_THINKING, "", "streaming")
    return None


def resolve_real_app_server() -> list[str]:
    """Commande de l'app server reel: env explicite (ligne de commande)
    ou le binaire voisin de l'executable."""
    explicit = os.environ.get(_ENV_REAL_SERVER)
    if explicit:
        import shlex

        return shlex.split(explicit)
    exe = Path(sys.executable).resolve()
    candidate = exe.parent / ("vibe-app-server.exe" if sys.platform == "win32" else "vibe-app-server")
    if not candidate.exists():
        raise SystemExit(f"vibe-app-server introuvable: {candidate} (positionne {_ENV_REAL_SERVER})")
    return [str(candidate)]


# ---------------------------------------------------------------------------
# Approveurs


class Approver:
    """Arbitre une demande d'approbation.

    decide() retourne une decision (voir app_server_client.KNOWN_DECISIONS)
    ou None pour laisser la main a l'autre arbitre (la TUI).
    """

    async def decide(self, approval: ApprovalRequest, cancel: threading.Event) -> str | None:
        raise NotImplementedError


class EnvApprover(Approver):
    """Decision fixe par env — pour tests et mode off."""

    def __init__(self, decision: str | None) -> None:
        self.decision = decision

    async def decide(self, approval: ApprovalRequest, cancel: threading.Event) -> str | None:
        return self.decision


class DeviceApprover(Approver):
    """Arbitrage physique sur le M5Stack.

    Avec une DeviceSession connectee (proxy proprietaire du port):
    arbitrage sur la connexion persistante, renvoi indefini jusqu'au bouton
    — attendre quoi qu'il arrive. Sans session (statuts off ou device pas
    encore connecte): requete a connexion fraiche sous FileLock, FIFO avec
    d'autres sessions, meme contrat de renvoi. Device absent au premier
    tour: retourne None (fallback TUI).
    """

    RESEND_INTERVAL_S = 30.0
    ABSENT_PROBE_RETRY_S = 5.0

    def __init__(self, session_provider: Callable[[], Any] | None = None) -> None:
        self.session_provider = session_provider
        self._bridge: Any = None

    def _live_session(self) -> Any | None:
        session = self.session_provider() if self.session_provider else None
        if session is not None and getattr(session, "running", False):
            return session
        return None

    def _get_bridge(self) -> Any:
        if self._bridge is None:
            from plugin.bridge import M5StackBridge

            self._bridge = M5StackBridge(auto_connect=False)
        return self._bridge

    def _decide_fresh(self, approval: ApprovalRequest, cancel: threading.Event) -> str | None:
        from plugin.config import resolve_port

        bridge = self._get_bridge()
        request_id = abs(hash(approval.callback_id)) % 1_000_000
        first = True
        while not cancel.is_set():
            if first and resolve_port() is None:
                logger.warning("DeviceApprover: aucun port M5Stack — fallback TUI")
                return None
            response = bridge.request_approval(
                title=approval.title, body=approval.body, request_id=request_id
            )
            if response is not None:
                if response.get("approved"):
                    return DECISION_APPROVE
                if response.get("cancelled"):
                    return DECISION_DENY
                logger.warning("DeviceApprover: reponse inconnue: %s", response)
                return DECISION_DENY
            first = False
            cancel.wait(self.RESEND_INTERVAL_S)
        return None

    async def decide(self, approval: ApprovalRequest, cancel: threading.Event) -> str | None:
        session = self._live_session()
        if session is not None:
            return await session.decide(approval, cancel)
        return await asyncio.to_thread(self._decide_fresh, approval, cancel)


def make_approver(session_provider: Callable[[], Any] | None = None) -> Approver:
    mode = os.environ.get(_ENV_MODE, "off").strip().lower()
    if mode == "auto-approve":
        return EnvApprover(DECISION_APPROVE)
    if mode == "auto-deny":
        return EnvApprover(DECISION_DENY)
    if mode == "off":
        return EnvApprover(None)
    if mode == "device":
        return DeviceApprover(session_provider)
    raise SystemExit(f"{_ENV_MODE} inconnu: {mode} (off|auto-approve|auto-deny|device)")


# ---------------------------------------------------------------------------
# Routeur d'approbation


class ApprovalRouter:
    """Course entre l'approveur et la TUI pour chaque callback."""

    def __init__(self, approver: Approver, send_result: Callable[[dict], Awaitable[dict]]) -> None:
        self.approver = approver
        self.send_result = send_result  # requete callback/result vers le serveur
        self.answered: set[str] = set()
        self.cancels: dict[str, threading.Event] = {}
        self.tui_visible = os.environ.get(_ENV_TUI, "1") != "0"

    async def offer(self, approval: ApprovalRequest) -> None:
        """Propose l'approbation a l'approveur (tache fond)."""
        if approval.callback_id in self.answered:
            return
        cancel = threading.Event()
        self.cancels[approval.callback_id] = cancel

        async def run() -> None:
            try:
                decision = await self.approver.decide(approval, cancel)
            finally:
                self.cancels.pop(approval.callback_id, None)
            if decision is None or cancel.is_set():
                return
            if approval.callback_id in self.answered:
                logger.info("approbation %s deja arbitree (TUI)", approval.callback_id)
                return
            await self.send_result(
                {
                    "sessionId": approval.session_id,
                    "result": {
                        "callbackId": approval.callback_id,
                        "output": {
                            "type": "approval",
                            "decision": {"type": decision},
                            "feedback": f"m5stack:{decision}",
                        },
                    },
                }
            )
            self.answered.add(approval.callback_id)
            logger.info("approbation %s arbitree par le device: %s", approval.callback_id, decision)

        asyncio.get_running_loop().create_task(run())

    def tui_answered(self, callback_id: str) -> None:
        """La TUI a repondu: marque arbitree et annule l'approveur en course."""
        self.answered.add(callback_id)
        cancel = self.cancels.get(callback_id)
        if cancel:
            cancel.set()


# ---------------------------------------------------------------------------
# Proxy


class AppServerProxy:
    """Relais JSON-RPC client <-> app server avec interception d'approbations."""

    def __init__(
        self,
        *,
        approver: Approver | None = None,
        device: Any = None,
        device_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.approver = approver
        self.device = device  # DeviceSession-like: push_status/stop
        self.device_factory = device_factory
        self.left: JsonRpcPeer | None = None  # cote client (TUI)
        self.right: JsonRpcPeer | None = None  # cote app server
        self.proc: asyncio.subprocess.Process | None = None
        self.router: ApprovalRouter | None = None
        self.last_event_id = 0

    async def run(
        self,
        real_app_server: list[str] | str | Path | None = None,
        *,
        left_read: Callable[[], Awaitable[bytes]] | None = None,
        left_write: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> None:
        if real_app_server is None:
            command = resolve_real_app_server()
        elif isinstance(real_app_server, (str, Path)):
            command = [str(real_app_server)]
        else:
            command = list(real_app_server)
        self.proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert self.proc.stdout and self.proc.stdin and self.proc.stderr

        if left_read is None:

            async def left_read_default() -> bytes:  # type: ignore[misc]
                return await asyncio.to_thread(sys.stdin.buffer.read1, 65536)

            left_read = left_read_default
        if left_write is None:

            async def left_write_default(line: bytes) -> None:  # type: ignore[misc]
                await asyncio.to_thread(sys.stdout.buffer.write, line)
                await asyncio.to_thread(sys.stdout.buffer.flush)

            left_write = left_write_default

        async def write_child(line: bytes) -> None:
            self.proc.stdin.write(line)
            await self.proc.stdin.drain()

        self.left = JsonRpcPeer(left_read, left_write, label="client", request_timeout=REQUEST_TIMEOUT_S)
        self.right = JsonRpcPeer(
            lambda: self.proc.stdout.read(65536), write_child, label="server", request_timeout=REQUEST_TIMEOUT_S
        )
        if self.approver is None:
            self.approver = make_approver(
                lambda: self.device if self.device is not None else None
            )
        self.router = ApprovalRouter(self.approver, self._send_callback_result)

        # Connexion device en tache de fond: la connexion serie/BT peut etre
        # lente et le client (TUI) attend un initialize rapide — jamais sur
        # le chemin critique. Les statuts partent des qu'elle est prete.
        if self.device is None and self.device_factory is not None:
            def connect_device() -> None:
                device = self.device_factory()
                if device is not None and getattr(device, "start", lambda: False)():
                    self.device = device
                    logger.info("device connecte en arriere-plan")
                else:
                    logger.info("device absent ou indisponible: statuts/approbation via TUI")

            asyncio.get_running_loop().create_task(asyncio.to_thread(connect_device))

        self.left.on_request = self._on_client_request
        self.left.on_notification = self._on_client_notification
        self.right.on_request = self._on_server_request
        self.right.on_notification = self._on_server_notification

        asyncio.get_running_loop().create_task(self._drain_child_stderr())
        right_task = self.right.serve()
        left_task = self.left.serve()
        exit_task = asyncio.get_running_loop().create_task(self._child_exit_watch())

        try:
            done, pending = await asyncio.wait(
                {left_task, right_task, exit_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
        finally:
            await self.close()

    async def _child_exit_watch(self) -> None:
        assert self.proc is not None
        code = await self.proc.wait()
        logger.info("app server arrete (code %s), fermeture du proxy", code)

    async def _drain_child_stderr(self) -> None:
        assert self.proc is not None
        while True:
            chunk = await self.proc.stderr.read(4096)
            if not chunk:
                break
            sys.stderr.write(chunk.decode(errors="replace"))
            sys.stderr.flush()

    # -- navigation client -> serveur -------------------------------------

    async def _on_client_request(self, rid: int, method: str, params: dict) -> None:
        assert self.left and self.right and self.router
        callback_id = (params.get("result") or {}).get("callbackId") if method == "callback/result" else None
        if callback_id:
            if callback_id in self.router.answered:
                # le device a deja arbitre: on avale la reponse tardive de la
                # TUI en acquittant pour qu'elle ne parte pas en erreur.
                logger.info("callback/result TUI avale (deja arbitre): %s", callback_id)
                await self.left.respond(rid, {"accepted": True, "lastEventId": self.last_event_id})
                return
            self.router.tui_answered(callback_id)
        try:
            response = await self.right.request(method, params)
        except (TimeoutError, AppServerProtocolError) as exc:
            await self.left.respond_error(rid, -32000, f"proxy: {exc}")
            return
        if "error" in response:
            await self.left.respond_error(rid, response["error"].get("code", -32000), response["error"].get("message", ""))
        else:
            await self.left.respond(rid, response.get("result") or {})
            if callback_id:
                self.router.answered.add(callback_id)

    async def _on_client_notification(self, method: str, params: dict) -> None:
        assert self.right
        await self.right.notify(method, params)

    # -- navigation serveur -> client -------------------------------------

    async def _on_server_request(self, rid: int, method: str, params: dict) -> None:
        assert self.left and self.right and self.router
        if method == "callback/call":
            await self._on_approval_call(rid, params)
            return
        try:
            response = await self.left.request(method, params)
        except (TimeoutError, AppServerProtocolError) as exc:
            await self.right.respond_error(rid, -32000, f"proxy: {exc}")
            return
        if "error" in response:
            await self.right.respond_error(rid, response["error"].get("code", -32000), response["error"].get("message", ""))
        else:
            await self.right.respond(rid, response.get("result") or {})

    async def _on_approval_call(self, rid: int, params: dict) -> None:
        """callback/call du serveur: TUI + device en course (ou device seul).

        L'approveur est sollicite immediatement, sans attendre l'ack TUI:
        le device doit pouvoir arbitrer meme si la TUI tarde.
        """
        assert self.left and self.right and self.router
        approval = ApprovalRequest.from_callback(params.get("callback") or {})
        asyncio.get_running_loop().create_task(self.router.offer(approval))
        if self.device:
            await asyncio.to_thread(self.device.push_status, STATE_WAITING, approval.tool)
        if self.router.tui_visible:
            try:
                ack = await self.left.request("callback/call", params)
                await self.right.respond(rid, ack.get("result") or {"callbackId": approval.callback_id})
            except (TimeoutError, AppServerProtocolError) as exc:
                await self.right.respond_error(rid, -32000, f"proxy: {exc}")
        else:
            # la TUI ne doit pas afficher de dialogue: ack cote proxy.
            await self.right.respond(rid, {"callbackId": approval.callback_id, "accepted": True})

    async def _send_callback_result(self, params: dict) -> dict:
        assert self.right
        response = await self.right.request("callback/result", params)
        if "error" in response:
            raise AppServerProtocolError(f"callback/result: {response['error']}")
        return response.get("result") or {}

    async def _on_server_notification(self, method: str, params: dict) -> None:
        assert self.left
        event_id = params.get("eventId")
        if isinstance(event_id, int) and event_id > self.last_event_id:
            self.last_event_id = event_id
        await self.left.notify(method, params)
        if self.device:
            mapped = status_from_notification(method, params)
            if mapped:
                state, detail, activity = mapped
                await asyncio.to_thread(self.device.push_status, state, detail, activity)

    async def close(self) -> None:
        if self.left:
            await self.left.close()
        if self.right:
            await self.right.close()
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.stdin.close()  # type: ignore[union-attr]
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except TimeoutError:
                self.proc.kill()
        if self.device and hasattr(self.device, "stop"):
            stop = self.device.stop
            await asyncio.to_thread(stop)


def _setup_logging() -> Path:
    """Logs vers un fichier: la TUI Rust avalait la stderr du proxy.

    Retourne le chemin du fichier de log."""
    import tempfile

    log_path = os.environ.get("VIBE_M5STACK_LOG_FILE")
    if not log_path:
        log_path = str(Path(tempfile.gettempdir()) / "vibe-m5stack-proxy.log")
    level = os.environ.get("VIBE_M5STACK_LOG", "INFO")
    handlers: list[logging.Handler] = [logging.FileHandler(log_path, encoding="utf-8")]
    if os.environ.get("VIBE_M5STACK_LOG_STDERR"):
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )
    return Path(log_path)


def main() -> None:
    log_path = _setup_logging()
    logger.info("proxy demarre, log: %s", log_path)

    def make_device_session() -> DeviceSession | None:
        if os.environ.get(_ENV_STATUS, "device").strip().lower() == "off":
            return None
        return DeviceSession()

    try:
        asyncio.run(AppServerProxy(device_factory=make_device_session).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
