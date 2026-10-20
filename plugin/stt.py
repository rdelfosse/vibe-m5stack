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
"""Transcription Voxtral 3 par appel REST direct (v0.7, sans SDK mistralai).

Le 0.6 passait par le SDK; le proxy doit vivre dans n'importe quel env.
Modele par defaut: voxtral-mini-transcribe-3-0 (Voxtral 3, sortie
2026-10-20) — language omis par defaut: la detection est automatique et
couvre 35+ langues (doc "Migrate from Voxtral 2").
"""

from __future__ import annotations

import json
import logging
import os
import uuid
import urllib.error
import urllib.request

from plugin.tts_speaker import API_BASE, resolve_api_key

logger = logging.getLogger("vibe-m5stack.stt")

STT_MODEL = os.environ.get("M5STACK_STT_MODEL", "voxtral-mini-transcribe-3-0")
TRANSCRIBE_TIMEOUT_S = 30.0


def transcribe_sync(wav_data: bytes, *, language: str | None = None) -> str:
    """WAV -> texte via /audio/transcriptions. Retourne '' si indisponible."""
    key = resolve_api_key()
    if not key:
        logger.warning("STT: aucune cle Mistral API")
        return ""
    boundary = f"----m5stack{uuid.uuid4().hex}"
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )

    field("model", STT_MODEL)
    if language:
        field("language", language)
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"ptt.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode()
    )
    parts.append(wav_data)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)

    request = urllib.request.Request(
        f"{API_BASE}/audio/transcriptions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TRANSCRIBE_TIMEOUT_S) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode(errors="replace")[:200]
        except Exception:  # noqa: BLE001
            detail = ""
        logger.error("STT: HTTP %s: %s", exc.code, detail)
        return ""
    except Exception as exc:  # noqa: BLE001 - le TUI ne doit jamais mourir du STT
        logger.error("STT: %s", exc)
        return ""
    text = payload.get("text")
    if not text and payload.get("segments"):
        text = " ".join(seg.get("text", "") for seg in payload["segments"])
    return (text or "").strip()
