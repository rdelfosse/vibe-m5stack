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
# 512 octets bruts (~32 ms) -> ligne base64+JSON ~740 chars : dimensionné pour
# la queue RX de 512 octets de BluetoothSerial côté device (drainée chaque
# frame de 16 ms — un chunk de 1 Ko produisait des lignes d'1,4 Ko qui ne
# pouvaient jamais y tenir entières, tronquées en silence).
# ⚠️ Une ligne tts_audio arrive au device en UN événement SPP, et la queue RX
# de BluetoothSerial fait 512 octets : la ligne entière (JSON + base64) doit
# tenir dessous, sinon la fin de CHAQUE chunk est jetée par le callback.
# 256 o de µ-law → ~390 o de ligne. 256/0.016 = 16 Ko/s : EXACTEMENT le temps
# réel — plus vite, le buffer device (10 s max) finit par saturer sur les
# lectures longues (intégrale) ; le pré-buffer de 1,5 s absorbe la gigue.
CHUNK_SIZE = 256
PACING_INTERVAL = 0.016


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


def clean_and_truncate_text(text: str, max_chars: int = 4000) -> str:
    """
    Clean text for TTS (P2 — lecture intégrale, décision rdelfosse 2026-08-10).

    - Remove markdown formatting
    - Remove code blocks
    - max_chars est un GARDE-FOU technique (timeout de synthèse 30 s, limites
      API), pas une limite produit : 4000 car. ≈ 4 min de parole. Un appui
      bouton interrompt la lecture à tout moment (P3).

    Args:
        text: The raw assistant message
        max_chars: Plafond de sécurité (default: 4000)

    Returns:
        Cleaned text
    """
    if not text:
        return ""
    
    # Remove code blocks (```...``` or ~~~...~~~) - preserve surrounding spaces
    text = re.sub(r'```.*?```', ' ', text, flags=re.DOTALL)
    text = re.sub(r'~~~.*?~~~', ' ', text, flags=re.DOTALL)
    
    # Remove inline code (`...`) - preserve surrounding spaces
    text = re.sub(r'`[^`]*`', ' ', text)
    
    # Remove markdown formatting - preserve surrounding spaces
    # Bold: **...** or __...
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    # Italic: *...* or _..._
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'_(?![_])([^_]+?)(?<![_])_', r'\1', text)
    # Strikethrough: ~~...~~
    text = re.sub(r'~~([^~]+)~~', r'\1', text)
    
    # Remove links and images - preserve surrounding spaces
    text = re.sub(r'\[[^\]]*\]\([^)]*\)', ' ', text)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', ' ', text)
    
    # Remove HTML tags - preserve surrounding spaces
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # Puces et marqueurs de liste : à l'oral ils ne se lisent pas.
    text = re.sub(r'[•▪◦‣]', ' ', text)
    text = re.sub(r'^\s*[-*]\s+', ' ', text, flags=re.MULTILINE)
    # Titres markdown (# ...)
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)

    # Tout aplatir en une seule ligne : la limite est max_chars, PAS le
    # premier paragraphe — une réponse structurée (intro + liste) ne doit
    # pas être réduite à sa phrase d'introduction.
    text = re.sub(r'\s+', ' ', text).strip()

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


# Encodeur µ-law : réutiliser celui de plugin/voice.py (une seule vérité).
from plugin.voice import _pcm16_to_ulaw as _voice_pcm16_to_ulaw


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
    """Encodeur G.711 µ-law (délègue à plugin.voice — une seule implémentation)."""
    return _voice_pcm16_to_ulaw(pcm)


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


def _lowpass_fir(pcm_values, current_rate, target_rate):
    """Passe-bas anti-repliement avant décimation (sinc fenêtré, 15 taps).

    Sans lui, l'interpolation 24→16 kHz replie le contenu > 8 kHz dans la
    bande audible — c'est le timbre « métallique/électronique » entendu sur
    le HP du Fire. Coupure à ~0,45 × le débit cible.
    """
    import math
    if current_rate <= target_rate or len(pcm_values) < 32:
        return pcm_values
    fc = 0.45 * target_rate / current_rate  # fréquence normalisée (0..0.5)
    n_taps = 15
    mid = n_taps // 2
    taps = []
    for i in range(n_taps):
        x = i - mid
        h = 2 * fc if x == 0 else math.sin(2 * math.pi * fc * x) / (math.pi * x)
        h *= 0.54 - 0.46 * math.cos(2 * math.pi * i / (n_taps - 1))  # Hamming
        taps.append(h)
    s = sum(taps)
    taps = [t / s for t in taps]
    n = len(pcm_values)
    out = [0] * n
    for i in range(n):
        acc = 0.0
        for j, t in enumerate(taps):
            k = i + j - mid
            if k < 0:
                k = 0
            elif k >= n:
                k = n - 1
            acc += t * pcm_values[k]
        out[i] = int(acc)
    return out


def _normalize_peak(pcm_values):
    """Normalisation crête à ~90 % de la pleine échelle.

    Le DAC du Fire n'a que 8 bits : un signal à mi-échelle joue moins fort
    ET gaspille de la résolution (voix plus granuleuse). Gain plafonné à 8x
    pour ne pas amplifier un passage quasi silencieux en souffle.
    """
    peak = max((abs(v) for v in pcm_values), default=0)
    if not 0 < peak < 29000:
        return pcm_values
    gain = min(29500 / peak, 8.0)
    return [max(-32768, min(32767, int(v * gain))) for v in pcm_values]


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
        pcm_values = _normalize_peak(struct.unpack(f'<{len(pcm_data) // 2}h', pcm_data))
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
    
    pcm_values = _normalize_peak(pcm_values)
    pcm_values = _lowpass_fir(pcm_values, current_rate, TARGET_SAMPLE_RATE)

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
        
        # Config vivante de l'agent loop OBLIGATOIRE : un VibeConfigSchema()
        # construit à vide ignore le config.toml réel et lève
        # MissingAPIKeyError chez les utilisateurs en login navigateur
        # (clé en keyring, pas en variable d'env).
        if vibe_config is None:
            logger.warning("TTS: pas de config Vibe disponible (tour jamais lancé ?)")
            return None
        
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
        
    except Exception:
        # JAMAIS de print/traceback vers stdout/stderr : ça pollue la TUI.
        logger.exception("Failed to create TTS client")
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

        # Debug : dernière synthèse décodée sur disque (audit qualité, comme
        # last_ptt.wav pour le micro). Jamais persisté hors debug explicite.
        from plugin import runtime_flags
        if runtime_flags.debug_enabled():
            try:
                from pathlib import Path
                from plugin.voice import ulaw_to_wav
                dump = Path.home() / ".vibe" / "logs" / "last_tts.wav"
                dump.write_bytes(ulaw_to_wav(ulaw_data))
                logger.info(f"[debug] TTS audio: {len(ulaw_data)} octets µ-law -> {dump}")
            except Exception:
                logger.exception("Could not dump last_tts.wav")
        
        # Send tts_stop first to cancel any previous playback
        try:
            broker_mgr.broker.bridge.send({"type": "tts_stop"})
        except Exception:
            pass
        
        # Stream in chunks with pacing
        chunk_size = CHUNK_SIZE
        total_size = len(ulaw_data)
        _state.total_chunks = (total_size + chunk_size - 1) // chunk_size
        _state.sent_chunks = 0
        
        for seq in range(_state.total_chunks):
            # Interruption (bouton device, nouveau tour) : arrêter NET —
            # sans ce check, un stream de 30 s continuerait dans le vide.
            if _state.cancel_event.is_set():
                logger.info(f"TTS stream cancelled at chunk {seq}/{_state.total_chunks}")
                # Prévenir le device : sans ce stop, les chunks déjà en vol
                # REDÉMARRENT la lecture qui attend ensuite des données pour
                # toujours (pastille qui clignote à vide).
                try:
                    broker_mgr.broker.bridge.send({"type": "tts_stop"})
                except Exception:
                    pass
                return False
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
            broker_mgr.broker.bridge.send(message)
            _state.sent_chunks += 1

            # Pacing par échéances : sous Windows, asyncio.sleep(0.015) dort
            # en réalité ~21 ms (granularité du timer) — un sleep fixe ne
            # tient que ~12 Ko/s alors que la lecture consomme 16 Ko/s
            # (buffer à sec → micro-silences, voix hachée). En visant
            # l'échéance absolue, les réveils tardifs sont rattrapés en
            # envoyant les chunks suivants dos à dos.
            if seq == 0:
                pacing_t0 = asyncio.get_running_loop().time()
            elif seq < _state.total_chunks - 1:
                target = pacing_t0 + seq * PACING_INTERVAL
                delay = target - asyncio.get_running_loop().time()
                if delay > 0:
                    await asyncio.sleep(delay)
        
        # Send end marker
        message = {
            "type": "tts_end",
            "total": _state.total_chunks
        }
        broker_mgr.broker.bridge.send(message)
        
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
        
        # Synthesize speech — timeout dur : un endpoint qui pend ne doit pas
        # laisser une task fantôme (c'était invisible dans les logs).
        logger.info(f"Synthesizing speech: {clean_text[:60]}...")
        t0 = time.monotonic()
        try:
            # 120 s : la lecture intégrale envoie jusqu'à 4000 car. — la
            # synthèse d'un texte long dépasse largement les 30 s initiaux.
            result = await asyncio.wait_for(tts.speak(clean_text), timeout=120.0)
        except asyncio.TimeoutError:
            logger.error("TTS speak() timeout (120 s)")
            return False
        except asyncio.CancelledError:
            logger.info("TTS annulé (nouveau tour ou stop)")
            raise
        logger.info(
            f"TTS: {len(result.audio_data)} octets en {time.monotonic() - t0:.1f}s, "
            f"magie={result.audio_data[:4]!r}"
        )
        
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
        
    except Exception:
        logger.exception("Speech failed")
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
