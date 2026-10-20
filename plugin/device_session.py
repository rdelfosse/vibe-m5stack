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
"""Session device du proxy v0.7: proprietaire du port M5Stack.

Le proxy vit autant que la session Vibe: il detient la connexion serie/BT
persistante, pousse les statuts (qui servent de heartbeat, cf. broker 0.6,
HEARTBEAT_MS = 3000) et arbitre les approbations via la connexion deja
ouverte (request_approval_persistent), en renvoyant la demande jusqu'au
bouton — attendre quoi qu'il arrive.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger("vibe-m5stack.device")

#: Etats compris par le firmware (cf. bridge.send_status).
STATE_THINKING = "thinking"
STATE_WAITING = "waiting"
STATE_DONE = "done"
STATE_ERROR = "error"


class DeviceSession:
    """Connexion M5Stack persistante poussee par le proxy.

    Thread-safe: push_status peut etre appele depuis asyncio (to_thread) et
    le heartbeat tourne dans son propre thread, comme le broker 0.6.
    """

    HEARTBEAT_S = 3.0
    APPROVAL_RESEND_S = 30.0

    def __init__(
        self,
        bridge: Any = None,
        port: str | None = None,
        *,
        on_transcript: Any = None,
        on_reject: Any = None,
    ) -> None:
        self.bridge = bridge
        self.port = port
        self.on_transcript = on_transcript  # (texte) -> tour injecte par le proxy
        self.on_reject = on_reject  # (raison) -> approbation en cours refusee
        self.running = False
        self._seq = 0
        self._lock = threading.Lock()
        self._current: tuple[str, str, str] = (STATE_DONE, "", "")
        self._hb_thread: threading.Thread | None = None

    def _configure_voice(self) -> None:
        """Branche la dictee du device (VoiceHandler 0.6) sur le proxy v0.7.

        Le bridge route deja les messages voice/audio/audio_end vers le
        singleton VoiceHandler; on lui fournit transcriber REST (sans SDK)
        et callbacks.
        """
        try:
            from plugin import stt
            from plugin.voice_handler import get_voice_handler

            handler = get_voice_handler()
            handler.set_transcriber(stt.transcribe_sync)
            handler.set_send_voice_ack_callback(self._send_voice_ack)
            if self.on_transcript is not None:
                handler.set_inject_callback(self._dispatch_transcript)
            if self.on_reject is not None:
                handler.set_resolve_approval_callback(self._dispatch_reject)
        except Exception as exc:  # noqa: BLE001 - la voix ne doit jamais casser le statut
            logger.warning("DeviceSession: voix non branchee: %s", exc)

    def _send_voice_ack(self, state: str, text: str = "") -> None:
        if self.bridge:
            try:
                self.bridge.send_voice_ack(state, text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("voice ack: %s", exc)

    def _dispatch_transcript(self, text: str) -> None:
        cb = self.on_transcript
        if cb is None:
            return
        try:
            cb(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("transcript callback: %s", exc)

    def _dispatch_reject(self, request_id, approved: bool, reason: str) -> None:
        cb = self.on_reject
        if cb is None:
            return
        try:
            cb(reason)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reject callback: %s", exc)

    def start(self) -> bool:
        """Ouvre la connexion persistante. False si aucun device."""
        if self.bridge is None:
            from plugin.bridge import M5StackBridge

            self.bridge = M5StackBridge(auto_connect=False)
        port = self.port
        if not port:
            from plugin.config import resolve_port

            port = resolve_port()
        if not port:
            logger.info("DeviceSession: aucun port M5Stack, statuts desactives")
            return False
        self.port = port
        if not self.bridge.connect(port):
            logger.warning("DeviceSession: connexion impossible sur %s", port)
            return False
        self.running = True
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, name="m5stack-hb", daemon=True)
        self._hb_thread.start()
        self._configure_voice()
        logger.info("DeviceSession: connecte sur %s", port)
        return True

    def stop(self) -> None:
        self.running = False
        if self._hb_thread:
            self._hb_thread.join(timeout=2.0)
        if self.bridge:
            try:
                self.bridge.close()
            except Exception:  # noqa: BLE001 - fermeture au mieux
                pass

    def push_status(self, state: str, detail: str = "", activity: str = "") -> None:
        """Pousse un statut; sert aussi d'etat de reference du heartbeat."""
        if not self.running or self.bridge is None:
            return  # pas encore connecte (demarrage en tache de fond)
        with self._lock:
            self._seq += 1
            seq = self._seq
            self._current = (state, detail, activity)
        try:
            self.bridge.send_status(state, detail[:40], seq, activity)
        except Exception as exc:  # noqa: BLE001 - le lien peut etre absent
            logger.warning("DeviceSession.push_status: %s", exc)

    def _heartbeat_loop(self) -> None:
        """Repousse l'etat courant: heartbeat + resynchronisation du device
        apres un reboot/coupure BT (le bridge gere la reconnexion)."""
        while self.running:
            with self._lock:
                state, detail, activity = self._current
            try:
                self.bridge.send_status(state, detail[:40], self._seq, activity)
            except Exception as exc:  # noqa: BLE001
                logger.warning("DeviceSession.heartbeat: %s", exc)
            time.sleep(self.HEARTBEAT_S)

    def decide_blocking(self, approval, cancel: threading.Event) -> str | None:
        """Arbitre une approbation sur la connexion persistante.

        Renvoie la meme requete (meme id) jusqu'a la reponse ou
        l'annulation: l'ecran d'approbation reste affiche sur le device,
        sans limite de duree. Retourne None si annule (l'autre arbitre —
        la TUI — a repondu) ou si le lien est mort.
        """
        request_id = abs(hash(approval.callback_id)) % 1_000_000
        while self.running and not cancel.is_set():
            response = None
            try:
                response = self.bridge.request_approval_persistent(
                    title=approval.title, body=approval.body, request_id=request_id
                )
            except Exception as exc:  # noqa: BLE001 - lien serie fragile
                logger.warning("DeviceSession.decide: %s", exc)
            if response is not None:
                if response.get("approved"):
                    return "approve"
                if response.get("cancelled"):
                    return "deny"
                logger.warning("DeviceSession.decide: reponse inconnue: %s", response)
                return "deny"
            cancel.wait(self.APPROVAL_RESEND_S)
        return None

    async def decide(self, approval, cancel: threading.Event) -> str | None:
        import asyncio

        return await asyncio.to_thread(self.decide_blocking, approval, cancel)
