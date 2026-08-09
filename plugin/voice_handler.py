"""Vibe M5Stack - Voice handler module.

Reçoit les événements voice du device (via le reader du broker), pilote
l'enregistrement micro côté PC et la transcription Voxtral, puis :
  - prompt  : injecte la transcription comme instruction utilisateur ;
  - approve : injecte la transcription en commentaire (l'approbation est déjà
              résolue YES par le response envoyé par le device) ;
  - reject  : résout l'approbation en NO avec la transcription comme raison
              (PAS d'injection : le feedback EST la consigne).
"""
import logging
import threading

from plugin.voice import get_voice_input

# Enfant du logger du hook : hérite de son FileHandler (~/.vibe/logs/
# m5stack_hook.log) — sinon les traces voix partent dans le vide.
logger = logging.getLogger("m5stack_hook.voice")

# Message de refus par défaut quand la consigne vocale est vide/indisponible.
DEFAULT_REJECT_REASON = "User rejected via M5Stack"


class VoiceHandler:
    def __init__(self):
        self._voice_input = get_voice_input()
        self._recording = False
        self._current_mode = None
        self._current_id = 0
        # RLock : _cleanup_recording() est appelé depuis des chemins qui
        # tiennent déjà le verrou (handle_voice_message -> _handle_voice_stop).
        self._lock = threading.RLock()

        self._inject_callback = None
        self._resolve_approval_callback = None
        self._send_voice_ack_callback = None

        # Session micro device : l'audio arrive en chunks µ-law base64 streamés
        # par le M5Stack pendant l'enregistrement, clos par audio_end.
        self._device_session = None  # {mode, id, data: bytearray, timer}

    def set_inject_callback(self, callback):
        self._inject_callback = callback

    def set_resolve_approval_callback(self, callback):
        self._resolve_approval_callback = callback

    def set_send_voice_ack_callback(self, callback):
        self._send_voice_ack_callback = callback

    # -- Entrée des messages device ----------------------------------------

    def handle_voice_message(self, msg):
        if msg.get("type") != "voice":
            return

        action = msg.get("action")
        mode = msg.get("mode", "prompt")
        request_id = msg.get("id", 0)
        mic = msg.get("mic", "pc")

        logger.info(f"Voice message: action={action}, mode={mode}, id={request_id}, mic={mic}")

        with self._lock:
            if mic == "device":
                if action == "start":
                    self._device_start(mode, request_id)
                # stop : rien à faire, les chunks/audio_end suivent d'eux-mêmes
            else:
                if action == "start":
                    self._handle_voice_start(mode, request_id)
                elif action == "stop":
                    self._handle_voice_stop(mode, request_id)

    # -- Session micro device ------------------------------------------------

    def _device_start(self, mode, request_id):
        self._cancel_device_session()
        timer = threading.Timer(90.0, self._device_timeout)
        timer.daemon = True
        timer.start()
        self._device_session = {
            "mode": mode,
            "id": request_id,
            "data": bytearray(),
            "timer": timer,
        }
        logger.info(f"Device mic session started (mode={mode}, id={request_id})")

    def handle_audio_chunk(self, msg):
        import base64
        with self._lock:
            if self._device_session is None:
                return
            try:
                self._device_session["data"] += base64.b64decode(msg.get("data", ""))
            except Exception:
                logger.warning("Invalid audio chunk dropped")

    def handle_audio_end(self, msg):
        with self._lock:
            session = self._device_session
            self._device_session = None
            if session is None:
                logger.warning("audio_end without device session")
                return
            session["timer"].cancel()

        data = bytes(session["data"])
        total = msg.get("total")
        if total is not None and total != len(data):
            logger.warning(f"Audio incomplete: {len(data)}/{total} octets (chunks perdus)")

        mode, request_id = session["mode"], session["id"]
        capture_ms = msg.get("ms") or 0
        logger.info(
            f"Device audio received: {len(data)} octets, capture réelle {capture_ms} ms"
        )

        # L'I2S-ADC de l'ESP32 ne tient pas la fréquence demandée : recaler le
        # flux sur 16 kHz d'après la durée mesurée par le device.
        if capture_ms > 200 and len(data) > 0:
            actual_rate = len(data) * 1000.0 / capture_ms
            if abs(actual_rate - 16000) / 16000 >= 0.03:
                from plugin.voice import resample_ulaw
                logger.info(f"Resampling: débit ADC effectif {actual_rate:.0f} Hz -> 16000 Hz")
                data = resample_ulaw(data, actual_rate)

        if len(data) < 1600:  # < 100 ms : rien d'exploitable
            logger.warning("Device audio too short")
            self._send_ack("done", "")
            self._resolve_reject_fallback(mode, request_id, DEFAULT_REJECT_REASON)
            return

        from plugin.voice import ulaw_to_wav
        try:
            wav_data = ulaw_to_wav(data)
        except Exception:
            logger.exception("ulaw decode failed")
            self._send_ack("done", "")
            self._resolve_reject_fallback(mode, request_id, DEFAULT_REJECT_REASON)
            return

        self._maybe_dump_debug(wav_data)
        self._send_ack("transcribing", "")

        if not self._voice_input.transcription_available():
            logger.error(
                "Transcription not available: " + self._voice_input.availability_detail()
            )
            self._send_ack("done", "")
            self._resolve_reject_fallback(
                mode, request_id, DEFAULT_REJECT_REASON + " (voice unavailable)"
            )
            return

        do_inject = mode in ("prompt", "approve")
        reject_id = request_id if mode == "reject" else None
        threading.Thread(
            target=self._transcribe_thread,
            args=(wav_data, do_inject, reject_id),
            daemon=True,
            name="voice-transcribe",
        ).start()

    def _device_timeout(self):
        with self._lock:
            session = self._device_session
            self._device_session = None
        if session is not None:
            logger.error("Device mic session timeout (audio_end jamais reçu)")
            self._send_ack("done", "")
            self._resolve_reject_fallback(
                session["mode"], session["id"], DEFAULT_REJECT_REASON + " (timeout)"
            )

    def _cancel_device_session(self):
        if self._device_session is not None:
            self._device_session["timer"].cancel()
            self._device_session = None

    def _handle_voice_start(self, mode, request_id):
        if self._recording:
            # Session zombie (stop jamais reçu : reboot device, message perdu…) :
            # on repart proprement plutôt que de bloquer la voix pour toujours.
            logger.warning("Recording already in progress - resetting stale session")
            try:
                self._voice_input.cancel()
            except Exception:
                pass
            self._cleanup_recording()

        self._current_mode = mode
        self._current_id = request_id
        self._recording = True

        if self._voice_input.record_start():
            logger.info(f"Recording started (mode={mode}, id={request_id})")
        else:
            logger.error("Failed to start recording")
            self._cleanup_recording()

    def _handle_voice_stop(self, mode, request_id):
        if not self._recording:
            logger.warning("No recording in progress")
            return

        wav_data = self._voice_input.record_stop()
        # Quoi qu'il arrive ensuite, la session d'enregistrement est terminée :
        # la transcription tourne dans son propre thread sur wav_data.
        self._cleanup_recording()

        if not wav_data:
            logger.warning("No audio data captured")
            self._send_ack("done", "")
            self._resolve_reject_fallback(mode, request_id, DEFAULT_REJECT_REASON)
            return

        self._maybe_dump_debug(wav_data)

        if mode not in ("prompt", "approve", "reject"):
            logger.warning(f"Unknown mode: {mode}")
            self._send_ack("done", "")
            return

        # L'enregistrement est fini, la transcription commence.
        self._send_ack("transcribing", "")

        if not self._voice_input.is_available():
            logger.error(
                "Voice input not available: " + self._voice_input.availability_detail()
            )
            self._send_ack("done", "")
            self._resolve_reject_fallback(
                mode, request_id, DEFAULT_REJECT_REASON + " (voice unavailable)"
            )
            return

        # reject : résoudre l'approbation, ne PAS injecter (le feedback EST la
        # consigne). prompt/approve : injecter seulement.
        do_inject = mode in ("prompt", "approve")
        reject_id = request_id if mode == "reject" else None
        threading.Thread(
            target=self._transcribe_thread,
            args=(wav_data, do_inject, reject_id),
            daemon=True,
            name="voice-transcribe",
        ).start()

    # -- Transcription (thread dédié) ---------------------------------------

    def _transcribe_thread(self, wav_data, do_inject, reject_id):
        try:
            text = self._voice_input.transcribe_sync(wav_data)
            text = text.strip() if text else ""

            self._send_ack("done", text[:60])

            if not text:
                logger.warning("Empty transcription")
                if reject_id is not None:
                    self._resolve(reject_id, DEFAULT_REJECT_REASON)
                return

            logger.info(f"Transcription: {text[:100]}")

            if reject_id is not None:
                self._resolve(reject_id, text)
            elif do_inject and self._inject_callback:
                self._inject_callback(text)

        except Exception as e:
            logger.error(f"Transcription error: {e}")
            self._send_ack("done", "")
            if reject_id is not None:
                self._resolve(reject_id, f"{DEFAULT_REJECT_REASON} (voice error)")

    # -- Helpers -------------------------------------------------------------

    def _resolve(self, request_id, reason):
        if self._resolve_approval_callback:
            try:
                self._resolve_approval_callback(request_id, False, reason)
            except Exception:
                logger.exception("resolve_approval_callback failed")
        else:
            logger.warning("No resolve_approval_callback set - reject lost")

    def _resolve_reject_fallback(self, mode, request_id, reason):
        """Un reject sans transcription doit quand même refuser l'action."""
        if mode == "reject":
            self._resolve(request_id, reason)

    def _maybe_dump_debug(self, wav_data):
        """Mode debug (menu config du device, OFF par défaut) : garder la
        dernière capture sur disque pour audit. L'audio est une donnée
        sensible — jamais persistée hors debug explicite."""
        from plugin import runtime_flags
        if not runtime_flags.debug_enabled():
            return
        try:
            from pathlib import Path
            dump = Path.home() / ".vibe" / "logs" / "last_ptt.wav"
            dump.write_bytes(wav_data)
            duration_ms = max(0, (len(wav_data) - 44)) // 32  # 16 kHz mono 16-bit
            logger.info(
                f"[debug] Audio capture: {len(wav_data)} octets (~{duration_ms} ms) -> {dump}"
            )
        except Exception:
            logger.exception("Could not dump last_ptt.wav")

    def _send_ack(self, state, text):
        if self._send_voice_ack_callback:
            try:
                self._send_voice_ack_callback(state, text)
            except Exception:
                logger.exception("send_voice_ack_callback failed")

    def _cleanup_recording(self):
        with self._lock:
            self._recording = False
            self._current_mode = None
            self._current_id = 0


_voice_handler = None


def get_voice_handler():
    global _voice_handler
    if _voice_handler is None:
        _voice_handler = VoiceHandler()
    return _voice_handler
