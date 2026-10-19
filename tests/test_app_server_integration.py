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
"""Tests d'integration du client compagnon et du proxy app server (Vibe 3.x).

Chaine complete en protocole pur, sans LLM ni materiel:
    client -> (proxy) -> fake app server (tests/fake_app_server.py)
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
from pathlib import Path

import pytest

from plugin.app_server_client import (
    DECISION_APPROVE,
    ApprovalRequest,
    AppServerClient,
)
from plugin.app_server_proxy import ApprovalRouter, EnvApprover

REPO_ROOT = Path(__file__).resolve().parents[1]
FAKE_SERVER = REPO_ROOT / "tests" / "fake_app_server.py"


def fake_server_command(record_path: Path) -> list[str]:
    return [sys.executable, str(FAKE_SERVER)]


def read_records(record_path: Path) -> list[dict]:
    if not record_path.exists():
        return []
    return [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines() if line]


async def drive_session(client: AppServerClient, *, cwd: str) -> None:
    await client.start()
    await client.initialize()
    session_id = await client.session_start(cwd=cwd)
    assert session_id == "s-fake"
    queue_item = await client.turn_enqueue("cree cible.txt")
    assert queue_item == "q-fake-1"
    assert await client.wait_turn_done(timeout=30.0) is True


async def test_client_answers_approval(tmp_path):
    """Le client compagnon arbitre lui-meme l'approbation."""
    record = tmp_path / "record.jsonl"
    seen: list[ApprovalRequest] = []

    async def approve(approval: ApprovalRequest) -> str:
        seen.append(approval)
        return DECISION_APPROVE

    env = os.environ.copy()
    env["FAKE_SERVER_RECORD"] = str(record)
    client = AppServerClient(fake_server_command(record), on_approval=approve, env=env)
    await drive_session(client, cwd=str(tmp_path))
    await client.close()

    assert len(seen) == 1
    assert seen[0].tool == "file_system.write_file"
    decisions = [e for e in read_records(record) if e["event"] == "callback_result"]
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "approve"


def proxy_command(record_path: Path, *, mode: str, tui: bool = True) -> tuple[list[str], dict]:
    """Commande du proxy + env: le proxy lance le fake app server en enfant."""
    env = os.environ.copy()
    env["M5STACK_APPROVAL_MODE"] = mode
    env["VIBE_M5STACK_REAL_APP_SERVER"] = " ".join(shlex.quote(part) for part in fake_server_command(record_path))
    env["VIBE_M5STACK_LOG"] = "WARNING"
    if not tui:
        env["M5STACK_APPROVAL_TUI"] = "0"
    env["FAKE_SERVER_RECORD"] = str(record_path)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return [sys.executable, "-m", "plugin.app_server_proxy"], env


async def test_proxy_auto_approve(tmp_path):
    """Le proxy arbitre (auto-approve) alors que le client reste silencieux."""
    record = tmp_path / "record.jsonl"
    seen: list[ApprovalRequest] = []

    async def silent(approval: ApprovalRequest) -> None:
        seen.append(approval)
        return None  # la TUI ne repond pas: le proxy doit arbitrer

    command, env = proxy_command(record, mode="auto-approve")
    client = AppServerClient(command, on_approval=silent, env=env)
    await drive_session(client, cwd=str(tmp_path))
    await client.close()

    # le callback a bien ete transmis au client (la TUI l'afficherait)
    assert len(seen) == 1
    assert seen[0].callback_id == "cb-fake-1"
    # et c'est bien le proxy qui a envoye la decision au serveur
    decisions = [e for e in read_records(record) if e["event"] == "callback_result"]
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "approve"
    assert decisions[0]["callbackId"] == "cb-fake-1"


async def test_proxy_device_only(tmp_path):
    """M5STACK_APPROVAL_TUI=0: le client ne voit aucun callback."""
    record = tmp_path / "record.jsonl"

    async def fail_if_called(approval: ApprovalRequest) -> None:
        raise AssertionError("la TUI ne doit pas voir l'approbation en mode device-only")

    command, env = proxy_command(record, mode="auto-deny", tui=False)
    client = AppServerClient(command, on_approval=fail_if_called, env=env)
    await drive_session(client, cwd=str(tmp_path))
    await client.close()

    decisions = [e for e in read_records(record) if e["event"] == "callback_result"]
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "deny"


async def test_router_tui_first_wins():
    """La TUI repond avant le device: la decision du device est oubliee."""
    sent: list[dict] = []

    async def send_result(params: dict) -> dict:
        sent.append(params)
        return {"accepted": True}

    router = ApprovalRouter(EnvApprover(DECISION_APPROVE), send_result)
    approval = ApprovalRequest(
        callback_id="cb-1", session_id="s", tool="t", choices=["approve", "deny"]
    )
    router.tui_answered("cb-1")
    await router.offer(approval)
    await asyncio.sleep(0.1)
    assert sent == []  # deja arbitree: rien n'est envoye


async def test_router_device_first_wins():
    """Le device repond avant la TUI: la decision part, le retardataire est noie."""
    sent: list[dict] = []

    async def send_result(params: dict) -> dict:
        sent.append(params)
        return {"accepted": True}

    router = ApprovalRouter(EnvApprover(DECISION_APPROVE), send_result)
    approval = ApprovalRequest(
        callback_id="cb-1", session_id="s", tool="t", choices=["approve", "deny"]
    )
    await router.offer(approval)
    for _ in range(50):
        if sent:
            break
        await asyncio.sleep(0.02)
    assert len(sent) == 1
    output = sent[0]["result"]["output"]
    assert output["decision"]["type"] == "approve"
    router.tui_answered("cb-1")  # la TUI repond trop tard: sans effet
    assert len(sent) == 1
