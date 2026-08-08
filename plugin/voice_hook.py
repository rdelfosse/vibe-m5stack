"""Vibe M5Stack - Voice hook integration"""
import asyncio
import logging
import threading
from typing import Any, Optional
from plugin.voice_handler import get_voice_handler
from plugin.bridge import get_or_init_broker

logger = logging.getLogger(__name__)

_voice_initialized = False
_voice_thread = None
_voice_running = False


def _voice_message_listener():
    global _voice_running
    logger.info("Voice message listener thread started")
    while _voice_running:
        try:
            mgr = get_or_init_broker()
            if mgr is None:
                threading.Event().wait(1.0)
                continue
            bridge = getattr(mgr, 'bridge', None)
            if bridge is None or not bridge.is_connected:
                threading.Event().wait(1.0)
                continue
            msg = bridge.receive(timeout=0.1)
            if msg and msg.get("type") == "voice":
                voice_handler = get_voice_handler()
                voice_handler.handle_voice_message(msg)
        except Exception as e:
            logger.error(f"Error in voice listener: {e}")
            threading.Event().wait(1.0)
    logger.info("Voice message listener stopped")


def _start_voice_listener():
    global _voice_running, _voice_thread
    if _voice_running:
        return
    _voice_running = True
    _voice_thread = threading.Thread(target=_voice_message_listener, daemon=True, name="voice-listener")
    _voice_thread.start()
    logger.info("Voice listener started")


def _stop_voice_listener():
    global _voice_running, _voice_thread
    _voice_running = False
    if _voice_thread:
        _voice_thread.join(timeout=2.0)
        _voice_thread = None
    logger.info("Voice listener stopped")


def install_voice_hook():
    global _voice_initialized
    if _voice_initialized:
        return
    logger.info("Installing voice hook...")
    _start_voice_listener()
    _voice_initialized = True
    logger.info("Voice hook installed")


def uninstall_voice_hook():
    global _voice_initialized
    _stop_voice_listener()
    _voice_initialized = False


install_voice_hook()
