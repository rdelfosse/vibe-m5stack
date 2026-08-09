"""Vibe M5Stack - Voice input module"""
import asyncio
import io
import logging
import os
import threading
import wave
from typing import Optional

# Enfant du logger du hook -> écrit dans ~/.vibe/logs/m5stack_hook.log
# (sinon les erreurs de capture/transcription partent dans le vide).
logger = logging.getLogger("m5stack_hook.voice_input")
VOXTRAL_MODEL = "voxtral-mini-latest"
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2

class VoiceInput:
    def __init__(self):
        self._recording = False
        self._audio_data = None
        self._stream = None
        self._lock = threading.Lock()
        self._has_sounddevice = False
        self._has_mistralai = False
        self._has_api_key = False
        try:
            import sounddevice
            self._has_sounddevice = True
        except ImportError:
            pass
        try:
            import mistralai
            self._has_mistralai = True
        except ImportError:
            pass
        self._has_api_key = bool(self._get_api_key())

    def _get_api_key(self):
        """Résout la clé comme Vibe lui-même : env puis keyring OS.

        Une clé posée par `vibe` (login navigateur -> keyring) fonctionne donc
        sans variable d'environnement. Résolution paresseuse : la clé peut
        apparaître après le premier import.
        """
        try:
            from vibe.core.config.vibe_schema import resolve_api_key
            key = resolve_api_key("MISTRAL_API_KEY")
            if key:
                return key
        except Exception as e:
            logger.debug(f"resolve_api_key failed: {e}")
        return os.environ.get("MISTRAL_API_KEY") or None

    def is_available(self):
        # Ré-évaluer la clé à chaque fois (login possible en cours de session).
        self._has_api_key = bool(self._get_api_key())
        return self._has_sounddevice and self._has_mistralai and self._has_api_key

    def availability_detail(self):
        """Pour les logs : dit précisément ce qui manque."""
        return (f"sounddevice={self._has_sounddevice} "
                f"mistralai={self._has_mistralai} "
                f"api_key={'oui' if self._get_api_key() else 'NON'}")

    def record_start(self):
        if not self._has_sounddevice:
            return False
        with self._lock:
            if self._recording:
                return False
            try:
                import sounddevice as sd
                # RawInputStream livre des buffers bruts (int16 little-endian),
                # sans dépendre de numpy (requis par InputStream).
                self._stream = sd.RawInputStream(
                    samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16',
                    callback=self._audio_callback
                )
                self._stream.start()
                self._recording = True
                self._audio_data = b''
                return True
            except Exception as e:
                logger.error(f"Failed to start recording: {e}")
                return False

    def _audio_callback(self, indata, frames, time, status):
        audio_bytes = bytes(indata)
        with self._lock:
            if self._recording:
                if self._audio_data is None:
                    self._audio_data = b''
                self._audio_data += audio_bytes

    def record_stop(self):
        # Étape 1 : sous verrou, basculer l'état et confisquer stream + audio.
        # NE PAS appeler stream.stop() ni _cleanup_recording() sous le verrou :
        # stop() attend la fin des callbacks audio (qui prennent ce même verrou)
        # et _cleanup_recording() le reprend — deadlock dans les deux cas.
        with self._lock:
            if not self._recording:
                return None
            self._recording = False
            stream = self._stream
            self._stream = None
            audio_data = self._audio_data
            self._audio_data = None
        # Étape 2 : hors verrou, arrêter le flux (les callbacks restants
        # no-opent car _recording est déjà False).
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                logger.error(f"Error stopping recording: {e}")
        if not audio_data:
            return None
        try:
            return self._encode_to_wav(audio_data)
        except Exception as e:
            logger.error(f"Error encoding wav: {e}")
            return None

    def _encode_to_wav(self, audio_data):
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(SAMPLE_WIDTH)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(audio_data)
        return wav_buffer.getvalue()

    def _cleanup_recording(self):
        # Même discipline que record_stop : confisquer sous verrou,
        # stopper le flux HORS verrou (callbacks audio -> self._lock).
        with self._lock:
            self._recording = False
            self._audio_data = None
            stream = self._stream
            self._stream = None
        if stream is not None:
            try:
                if stream.active:
                    stream.stop()
                stream.close()
            except Exception:
                pass

    async def transcribe(self, wav_data):
        if not self._has_mistralai:
            return ""
        try:
            try:
                from mistralai.client import Mistral  # SDK >= 2.x (top-level vide)
            except ImportError:
                from mistralai import Mistral  # anciens SDK
            api_key = self._get_api_key()
            if not api_key:
                return ""
            client = Mistral(api_key=api_key)
            # SDK 2.x : la méthode batch s'appelle complete() (create() avant).
            transcriptions = client.audio.transcriptions
            method = getattr(transcriptions, "complete", None) or transcriptions.create
            response = method(
                model=VOXTRAL_MODEL,
                file={"file_name": "ptt.wav", "content": wav_data},
                language="fr",
            )
            return response.text
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return ""

    def transcribe_sync(self, wav_data):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.transcribe(wav_data))

    def cancel(self):
        # _cleanup_recording gère lui-même le verrou (le prendre ici = deadlock).
        self._cleanup_recording()

_voice_input = None

def get_voice_input():
    global _voice_input
    if _voice_input is None:
        _voice_input = VoiceInput()
    return _voice_input
