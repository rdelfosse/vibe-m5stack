# Tests

Suite pytest pour les fonctions de logique pure. Pas de M5Stack physique requis.

## Lancement

```bash
# Depuis la racine du repo, avec le Python du venv mistral-vibe
"%USERPROFILE%\AppData\Roaming\uv\tools\mistral-vibe\Scripts\python.exe" -m pytest tests/

# Ou si pytest est dans le PATH
pytest tests/

# Un fichier en particulier
pytest tests/test_bridge_probe.py -v
```

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
| test_hook_format.py | format_tool_info (path/content/command extraction) |

## Non couvert

- Firmware C++ (besoin du hardware)
- Race avec _pending_approval Future (besoin event loop Textual)
- LEDs, animation, shake

## Critères d'acceptation

- [x] `pytest tests/ -q` passe avec 0 fail
- [x] Temps total < 5 s (pas de `time.sleep` réel > 100 ms dans les tests)
- [x] ≥ 15 tests au total répartis sur les 4 fichiers
- [x] Aucun test ne touche au `~/.vibe/m5stack.lock` réel (utiliser `tmp_path` ou path tmp)
- [x] Aucun test ne tente d'ouvrir un vrai port serial (tout passe par `patch_serial`)
- [x] `pip install -e ".[test]"` install proprement pytest
