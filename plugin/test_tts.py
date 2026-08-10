"""Tests du TTS Voice Out (fonctions pures + annulation du stream).

Ni réseau, ni hardware : la synthèse Voxtral n'est pas testée ici, seulement
le nettoyage du texte (P2), la conversion audio et la mécanique d'envoi.
"""
import asyncio
import io
import math
import struct
import wave

from plugin.tts_handler import (
    clean_and_truncate_text,
    wav_to_ulaw_16k,
    stream_to_device,
    _state,
)


# -- Nettoyage / troncature (P2) ----------------------------------------------

def test_reads_full_text_up_to_safety_cap():
    # Lecture intégrale (révision P2 du 2026-08-10) : un texte de 2000 car.
    # passe entier ; seul le garde-fou technique de 4000 car. tronque.
    out = clean_and_truncate_text("mot " * 500)
    assert len(out) == 1999
    out_long = clean_and_truncate_text("mot " * 2000)
    assert len(out_long) <= 4005  # 4000 + ellipse


def test_code_blocks_are_stripped():
    text = "Voilà le résultat :\n```python\nprint('secret')\n```\nC'est corrigé."
    out = clean_and_truncate_text(text)
    assert "print" not in out and "```" not in out
    assert "C'est corrigé" in out


def test_markdown_is_flattened():
    out = clean_and_truncate_text("**Gras** et [lien](https://x.y) et `inline`")
    assert "**" not in out and "](" not in out and "`" not in out
    assert "Gras" in out


def test_code_only_text_gives_empty():
    assert clean_and_truncate_text("```\nfoo\n```").strip() == ""


# -- Conversion audio -----------------------------------------------------------

def make_wav(rate=24000, channels=1, seconds=0.5, freq=440):
    buf = io.BytesIO()
    n = int(rate * seconds)
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            s = int(12000 * math.sin(2 * math.pi * freq * i / rate))
            for _ in range(channels):
                frames += struct.pack("<h", s)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def test_wav_24k_mono_resampled_to_16k_ulaw():
    ulaw = wav_to_ulaw_16k(make_wav(rate=24000, channels=1, seconds=0.5))
    # 0,5 s à 16 kHz µ-law = ~8000 octets (tolérance bords de resampling)
    assert abs(len(ulaw) - 8000) < 200


def test_wav_stereo_downmixed():
    ulaw = wav_to_ulaw_16k(make_wav(rate=16000, channels=2, seconds=0.25))
    assert abs(len(ulaw) - 4000) < 200


# -- Stream device : annulation --------------------------------------------------

class FakeBridge:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)
        return True


class FakeBroker:
    def __init__(self):
        self.bridge = FakeBridge()


class FakeMgr:
    def __init__(self):
        self.broker = FakeBroker()


def test_stream_cancel_stops_sending():
    mgr = FakeMgr()
    _state.cancel_event = asyncio.Event()
    _state.cancel_event.set()  # annulation demandée avant le stream
    ok = asyncio.run(stream_to_device(make_wav(seconds=2.0), mgr))
    assert ok is False
    # Seul le tts_stop initial est parti, aucun chunk audio
    types = [m["type"] for m in mgr.broker.bridge.sent]
    assert "tts_audio" not in types
    _state.cancel_event = asyncio.Event()  # reset pour les autres tests


def test_stream_sends_chunks_and_end():
    mgr = FakeMgr()
    _state.cancel_event = asyncio.Event()
    ok = asyncio.run(stream_to_device(make_wav(seconds=0.2), mgr))
    assert ok is True
    types = [m["type"] for m in mgr.broker.bridge.sent]
    assert "tts_audio" in types
    assert types[-1] == "tts_end"
