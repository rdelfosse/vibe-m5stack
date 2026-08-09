"""Vibe M5Stack - Voice hook integration"""
import asyncio
import logging
from typing import Any, Optional

from plugin.voice_handler import get_voice_handler
from plugin.vibe_m5stack_hook import get_or_init_broker

logger = logging.getLogger(__name__)

_voice_initialized = False


def install_voice_hook():
    global _voice_initialized
    if _voice_initialized:
        return
    logger.info("Installing voice hook...")
    _voice_initialized = True
    logger.info("Voice hook installed")


def uninstall_voice_hook():
    global _voice_initialized
    _voice_initialized = False


install_voice_hook()
