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
"""Lecture TTS des reponses de l'agent sur le M5Stack (v0.7).

Decouple du package ``vibe``: cle API resolue par env, puis keyring via
``vibe.utils.api_keys`` si importable (facultatif), puis ~/.vibe/.env.
Synthese par appel REST direct a l'API Voxtral TTS, streaming µ-law 16 kHz
identique au 0.6 (meme protocole firmware: tts_stop / tts_audio / tts_end).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Awaitable, Callable

from plugin.tts_handler import (
    CHUNK_SIZE,
    PACING_INTERVAL,
    VOICE_BY_LANG,
    clean_and_truncate_text,
    wav_to_ulaw_16k,
)

logger = logging.getLogger("vibe-m5stack.tts")

API_BASE = os.environ.get("M5STACK_TTS_API_BASE", "https://api.mistral.ai/v1")
# Voxtral 3 (sorti le 2026-10-20): les voice_ids de la generation precedente
# (fr_marie_neutral, gb_jane_neutral) restent valides sur ce modele (verifie
# sur l'API). Surcharger via M5STACK_TTS_MODEL pour tester une autre version.
TTS_MODEL = os.environ.get("M5STACK_TTS_MODEL", "voxtral-mini-tts-3-0")
SYNTH_TIMEOUT_S = 30.0

#: TTS en cours: interruption par tts_stop du device ou par un nouveau tour.
_current_cancel: threading.Event | None = None
_current_lock = threading.Lock()


def resolve_api_key() -> str | None:
    """Cle Mistral: env > keyring vibe (si importable) > ~/.vibe/.env."""
    key = os.environ.get("MISTRAL_API_KEY")
    if key:
        return key
    try:  # keyring (login navigateur) — present si le proxy vit dans le tool env
        from vibe.utils.api_keys import resolve_api_key as vibe_resolve  # type: ignore

        key = vibe_resolve("MISTRAL_API_KEY")
        if key:
            return key
    except Exception:  # noqa: BLE001 - facultatif
        pass
    env_file = Path.home() / ".vibe" / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("MISTRAL_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("'\"") or None
        except OSError:
            pass
    return None


def synth_wav(text: str, voice: str) -> bytes:
    """Synthese REST Voxtral TTS -> WAV (bloquant, appeler en thread)."""
    key = resolve_api_key()
    if not key:
        raise RuntimeError("aucune cle Mistral API pour le TTS")
    payload = json.dumps(
        {
            "model": TTS_MODEL,
            "input": text,
            "voice_id": voice,
            "response_format": "wav",
        }
    ).encode()
    request = urllib.request.Request(
        f"{API_BASE}/audio/speech",
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=SYNTH_TIMEOUT_S) as response:
        body = response.read()
    # Le SDK renvoie {"audio_data": "<b64>"}; tolere le WAV brut.
    try:
        decoded = json.loads(body)
        if isinstance(decoded, dict) and decoded.get("audio_data"):
            return base64.b64decode(decoded["audio_data"])
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    if body[:4] == b"RIFF":
        return body
    raise RuntimeError("reponse TTS inattendue (ni audio_data ni WAV)")


def stop_all() -> None:
    """Interrompt la lecture en cours (bouton device, nouveau tour)."""
    with _current_lock:
        if _current_cancel is not None:
            _current_cancel.set()


def _voice_for(bridge: Any) -> str:
    lang = getattr(bridge, "voice_lang", None) or "fr"
    return VOICE_BY_LANG.get(lang, VOICE_BY_LANG["fr"])


#: Choix d'emotion heuristique selon le ton de la reponse (fr uniquement:
#: variants de Marie verifiees sur l'API ; jane n'a pas encore d'emoctions
#: confirmees — rester en neutral pour les autres langues).
EMOTION_VARIANTS = {
    "fr": {
        "neutral": "fr_marie_neutral",
        "happy": "fr_marie_happy",
        "sad": "fr_marie_sad",
        "excited": "fr_marie_excited",
        "angry": "fr_marie_angry",
    }
}

_EMOTION_MARKERS = {
    "angry": (
        "je refuse", "refus", "interdit", "danger", "jamais", "aucun cas",
        "ne dois pas", "attention",
    ),
    "sad": (
        "erreur", "echec", "échec", "impossible", "desole", "désolé",
        "echoue", "échoué", "raté", "bug", "cassé", "inconnu", "absent",
    ),
    "happy": (
        "reussi", "réussi", "parfait", "succes", "succès", "bravo",
        "génial", "genial", "fonctionne", "super", "corrigé", "créé",
    ),
    "excited": (
        "gagné", "incroyable", "excellent", "enfin", "voilà",
        "merveilleux", "fantastique",
    ),
}


def pick_voice(text: str, lang: str) -> str:
    """Choisit la voix (et son emotion) selon le ton du texte.

    Heuristique locale, sans appel LLM: les mots marqueurs votent, les
    points d'exclamation boostent l'excitation. Egalite ou aucun marqueur:
    neutral — la voix du menu reste la reference par defaut.
    """
    variants = EMOTION_VARIANTS.get(lang)
    if variants is None:
        return VOICE_BY_LANG.get(lang, VOICE_BY_LANG["fr"])
    lowered = text.lower()
    scores = {
        emotion: sum(lowered.count(marker) for marker in markers)
        for emotion, markers in _EMOTION_MARKERS.items()
    }
    scores["excited"] += lowered.count("!")
    best = max(scores, key=lambda e: scores[e])
    if scores[best] == 0:
        return variants["neutral"]
    return variants[best]


async def speak(
    text: str,
    bridge: Any,
    *,
    synth: Callable[[str, str], bytes] | None = None,
) -> bool:
    """Lit un texte sur le device: synthese puis stream µ-law pace.

    ``synth`` injecte la fonction de synthese (tests). Retourne False si
    la voix est desactivee (voice_out_mode != "device") ou en cas d'echec.
    Une nouvelle lecture interrompt la precedente.
    """
    mode = getattr(bridge, "voice_out_mode", None)
    if mode != "device":
        logger.info("TTS ignore (voice_out_mode=%r)", mode)
        return False

    clean = clean_and_truncate_text(text)
    if not clean:
        return False

    stop_all()
    with _current_lock:
        cancel = threading.Event()
        global _current_cancel
        _current_cancel = cancel

    synth_fn = synth or synth_wav
    try:
        lang = getattr(bridge, "voice_lang", None) or "fr"
        voice = pick_voice(clean, lang)
        logger.info("voix choisie: %s (lang=%s)", voice, lang)
        wav = await asyncio.to_thread(synth_fn, clean, voice)
        if cancel.is_set():
            return False
        ulaw = await asyncio.to_thread(wav_to_ulaw_16k, wav)
        if not ulaw:
            logger.warning("TTS: audio vide apres conversion")
            return False
        return await _stream_to_device(ulaw, bridge, cancel)
    except Exception as exc:  # noqa: BLE001 - le TUI ne doit jamais mourir du TTS
        logger.warning("TTS echoue: %s", exc)
        return False
    finally:
        with _current_lock:
            if _current_cancel is cancel:
                _current_cancel = None


async def _stream_to_device(ulaw: bytes, bridge: Any, cancel: threading.Event) -> bool:
    """Chunks base64 pace (meme contrat que le 0.6, cf. tts_handler)."""
    try:
        bridge.send({"type": "tts_stop"})
    except Exception:  # noqa: BLE001
        pass
    total_chunks = (len(ulaw) + CHUNK_SIZE - 1) // CHUNK_SIZE
    pacing_t0 = asyncio.get_running_loop().time()
    for seq in range(total_chunks):
        if cancel.is_set():
            logger.info("TTS interrompu au chunk %s/%s", seq, total_chunks)
            try:
                bridge.send({"type": "tts_stop"})
            except Exception:  # noqa: BLE001
                pass
            return False
        chunk = ulaw[seq * CHUNK_SIZE : (seq + 1) * CHUNK_SIZE]
        bridge.send(
            {"type": "tts_audio", "seq": seq, "data": base64.b64encode(chunk).decode("ascii")}
        )
        if seq < total_chunks - 1:
            target = pacing_t0 + seq * PACING_INTERVAL
            delay = target - asyncio.get_running_loop().time()
            if delay > 0:
                await asyncio.sleep(delay)
    bridge.send({"type": "tts_end", "total": total_chunks})
    logger.info("TTS diffuse: %s chunks", total_chunks)
    return True
