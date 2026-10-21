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
"""Mode démo piloté par PC: l'histoire de Salem sur le M5Stack.

Sans Vibe, sans session: ``vibe-m5stack demo`` connecte le device et joue
l'histoire en voix émotionnelles (Marie, Voxtral 3). Chaque scène porte sa
propre voix — c'est une mise en scène, pas une lecture au ton détecté.
Le mode démo autonome (firmware, sans PC) reste la vitrine écran/LEDs.
"""

from __future__ import annotations

import asyncio
import logging

from plugin import tts_speaker as t

logger = logging.getLogger("vibe-m5stack.demo")

#: Histoire de Salem, le chat qui garde les approbations.
#: Chaque scene: (voix Voxtral 3, texte).
HISTOIRE = [
    ("fr_marie_neutral", "Il était une fois, sur un bureau en désordre, un petit M5Stack Fire nommé Salem. Un chat qui parlait aux machines."),
    ("fr_marie_neutral", "Chaque jour, Salem gardait la porte du royaume des agents. Rien ne passait sans lui."),
    ("fr_marie_neutral", "Un soir, un agent osa murmurer deux mots redoutables : commit et push."),
    ("fr_marie_excited", "Salem s'illumina ! Son écran s'alluma, et son double de pixels se mit à danser !"),
    ("fr_marie_angry", "Mais l'agent voulait pousser sur la branche principale sans aucune revue ! Salem grondait : non ! Je refuse !"),
    ("fr_marie_sad", "Parfois, quand personne ne branchait son câble, Salem se sentait bien seul, au fond du tiroir."),
    ("fr_marie_happy", "Puis l'humain appuyait sur le bouton A, et tout redevenait magnifique !"),
    ("fr_marie_excited", "Approbation accordée ! Les LEDs vibraient de joie, et le dépôt était sauvé !"),
    ("fr_marie_neutral", "Depuis ce jour, à chaque tour de l'agent, Salem veille, affiche, et répond d'une voix claire."),
    ("fr_marie_happy", "Et ils approuvèrent tous ensemble, sans jamais forcer de push. Fin."),
]

PAUSE_ENTRE_SCENES_S = 1.2


#: Mise en scene: l'emotion de la voix pilote l'ecran et les LEDs
#: (le chat danse pendant thinking, pastille de parole pendant le TTS,
#: palette d'activites differente par scene — cf. firmware protocol).
EMOTION_SHOW = {
    "neutral": ("thinking", "reasoning"),
    "excited": ("thinking", "streaming"),
    "angry": ("thinking", "tool_exec"),
    "sad": ("waiting", ""),
    "happy": ("done", ""),
}


def _emotion_of(voice: str) -> str:
    return voice.rsplit("_", 1)[-1] if "_" in voice else "neutral"


async def play_story(bridge, *, synth=None) -> None:
    """Joue l'histoire sur le device, scène par scène.

    Chaque scène met la scène au sens propre: l'état écran/LED correspondant
    à l'émotion est poussé AVANT la lecture, le chat danse pendant que Salem
    parle."""
    synth = synth or t.synth_wav
    seq = 0
    for voice, texte in HISTOIRE:
        state, activity = EMOTION_SHOW.get(_emotion_of(voice), ("thinking", "reasoning"))
        seq += 1
        try:
            bridge.send_status(state, "", seq, activity)
        except Exception as exc:  # noqa: BLE001 - la mise en scene n'est pas vitale
            logger.warning("mise en scene: %s", exc)
        # voix de scène imposée: le synth injecté ignore celle de speak()
        ok = await t.speak(texte, bridge, synth=lambda _text, _voice: synth(texte, voice))
        if not ok:
            logger.warning("scene abandonnee (voix=%s)", voice)
            return
        await asyncio.sleep(PAUSE_ENTRE_SCENES_S)
    seq += 1
    try:
        bridge.send_status("done", "", seq)
    except Exception:  # noqa: BLE001
        pass
    logger.info("histoire terminee (%d scenes)", len(HISTOIRE))


def run() -> int:
    """Entry point de ``vibe-m5stack demo``. Retourne un code de sortie."""
    from plugin.bridge import M5StackBridge
    from plugin.config import resolve_port

    port = resolve_port()
    if not port:
        print("Aucun M5Stack détecté — branche le device puis relance: vibe-m5stack demo", flush=True)
        return 1

    bridge = M5StackBridge(auto_connect=False)
    if not bridge.connect(port):
        print(f"Connexion impossible sur {port}", flush=True)
        return 1
    # La démo est une vitrine explicite: on force la lecture device même si
    # le menu Voice Out est sur off (le TTS est le propos de la démo).
    bridge.voice_out_mode = "device"
    bridge.voice_lang = "fr"
    print(f"Renard prend la parole sur {port} ({len(HISTOIRE)} scènes)...", flush=True)
    asyncio.run(play_story(bridge))
    bridge.close()
    print("Fin de l'histoire.", flush=True)
    return 0
