"""Vibe M5Stack - Voice handler module"""
import asyncio
import logging
import threading
from typing import Optional, Dict, Any, Callable
from plugin.voice import get_voice_input

logger = logging.getLogger(__name__)

class VoiceHandler:
    def __init__(self):
        self._voice_input = get_voice_input()
        self._recording = False
        self._current_mode = None
        self._current_id = 0
        self._lock = threading.Lock()
        self._loop = None
        self._inject_callback = None
        self._resolve_approval_callback = None

    def set_inject_callback(self, callback):
        self._inject_callback = callback

    def set_resolve_approval_callback(self, callback):
        self._resolve_approval_callback = callback

    def set_event_loop(self, loop):
        self._loop = loop

    def handle_voice_message(self, msg):
        if msg.get("type") != "voice":
            return
        action = msg.get("action")
        mode = msg.get("mode", "prompt")
        request_id = msg.get("id", 0)
        logger.info(f"Voice message: action={action}, mode={mode}, id={request_id}")
        
        with self._lock:
            if action == "start":
                self._handle_voice_start(mode, request_id)
            elif action == "stop":
                self._handle_voice_stop(mode, request_id)

    def _handle_voice_start(self, mode, request_id):
        if self._recording:
            logger.warning("Recording already in progress")
            return
        self._current_mode = mode
        self._current_id = request_id
        self._recording = True
        if self._voice_input.record_start():
            logger.info(f"Recording started (mode={mode}, id={request_id})")
        else:
            logger.error("Failed to start recording")
            self._recording = False

    def _handle_voice_stop(self, mode, request_id):
        if not self._recording:
            logger.warning("No recording in progress")
            return
        
        wav_data = self._voice_input.record_stop()
        if not wav_data:
            logger.warning("No audio data captured")
            self._cleanup_recording()
            return
        
        if mode == "prompt":
            self._transcribe_and_inject(wav_data, False, 0)
        elif mode == "approve":
            self._transcribe_and_inject(wav_data, True, request_id)
        elif mode == "reject":
            self._transcribe_and_inject(wav_data, True, request_id)
        self._cleanup_recording()

    def _transcribe_and_inject(self, wav_data, is_approval, approval_id):
        if not self._voice_input.is_available():
            logger.error("Voice input not available")
            return
        threading.Thread(
            target=self._transcribe_thread,
            args=(wav_data, is_approval, approval_id),
            daemon=True
        ).start()

    def _transcribe_thread(self, wav_data, is_approval, approval_id):
        try:
            text = self._voice_input.transcribe_sync(wav_data)
            if not text or len(text.strip()) == 0:
                logger.warning("Empty transcription")
                return
            logger.info(f"Transcription: {text[:100]}...")
            if self._inject_callback:
                self._inject_callback(text)
            if is_approval and self._resolve_approval_callback:
                self._resolve_approval_callback(approval_id, False, text)
        except Exception as e:
            logger.error(f"Transcription error: {e}")

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
