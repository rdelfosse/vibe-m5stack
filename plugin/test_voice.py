"""Tests du VoiceHandler (mock complet : ni micro, ni réseau, ni hardware).

Couvre les critères du brief voice :
  - prompt/approve -> injection de la transcription, jamais de resolve ;
  - reject -> resolve (id, False, consigne), jamais d'injection ;
  - transcription vide / voix indisponible -> fallback reject propre ;
  - la session se réarme (pas de PTT one-shot) et ne deadlocke pas.
"""
import threading
import time
from unittest.mock import patch

from plugin.voice_handler import VoiceHandler, DEFAULT_REJECT_REASON


class FakeVoiceInput:
    def __init__(self, wav=b"RIFF-fake-wav", text="corrige le test", available=True):
        self.wav = wav
        self.text = text
        self.available = available
        self.cancelled = False

    def record_start(self):
        return True

    def record_stop(self):
        return self.wav

    def is_available(self):
        return self.available

    def availability_detail(self):
        return f"fake available={self.available}"

    def transcribe_sync(self, wav_data):
        if isinstance(self.text, Exception):
            raise self.text
        return self.text

    def cancel(self):
        self.cancelled = True


class Recorder:
    """Espionne les callbacks du handler."""

    def __init__(self):
        self.injected = []
        self.resolved = []
        self.acks = []

    def inject(self, text):
        self.injected.append(text)

    def resolve(self, request_id, approved, text):
        self.resolved.append((request_id, approved, text))

    def ack(self, state, text=""):
        self.acks.append((state, text))


def make_handler(fake):
    with patch("plugin.voice_handler.get_voice_input", return_value=fake):
        handler = VoiceHandler()
    rec = Recorder()
    handler.set_inject_callback(rec.inject)
    handler.set_resolve_approval_callback(rec.resolve)
    handler.set_send_voice_ack_callback(rec.ack)
    return handler, rec


def run_session(handler, mode, request_id=0):
    handler.handle_voice_message(
        {"type": "voice", "action": "start", "mode": mode, "id": request_id}
    )
    handler.handle_voice_message(
        {"type": "voice", "action": "stop", "mode": mode, "id": request_id}
    )


def wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# -- Flux nominaux -----------------------------------------------------------

def test_prompt_injects_transcription():
    handler, rec = make_handler(FakeVoiceInput(text="ajoute des tests"))
    run_session(handler, "prompt")
    assert wait_until(lambda: rec.injected == ["ajoute des tests"])
    assert rec.resolved == []


def test_approve_injects_but_never_resolves():
    handler, rec = make_handler(FakeVoiceInput(text="pense au changelog"))
    run_session(handler, "approve", request_id=42)
    assert wait_until(lambda: rec.injected == ["pense au changelog"])
    assert rec.resolved == []  # l'approbation est résolue par le response device


def test_reject_resolves_no_with_reason_and_does_not_inject():
    handler, rec = make_handler(FakeVoiceInput(text="utilise plutot uv"))
    run_session(handler, "reject", request_id=7)
    assert wait_until(lambda: rec.resolved == [(7, False, "utilise plutot uv")])
    assert rec.injected == []  # le feedback EST la consigne, pas d'injection


def test_ack_sequence_transcribing_then_done_with_extract():
    handler, rec = make_handler(FakeVoiceInput(text="x" * 100))
    run_session(handler, "prompt")
    assert wait_until(lambda: ("done", "x" * 60) in rec.acks)
    assert rec.acks.index(("transcribing", "")) < rec.acks.index(("done", "x" * 60))


# -- Fallbacks ----------------------------------------------------------------

def test_reject_empty_transcription_uses_default_reason():
    handler, rec = make_handler(FakeVoiceInput(text="   "))
    run_session(handler, "reject", request_id=3)
    assert wait_until(lambda: rec.resolved == [(3, False, DEFAULT_REJECT_REASON)])


def test_reject_voice_unavailable_still_rejects():
    handler, rec = make_handler(FakeVoiceInput(available=False))
    run_session(handler, "reject", request_id=5)
    assert wait_until(lambda: len(rec.resolved) == 1)
    request_id, approved, reason = rec.resolved[0]
    assert (request_id, approved) == (5, False)
    assert DEFAULT_REJECT_REASON in reason


def test_reject_transcription_error_still_rejects():
    handler, rec = make_handler(FakeVoiceInput(text=RuntimeError("boom")))
    run_session(handler, "reject", request_id=9)
    assert wait_until(lambda: len(rec.resolved) == 1)
    assert rec.resolved[0][0] == 9 and rec.resolved[0][1] is False


def test_prompt_empty_audio_no_deadlock_and_no_inject():
    handler, rec = make_handler(FakeVoiceInput(wav=b""))
    done = threading.Event()

    def run():
        run_session(handler, "prompt")
        done.set()

    threading.Thread(target=run, daemon=True).start()
    # Régression deadlock : _cleanup_recording sous le verrou du caller.
    assert done.wait(2.0), "handle_voice_message deadlocked on empty audio"
    assert rec.injected == []
    assert ("done", "") in rec.acks


# -- Réarmement ----------------------------------------------------------------

def test_second_session_works_after_first():
    # Régression PTT one-shot : _recording doit être réarmé après un stop.
    handler, rec = make_handler(FakeVoiceInput(text="premiere"))
    run_session(handler, "prompt")
    assert wait_until(lambda: rec.injected == ["premiere"])

    handler._voice_input.text = "deuxieme"
    run_session(handler, "prompt")
    assert wait_until(lambda: rec.injected == ["premiere", "deuxieme"])


def test_stale_session_is_reset_on_new_start():
    # start sans stop (reboot device) puis nouvelle session complète.
    fake = FakeVoiceInput(text="apres reboot")
    handler, rec = make_handler(fake)
    handler.handle_voice_message(
        {"type": "voice", "action": "start", "mode": "prompt", "id": 0}
    )
    run_session(handler, "prompt")
    assert wait_until(lambda: rec.injected == ["apres reboot"])
    assert fake.cancelled  # la session zombie a été annulée proprement
