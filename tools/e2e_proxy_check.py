#!/usr/bin/env python3
# Vibe M5Stack - E2E check: client -> proxy -> vrai vibe-app-server
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
"""E2E reel du proxy v0.7: client compagnon -> proxy -> vibe-app-server.

Un tour LLM complet avec approbation interceptee par le proxy, sans
materiel (M5STACK_APPROVAL_MODE=auto-approve|auto-deny).

Usage (python du venv mistral-vibe, depuis la racine du repo):
    <venv>/Scripts/python.exe tools/e2e_proxy_check.py [approve|deny]
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from plugin.app_server_client import AppServerClient  # noqa: E402

DECISION = sys.argv[1] if len(sys.argv) > 1 else "speak"
SPEAK_MODE = DECISION == "speak"
MODE = "off" if SPEAK_MODE else ("auto-approve" if DECISION == "approve" else "auto-deny")
if SPEAK_MODE:
    PROMPT = (
        "Ne cree aucun fichier. Reponds uniquement par cette phrase exacte: "
        "bonjour, je suis la voix de ton agent sur le M5Stack."
    )
else:
    PROMPT = (
        "Cree le fichier cible.txt dans le repertoire de travail avec le contenu "
        "'e2e proxy'. Utilise l'outil write_file. Reponds juste OK ensuite."
    )


def log(msg: str) -> None:
    print(f"[e2e {time.strftime('%H:%M:%S')}] {msg}", flush=True)


async def main() -> int:
    if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    workdir = Path(tempfile.mkdtemp(prefix="m5stack-e2e-"))
    env = os.environ.copy()
    env["M5STACK_APPROVAL_MODE"] = MODE
    env["PYTHONPATH"] = str(REPO_ROOT)
    env.setdefault("VIBE_M5STACK_LOG", "INFO")
    # M5STACK_STATUS reste par defaut "device": avec un M5Stack branche, ce
    # test pousse aussi les statuts et lit la reponse en TTS sur le device.

    proxy_command = [sys.executable, "-m", "plugin.app_server_proxy"]
    client = AppServerClient(proxy_command, client_name="vibe-m5stack-e2e", env=env)

    log(f"workdir: {workdir} | mode proxy: {MODE}")
    await client.start()
    await client.initialize()
    session_id = await client.session_start(cwd=str(workdir), agent="ask")
    log(f"session: {session_id}")
    await client.turn_enqueue(PROMPT)
    log("tour enfile, attente de l'approbation interceptee par le proxy...")

    done = await client.wait_turn_done(timeout=240.0)
    log(f"turn/completed: {done}")

    state = await client.session_read()
    if state:
        for entry in state.get("state", {}).get("history") or []:
            if entry.get("role") == "assistant":
                for block in entry.get("content") or []:
                    if block.get("type") == "text" and block.get("text"):
                        log(f"assistant: {block['text'][:200]}")

    if SPEAK_MODE:
        # le proxy attend la lecture TTS pendant son close(): on lui laisse
        # le temps de diffuser avant de quitter (cf. attente dans close()).
        log("attente de la lecture TTS cote device...")
        await asyncio.sleep(12)
        log("SUCCES (TTS)")
        return 0

    cible = workdir / "cible.txt"
    exists = cible.exists()
    log(f"cible.txt present: {exists}")
    await client.close()

    if DECISION == "approve" and not exists:
        log("ECHEC: approve mais fichier absent")
        return 1
    if DECISION == "deny" and exists:
        log("ECHEC: deny mais fichier present")
        return 1
    log("SUCCES")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
