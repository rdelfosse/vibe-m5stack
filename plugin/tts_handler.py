"""
Vibe M5Stack - TTS Voice Output Handler
Copyright 2026 Romain Delfosse

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
"""
TTS Voice Output Handler for M5Stack device.

Handles:
- Text cleaning and truncation (P2)
- TTS synthesis via MistralTTSClient
- PC playback via sounddevice
- Device streaming via G.711 µ-law 16 kHz mono
- Voice Out configuration (Off/Device/PC)
"""

import asyncio
import base64
import io
import logging
import re
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from plugin import config as plugin_config

# Logger enfant de m5stack_hook -> écrit dans ~/.vibe/logs/m5stack_hook.log
logger = logging.getLogger("m5stack_hook.tts_handler")

# Target format for device streaming
TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1
TARGET_FORMAT = "ulaw"  # G.711 µ-law
CHUNK_SIZE = 1024  # ~64ms at 16kHz
PACING_INTERVAL = 0.060  # ~60ms between chunks


class VoiceOutMode(Enum):
    """Voice output mode."""
    OFF = "off"
    DEVICE = "device"
    PC = "pc"


@dataclass
class TTSState:
    """State for TTS playback."""
    is_playing: bool = False
    current_task: asyncio.Task | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    total_chunks: int = 0
    sent_chunks: int = 0


# Global state
_state = TTSState()
_tts_client = None


def _get_voice_out_mode() -> VoiceOutMode:
    """Get current Voice Out mode from plugin config."""
    try:
        mode_str = plugin_config.get_voice_out_mode()
        return VoiceOutMode(mode_str)
    except Exception:
        return VoiceOutMode.OFF


def _set_voice_out_mode(mode: VoiceOutMode) -> None:
    """Set Voice Out mode in plugin config."""
    try:
        plugin_config.set_voice_out_mode(mode.value)
    except Exception as e:
        logger.error(f"Failed to save voice_out config: {e}")


def _has_sounddevice() -> bool:
    """Check if sounddevice is available."""
    try:
        import sounddevice
        return True
    except ImportError:
        return False


def _has_mistralai() -> bool:
    """Check if mistralai SDK is available."""
    try:
        import mistralai
        return True
    except ImportError:
        return False


def _has_api_key() -> bool:
    """Check if Mistral API key is available."""
    try:
        from vibe.core.config.vibe_schema import resolve_api_key
        key = resolve_api_key("MISTRAL_API_KEY")
        if key:
            return True
    except Exception:
        pass
    return bool(Path.home().joinpath(".vibe", "m5stack_hook.log").parent.parent.joinpath(".mistral", "api_key").exists())


def is_tts_available() -> bool:
    """Check if TTS is available (has mistralai and API key)."""
    return _has_mistralai() and _has_api_key()


def clean_and_truncate_text(text: str, max_chars: int = 500) -> str:
    """
    Clean and truncate text for TTS (P2).
    
    - Remove markdown formatting
    - Remove code blocks
    - Truncate at first paragraph or ~max_chars, whichever comes first
    
    Args:
        text: The raw assistant message
        max_chars: Maximum characters to keep (default: 500)
        
    Returns:
        Cleaned and truncated text
    """
    if not text:
        return ""
    
    # Remove code blocks (```...``` or ~~~...~~~)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'~~~.*?~~~', '', text, flags=re.DOTALL)
    
    # Remove inline code (`...`)
    text = re.sub(r'`[^`]*`', '', text)
    
    # Remove markdown formatting
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)      # italic
    text = re.sub(r'__([^_]+)__', r'\1', text)       # underline
    text = re.sub(r'--([^-]+)--', r'\1', text)       # strikethrough
    
    # Remove links and images
    text = re.sub(r'\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Collapse multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    # Truncate at first paragraph (double newline) or max_chars
    first_paragraph_end = text.find('\n\n')
    if first_paragraph_end != -1:
        text = text[:first_paragraph_end]
    
    # Truncate to max_chars
    if len(text) > max_chars:
        # Try to truncate at sentence boundary
        last_period = text.rfind('.', 0, max_chars)
        last_exclamation = text.rfind('!', 0, max_chars)
        last_question = text.rfind('?', 0, max_chars)
        
        end_pos = max(last_period, last_exclamation, last_question)
        if end_pos > max_chars * 0.8:  # At least 80% of max_chars
            text = text[:end_pos + 1]
        else:
            text = text[:max_chars]
        text = text.rstrip() + "..."
    
    return text


# LUT for u-law encoding (from voice.py)
_ULAW_LUT = None


def _ulaw_lut():
    """Table G.711 µ-law -> PCM16 (256 entrées, construite une fois)."""
    global _ULAW_LUT
    if _ULAW_LUT is None:
        lut = []
        for byte in range(256):
            u = ~byte & 0xFF
            sign = u & 0x80
            exponent = (u >> 4) & 0x07
            mantissa = u & 0x0F
            sample = (((mantissa << 3) + 0x84) << exponent) - 0x84
            lut.append(-sample if sign else sample)
        _ULAW_LUT = lut
    return _ULAW_LUT


def _pcm16_to_ulaw(pcm: int) -> int:
    """Encodeur G.711 µ-law."""
    BIAS = 0x84
    CLIP = 32635
    sign = 0
    if pcm < 0:
        pcm = -pcm
        sign = 0x80
    if pcm > CLIP:
        pcm = CLIP
    pcm += BIAS
    exponent = 7
    mask = 0x4000
    while (pcm & mask) == 0 and exponent > 0:
        exponent -= 1
        mask >>= 1
    mantissa = (pcm >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def wav_to_pcm16(wav_data: bytes) -> tuple[bytes, int, int, int]:
    """
    Decode WAV data to PCM16.
    
    Returns:
        tuple of (pcm_data, sample_rate, channels, sample_width)
    """
    import wave
    import io
    
    wav_buffer = io.BytesIO(wav_data)
    with wave.open(wav_buffer, 'rb') as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frames = wav_file.readframes(wav_file.getnframes())
    
    return frames, sample_rate, channels, sample_width


def pcm16_to_ulaw_16k(pcm_data: bytes, current_rate: int, current_channels: int) -> bytes:
    """
    Convert PCM16 to G.711 µ-law 16 kHz mono.
    
    Args:
        pcm_data: Raw PCM16 data (little-endian)
        current_rate: Current sample rate
        current_channels: Current number of channels
        
    Returns:
        µ-law encoded data at 16 kHz mono
    """
    # If already 16kHz mono, just convert
    if current_rate == TARGET_SAMPLE_RATE and current_channels == TARGET_CHANNELS:
        # Convert PCM16 to u-law
        pcm_values = struct.unpack(f'<{len(pcm_data) // 2}h', pcm_data)
        ulaw_bytes = bytes([_pcm16_to_ulaw(pcm) for pcm in pcm_values])
        return ulaw_bytes
    
    # First, decode PCM16 to integer values
    pcm_values = struct.unpack(f'<{len(pcm_data) // 2}h', pcm_data)
    
    # Convert to mono if needed
    if current_channels > 1:
        # Simple downmix: average channels
        mono_values = []
        for i in range(0, len(pcm_values), current_channels):
            channel_samples = pcm_values[i:i+current_channels]
            mono_values.append(int(sum(channel_samples) / len(channel_samples)))
        pcm_values = mono_values
    
    # Resample to 16 kHz if needed
    if current_rate != TARGET_SAMPLE_RATE:
        import math
        old_len = len(pcm_values)
        new_len = int(old_len * TARGET_SAMPLE_RATE / current_rate)
        
        if new_len < 2:
            return b''
        
        resampled = bytearray(new_len)
        ratio = old_len / new_len
        
        if ratio > 1.5:
            # Decimation with averaging
            for i in range(new_len):
                a = int(i * ratio)
                b = int((i + 1) * ratio)
                if b <= a:
                    b = a + 1
                if b > old_len:
                    b = old_len
                seg = pcm_values[a:b]
                resampled[i] = _pcm16_to_ulaw(int(sum(seg) / len(seg)))
        else:
            # Interpolation
            step = (old_len - 1) / (new_len - 1) if new_len > 1 else 0
            for i in range(new_len):
                pos = i * step
                i0 = int(pos)
                frac = pos - i0
                i1 = min(i0 + 1, old_len - 1)
                pcm_val = int(pcm_values[i0] * (1 - frac) + pcm_values[i1] * frac)
                resampled[i] = _pcm16_to_ulaw(pcm_val)
        
        return bytes(resampled)
    
    # Convert to u-law
    ulaw_bytes = bytes([_pcm16_to_ulaw(pcm) for pcm in pcm_values])
    return ulaw_bytes


def wav_to_ulaw_16k(wav_data: bytes) -> bytes:
    """
    Convert WAV data to G.711 µ-law 16 kHz mono.
    
    Args:
        wav_data: WAV formatted audio data
        
    Returns:
        µ-law encoded data at 16 kHz mono
    """
    pcm_data, sample_rate, channels, sample_width = wav_to_pcm16(wav_data)
    
    # Ensure we have PCM16
    if sample_width != 2:
        # Need to convert sample width
        if sample_width == 1:
            # 8-bit PCM to 16-bit
            pcm_values = [((b - 128) << 8) for b in pcm_data]
            pcm_data = struct.pack(f'<{len(pcm_values)}h', *pcm_values)
        elif sample_width == 4:
            # 32-bit float to 16-bit (assuming -1.0 to 1.0)
            import struct
            float_values = struct.unpack(f'<{len(pcm_data) // 4}f', pcm_data)
            pcm_values = [int(f * 32767) for f in float_values]
            pcm_data = struct.pack(f'<{len(pcm_values)}h', *pcm_values)
    
    return pcm16_to_ulaw_16k(pcm_data, sample_rate, channels)


async def _get_tts_client(vibe_config=None):
    """Get or create TTS client.
    
    Args:
        vibe_config: Optional VibeConfigSchema instance. If not provided,
                     will attempt to create one.
    """
    global _tts_client
    
    if _tts_client is not None:
        return _tts_client
    
    if not is_tts_available():
        logger.warning("TTS not available: missing mistralai SDK or API key")
        return None
    
    try:
        from vibe.cli.tts import make_tts_client
        from vibe.app_server.config import AudioProviderView, TTSModelConfigView
        
        # Get the Vibe config
        if vibe_config is None:
            from vibe.core.config.vibe_schema import VibeConfigSchema
            vibe_config = VibeConfigSchema()
        
        # Get active TTS model
        tts_model_config = vibe_config.get_active_tts_model()
        tts_provider_config = vibe_config.get_tts_provider_for_model(tts_model_config)
        
        # Build AudioProviderView from TTSProviderConfig
        class _AudioProviderView:
            def __init__(self, provider_config):
                self.api_base = provider_config.api_base
                self.api_key_env_var = provider_config.api_key_env_var
                # client is not needed for our use case
                
        # Build TTSModelConfigView from TTSModelConfig
        class _TTSModelConfigView:
            def __init__(self, model_config):
                self.name = model_config.name
                self.voice = model_config.voice
                self.response_format = model_config.response_format
        
        provider = _AudioProviderView(tts_provider_config)
        model = _TTSModelConfigView(tts_model_config)
        
        _tts_client = make_tts_client(provider, model)
        return _tts_client
        
    except Exception as e:
        logger.error(f"Failed to create TTS client: {e}")
        import traceback
        traceback.print_exc()
        return None


async def play_on_pc(audio_data: bytes) -> bool:
    """
    Play audio on PC using sounddevice.
    
    Args:
        audio_data: Audio data (WAV format expected)
        
    Returns:
        True if playback started successfully, False otherwise
    """
    if not _has_sounddevice():
        logger.warning("sounddevice not available for PC playback")
        return False
    
    try:
        import sounddevice as sd
        
        # Decode WAV to get parameters
        pcm_data, sample_rate, channels, sample_width = wav_to_pcm16(audio_data)
        
        # Create a RawOutputStream
        # Note: We need to use RawOutputStream to avoid numpy dependency
        stream = sd.RawOutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype='int16',
            callback=None  # We'll use write instead
        )
        
        # For RawOutputStream, we need to write data
        # But it doesn't have a simple write method, so we'll use a different approach
        # Let's use a simple playback with a callback
        
        def callback(outdata, frames, time, status):
            chunksize = min(len(pcm_data) - _state.sent_chunks * frames * channels * 2, 
                          frames * channels * 2)
            if chunksize > 0:
                outdata[:chunksize] = pcm_data[_state.sent_chunks * frames * channels * 2:
                                              (_state.sent_chunks + 1) * frames * channels * 2]
                _state.sent_chunks += 1
                return
            raise sd.CallbackAbort
        
        # Reset sent chunks
        _state.sent_chunks = 0
        
        stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype='int16',
            callback=callback
        )
        
        with stream:
            _state.sent_chunks = 0
            while stream.active:
                await asyncio.sleep(0.1)
        
        return True
        
    except Exception as e:
        logger.error(f"PC playback failed: {e}")
        return False


async def stream_to_device(audio_data: bytes, broker_mgr) -> bool:
    """
    Stream audio to device as G.711 µ-law 16 kHz mono.
    
    Args:
        audio_data: Audio data (WAV format expected)
        broker_mgr: BrokerManager instance
        
    Returns:
        True if streaming started successfully, False otherwise
    """
    if broker_mgr is None:
        logger.warning("No broker manager for device streaming")
        return False
    
    try:
        # Convert to µ-law 16kHz mono
        ulaw_data = wav_to_ulaw_16k(audio_data)
        
        if not ulaw_data:
            logger.warning("Empty audio data after conversion")
            return False
        
        # Send tts_stop first to cancel any previous playback
        try:
            broker_mgr.broker.bridge.send_message({"type": "tts_stop"})
        except Exception:
            pass
        
        # Stream in chunks with pacing
        chunk_size = CHUNK_SIZE
        total_size = len(ulaw_data)
        _state.total_chunks = (total_size + chunk_size - 1) // chunk_size
        _state.sent_chunks = 0
        
        for seq in range(_state.total_chunks):
            start = seq * chunk_size
            end = min((seq + 1) * chunk_size, total_size)
            chunk = ulaw_data[start:end]
            
            # Encode as base64
            b64_chunk = base64.b64encode(chunk).decode('ascii')
            
            # Send chunk
            message = {
                "type": "tts_audio",
                "seq": seq,
                "data": b64_chunk
            }
            broker_mgr.broker.bridge.send_message(message)
            _state.sent_chunks += 1
            
            # Pace the sending
            if seq < _state.total_chunks - 1:
                await asyncio.sleep(PACING_INTERVAL)
        
        # Send end marker
        message = {
            "type": "tts_end",
            "total": _state.total_chunks
        }
        broker_mgr.broker.bridge.send_message(message)
        
        return True
        
    except Exception as e:
        logger.error(f"Device streaming failed: {e}")
        return False


async def speak_text(text: str, broker_mgr=None, vibe_config=None) -> bool:
    """
    Speak the given text using TTS.
    
    Handles:
    - Text cleaning and truncation
    - TTS synthesis
    - PC or Device playback based on configuration
    
    Args:
        text: The text to speak
        broker_mgr: BrokerManager instance (for device streaming and vout config)
        vibe_config: Optional VibeConfigSchema instance
        
    Returns:
        True if speech was successful, False otherwise
    """
    global _state
    
    # Get Voice Out mode from device (announced in pings/config messages)
    # If no device available, use local config as fallback
    mode = VoiceOutMode.OFF
    if broker_mgr is not None and hasattr(broker_mgr, 'bridge') and broker_mgr.bridge:
        vout = getattr(broker_mgr.bridge, 'voice_out_mode', None)
        if vout in ("off", "device", "pc"):
            mode = VoiceOutMode(vout)
    
    # Fallback to local config if no device mode available
    if mode == VoiceOutMode.OFF and broker_mgr is None:
        mode = _get_voice_out_mode()
    
    if mode == VoiceOutMode.OFF:
        return True  # Silently skip when Off
    
    # Clean and truncate text
    clean_text = clean_and_truncate_text(text)
    if not clean_text:
        logger.debug("No text to speak after cleaning")
        return True
    
    # Check if we can speak
    if not is_tts_available():
        logger.warning("TTS not available, skipping speech")
        return False
    
    # Cancel previous playback if any
    if _state.is_playing:
        _state.cancel_event.set()
        if _state.current_task:
            _state.current_task.cancel()
            try:
                await _state.current_task
            except asyncio.CancelledError:
                pass
        _state.is_playing = False
    
    # Reset state
    _state = TTSState()
    _state.is_playing = True
    
    try:
        # Get TTS client
        tts = await _get_tts_client(vibe_config)
        if tts is None:
            logger.warning("Could not create TTS client")
            return False
        
        # Synthesize speech
        logger.info(f"Synthesizing speech: {clean_text[:60]}...")
        result = await tts.speak(clean_text)
        
        # Handle result
        if mode == VoiceOutMode.PC:
            success = await play_on_pc(result.audio_data)
        elif mode == VoiceOutMode.DEVICE:
            success = await stream_to_device(result.audio_data, broker_mgr)
        else:
            success = True
        
        if success:
            logger.info("Speech completed successfully")
        else:
            logger.warning("Speech playback failed")
        
        return success
        
    except Exception as e:
        logger.error(f"Speech failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        _state.is_playing = False


def stop_playback() -> None:
    """Stop current TTS playback."""
    global _state
    if _state.is_playing:
        _state.cancel_event.set()
        if _state.current_task:
            _state.current_task.cancel()
        _state.is_playing = False
        logger.info("TTS playback stopped")


def get_voice_out_mode() -> VoiceOutMode:
    """Get current Voice Out mode."""
    return _get_voice_out_mode()


def set_voice_out_mode(mode: VoiceOutMode) -> None:
    """Set Voice Out mode."""
    _set_voice_out_mode(mode)


# Initialize LUT on import
_ulaw_lut()
