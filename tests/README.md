<!--
Vibe M5Stack - M5Stack integration for Mistral Vibe CLI
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
-->
# Tests

Suite pytest pour les fonctions de logique pure. Pas de M5Stack physique requis.

## Lancement

```bash
# Depuis la racine du repo
uv run --with pytest --with pytest-asyncio python -m pytest

# Ou avec le Python du venv mistral-vibe (pytest installé via -e ".[test]")
"%USERPROFILE%\AppData\Roaming\uv\tools\mistral-vibe\Scripts\python.exe" -m pytest

# Ou si pytest est dans le PATH
pytest

# Un fichier en particulier
pytest tests/test_bridge_probe.py -v
```

Le même suite tourne en CI : `.github/workflows/tests.yml` (Python 3.12 + 3.13).

## Installation

```bash
# Installer les dépendances de test
pip install -e ".[test]"
```

## Couverture

| Module | Quoi |
|--------|------|
| test_session_manager.py | SessionManager (préfixe titre, env var, truncate) |
| test_bridge_probe.py | _probe_port (JSON ping, timeout, garbage, exception) |
| test_bridge_ping_filter.py | request_approval (filtre ping, match par id) |
| test_bridge.py | M5StackBridge (send/receive, lock, éphémère) |
| test_broker.py | OwnerBroker, ClientProxy, BrokerManager (élection owner) |
| test_cli.py | Commandes `vibe-m5stack` (checks doctor, setup) |
| test_config.py | Résolution port (env > config > auto-detect) |
| test_hook_format.py | format_tool_info (path/content/command extraction) |
| test_hook_race.py | Course device vs TUI (_race_m5stack_approval) |
| test_integration.py | Patchs AgentLoop.act / VibeApp.__init__ au load du hook |
| test_mcp_server.py | Serveur MCP stdio (JSON-RPC initialize/tools) |
| test_status.py | map_event_to_status (états, seq, classification activité) |
| test_tts.py | TTS Voice Out (nettoyage texte, WAV → µ-law) |
| test_voice.py | VoiceHandler (dictée PC, callbacks injection) |

Les tests utilisent les vrais modules `mistral-vibe` (dépendance dure du
plugin depuis la 0.5.1) — pas de stubs `sys.modules`, fragiles selon l'ordre
de collecte.

## Non couvert

- Firmware C++ (besoin du hardware)
- Diagnostic matériel : voir `tools/test_bridge_hw.py` (script manuel, pas un
  test pytest — il ouvre le vrai port série)
- LEDs, animation, shake

## Critères d'acceptation

- [x] `pytest` passe avec 0 fail (129 tests)
- [x] Aucun test ne touche au `~/.vibe/m5stack.lock` réel (utiliser `tmp_path` ou path tmp)
- [x] Aucun test ne tente d'ouvrir un vrai port serial (tout passe par `patch_serial`)
- [x] `pip install -e ".[test]"` install proprement pytest
