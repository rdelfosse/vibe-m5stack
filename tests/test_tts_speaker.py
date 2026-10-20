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
"""Tests du speaker TTS v0.7: synthese injectee, streaming µ-law, interruption.
"""

from __future__ import annotations

import asyncio
import base64
import io
import wave

from plugin import tts_speaker


def make_wav(samples: int = 512, rate: int = 16000) -> bytes:
    """Petit WAV PCM16 mono pour les tests."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x01\x00" * samples)
    return buffer.getvalue()


class FakeBridge:
    def __init__(self, vout="device", lang="fr", on_send=None) -> None:
        self.voice_out_mode = vout
        self.voice_lang = lang
        self.sent: list[dict] = []
        self._on_send = on_send

    def send(self, message):
        self.sent.append(message)
        if self._on_send is not None:
            self._on_send(self, message)
        return True


async def test_speak_streams_ulaw_chunks():
    bridge = FakeBridge()

    ok = await tts_speaker.speak("Bonjour le device", bridge, synth=lambda t, v: make_wav())

    assert ok is True
    types = [m["type"] for m in bridge.sent]
    assert types[0] == "tts_stop"
    assert types[-1] == "tts_end"
    audio = [m for m in bridge.sent if m["type"] == "tts_audio"]
    assert len(audio) == (512 + 255) // 256  # 512 samples = 512 octets µ-law
    # les chunks base64 rejouent l'integralite du flux µ-law (512 echantillons
    # 16k mono = 512 octets µ-law)
    joined = b"".join(base64.b64decode(m["data"]) for m in audio)
    assert len(joined) == 512
    assert bridge.sent[-1]["total"] == len(audio)


async def test_speak_respects_voice_out_mode():
    bridge = FakeBridge(vout="off")
    called = []

    def synth(text, voice):  # ne doit jamais etre appele
        called.append(text)
        return make_wav()

    ok = await tts_speaker.speak("texte", bridge, synth=synth)
    assert ok is False
    assert called == []
    assert bridge.sent == []


async def test_speak_interrupts_on_stop():
    """stop_all (bouton device) coupe le stream: tts_end jamais envoye."""
    import threading

    stop_signal = threading.Event()

    def on_send(bridge, message):
        if message["type"] == "tts_audio" and message["seq"] == 1:
            stop_signal.set()
            tts_speaker.stop_all()

    bridge = FakeBridge(on_send=on_send)

    ok = await tts_speaker.speak("texte long", bridge, synth=lambda t, v: make_wav(4096))

    assert ok is False
    types = [m["type"] for m in bridge.sent]
    assert "tts_end" not in types
    # au moins deux tts_stop: pre-stream + interruption
    assert types.count("tts_stop") >= 2
    # le stream s'arrete avant la fin
    audio_seqs = [m["seq"] for m in bridge.sent if m["type"] == "tts_audio"]
    assert len(audio_seqs) < (4096 + 255) // 256
