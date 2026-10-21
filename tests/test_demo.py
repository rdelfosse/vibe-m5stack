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
"""Tests du mode démo PC (vibe-m5stack demo)."""

from __future__ import annotations

from plugin import demo, tts_speaker


def test_histoire_coherente():
    voices = [voice for voice, _ in demo.HISTOIRE]
    texts = [text for _, text in demo.HISTOIRE]
    assert len(demo.HISTOIRE) >= 8
    # chaque scène: une voix marie valide et un texte non vide accentué
    for voice, text in demo.HISTOIRE:
        assert voice in tts_speaker.EMOTION_VARIANTS["fr"].values()
        assert text and text == text.strip()
    assert any("é" in t for t in texts)  # accents conservés
    assert set(voices) >= {"fr_marie_neutral", "fr_marie_happy", "fr_marie_sad", "fr_marie_excited", "fr_marie_angry"}


def test_demo_sans_device(monkeypatch):
    """Aucun port -> message clair, code 1, pas d'exception."""
    monkeypatch.setattr("plugin.config.resolve_port", lambda: None)
    assert demo.run() == 1


async def test_play_story_avec_synth_injecte():
    """L'histoire se joue scène par scène: voix de mise en scène + états
    écran/LED poussés avant chaque lecture."""
    played: list[tuple[str, object]] = []

    class FakeBridge:
        voice_out_mode = "device"
        voice_lang = "fr"

        def send(self, message):
            played.append((message.get("type"), message.get("seq")))
            return True

        def send_status(self, state, detail="", seq=0, activity=""):
            played.append(("status", {"state": state, "activity": activity, "seq": seq}))
            return True

    def fake_synth(text, voice):
        played.append(("synth", voice))
        from tests.test_tts_speaker import make_wav

        return make_wav()

    await demo.play_story(FakeBridge(), synth=fake_synth)

    synths = [p for p in played if p[0] == "synth"]
    assert len(synths) == len(demo.HISTOIRE)
    # les voix passées au synth sont celles de la mise en scène, pas pick_voice
    assert [s[1] for s in synths] == [voice for voice, _ in demo.HISTOIRE]
    # chaque scène est précédée d'un statut écran/LED correspondant
    statuses = [p[1] for p in played if p[0] == "status"]
    attendus = [demo.EMOTION_SHOW[demo._emotion_of(v)] for v, _ in demo.HISTOIRE]
    assert len(statuses) == len(attendus) + 1  # + le statut final
    for i, (state, activity) in enumerate(attendus):
        assert statuses[i]["state"] == state
        assert statuses[i]["activity"] == activity
    # final: retour au repos
    assert statuses[-1]["state"] == "done"
