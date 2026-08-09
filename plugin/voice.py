"""Vibe M5Stack - Voice input module"""
import asyncio
import io
import logging
import os
import threading
import wave
from typing import Optional

logger = logging.getLogger(__name__)
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
        if "MISTRAL_API_KEY" in os.environ and os.environ["MISTRAL_API_KEY"]:
            self._has_api_key = True

    def is_available(self):
        return self._has_sounddevice and self._has_mistralai and self._has_api_key

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
        with self._lock:
            if not self._recording:
                return None
            self._recording = False
            try:
                if self._stream:
                    self._stream.stop()
                    self._stream.close()
                    self._stream = None
                if not self._audio_data:
                    self._cleanup_recording()
                    return None
                wav_data = self._encode_to_wav(self._audio_data)
                self._cleanup_recording()
                return wav_data
            except Exception as e:
                logger.error(f"Error stopping recording: {e}")
                self._cleanup_recording()
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
        with self._lock:
            self._recording = False
            self._audio_data = None
            if self._stream:
                try:
                    if self._stream.active:
                        self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

    async def transcribe(self, wav_data):
        if not self._has_mistralai or not self._has_api_key:
            return ""
        try:
            import mistralai
            api_key = os.environ.get("MISTRAL_API_KEY", "")
            if not api_key:
                return ""
            client = mistralai.Mistral(api_key=api_key)
            response = client.audio.transcriptions.create(
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
        with self._lock:
            self._cleanup_recording()

_voice_input = None

def get_voice_input():
    global _voice_input
    if _voice_input is None:
        _voice_input = VoiceInput()
    return _voice_input
