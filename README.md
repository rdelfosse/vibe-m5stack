# appro-vibe

Approbation physique pour [Mistral Vibe CLI](https://mistral.ai/) via un M5Stack Fire.
Quand l'agent veut faire quelque chose de sensible (commit, push, écriture fichier
critique), un écran s'allume sur le M5Stack avec un cat Mistral qui danse et tu
valides au bouton. LEDs latérales + matrices NeoPixel optionnelles aux ports B/C
pour signaler l'attente.

```
PC (vibe)  ──MCP stdio JSON-RPC──>  plugin/mcp_server.py
                                            │
                                       USB Serial 115200
                                            ▼
                                    M5Stack Fire (firmware/)
                                       écran + boutons A/B/C
                                       + ring LED + NeoMatrix
```

---

## Hardware requis

| Composant | Rôle | Pin |
|---|---|---|
| **M5Stack Fire** | Affichage, boutons, MCU ESP32 | — |
| (optionnel) NeoMatrix 5×10 sur Port B | Flood color Mistral | GPIO 26 |
| (optionnel) NeoMatrix 5×10 sur Port C | Flood color Mistral | GPIO 17 |
| Câble USB-C (Type C → A) | Lien PC ↔ M5Stack + alim | — |

**Important alim** : avec les NeoPixel branchés, prévoir un chargeur USB **1A+**.
Un port USB 2.0 de PC (500 mA) suffit pour le firmware seul mais peut provoquer
un brown-out reset au premier allumage des LEDs.

## Software requis

- **PlatformIO Core** (CLI, pas l'IDE) : https://platformio.org/install/cli
- **Python 3.10+**
- **Mistral Vibe CLI** installé via `uv tool install mistral-vibe` (https://docs.mistral.ai/)
- **gh** CLI si tu veux créer le repo GitHub depuis le terminal

---

## Quick start

### 1. Cloner et flasher le firmware

```bash
git clone https://github.com/rdelfosse/appro-vibe.git
cd appro-vibe/firmware

# Ajuster monitor_port = COM8 dans platformio.ini selon ton port
# (Linux/Mac: /dev/ttyUSB0 ou /dev/cu.SLAB_USBtoUART)

pio run -t upload
pio device monitor   # optionnel, pour voir les logs
```

Au boot, séquence diagnostique : 🔴 800 ms → 🟢/🔵 5 s (stats RAM) → puis le cat
Mistral danse sur fond rainbow. Si tu vois ça, le firmware tourne.

### 2. Installer le plugin Python

```bash
cd ../plugin
pip install -r requirements.txt
# (Optionnel) test direct sans Vibe :
python test_bridge.py
```

`test_bridge.py` envoie une demande factice au M5Stack. Si l'écran d'approbation
s'affiche et un appui A renvoie `{approved: true}` → bridge OK.

### 3. Brancher le MCP server à Vibe

Ajouter ce bloc à `~/.vibe/config.toml` (à la racine, pas dans une section) :

```toml
[[mcp_servers]]
transport = "stdio"
name = "m5stack"
command = "python"
args = ["-m", "plugin.mcp_server"]
cwd = "/abs/path/to/appro-vibe"     # adapter
startup_timeout_sec = 15.0
tool_timeout_sec = 60.0
```

**Pièges courants** :
- Le champ `transport = "stdio"` est obligatoire (discriminator Pydantic, sinon
  Vibe rejette silencieusement)
- `cwd` doit pointer vers le repo cloné pour que `from plugin.bridge import ...` résolve
- Si tu utilises un venv, mets le `python.exe` absolu du venv dans `command`
- **Ne jamais** garder `mcp_servers = []` ailleurs dans le fichier — conflit TOML

### 4. (Optionnel) Configurer Vibe pour appeler le tool systématiquement

Sans instructions, Vibe n'appelle l'outil `m5stack_request_human_approval` que si
tu le lui demandes explicitement. Pour qu'il l'utilise avant chaque action sensible,
ajouter dans `~/.vibe/instructions.md` :

```markdown
Before any git history-modifying op (commit, push, rebase), destructive shell
command, write to *.env/*.config/*.lock, or PR creation/merge, call
`m5stack_request_human_approval` first. Proceed only if `approved: true`.
```

(Le repo contient un exemple complet dans `plugin/mcp_config_example.toml`.)

### 5. Tester

```bash
vibe
```

Dans la session : *"appelle l'outil `m5stack_request_human_approval` avec
title='hello' body='depuis vibe'"*.
Le M5Stack doit afficher la demande, LEDs s'allument, A → `approved: true`
revient à Vibe.

---

## Configuration / personnalisation

| Quoi | Où |
|---|---|
| Couleurs Mistral (rainbow) | `firmware/src/display/gif_animator.cpp` (anim) + `firmware/src/display/screen.cpp` (approval) + `firmware/src/inputs/leds.cpp` (LEDs) |
| Vitesse du chase LED ring | `leds.cpp:updateApprovalAnimation` — `> 180` (ms entre steps) |
| Vitesse cycle couleur matrices | `leds.cpp` — `> 400` |
| Brightness LEDs / cap courant | `leds.cpp:begin()` — `setBrightness(32)` + `setMaxPowerInVoltsAndMilliamps(5, 400)` |
| Taille / position logo Mistral | `screen.cpp:drawRequestFrame` — `LOGO_SCALE` |
| Polices texte écran | FreeFonts inclues dans M5Stack lib (FreeSans / FreeSansBold 9/12/18 pt) |
| Logo Mistral pixel art | `firmware/src/display/mistral_logo.h` (transcription du SVG officiel) |

---

## Architecture

```
firmware/                          Arduino/PlatformIO, board m5stack-fire
├── platformio.ini                 M5Stack + ArduinoJson + FastLED
└── src/
    ├── main.cpp                   State machine: IDLE (anim) ↔ SHOWING_REQUEST
    ├── display/
    │   ├── anim.h                 ChatAnimator wrapper
    │   ├── gif_animator.{h,cpp}   pushImage direct + recomposition rainbow par bande
    │   ├── gif_frames.h           27 frames 240×240 RGB565 (≈3 MB en flash)
    │   ├── mistral_logo.h         10 rects du logo "M" Mistral
    │   ├── screen.{h,cpp}         ApprovalScreen (rendu titre/body/boutons)
    │   └── ...
    ├── inputs/
    │   ├── buttons.{h,cpp}        Wrapper boutons + vibration
    │   └── leds.{h,cpp}           FastLED — ring 10 + matrix B + matrix C
    └── serial/
        └── protocol.{h,cpp}       JSON in/out, filtrage ping/response par id

plugin/                            Python — pont serial ↔ Vibe
├── bridge.py                      M5StackBridge: auto-detect port, thread reader, request_approval()
├── mcp_server.py                  Server MCP stdio asyncio — outil request_human_approval
├── vibe_hook.py                   Hook console legacy (sans MCP)
├── test_bridge.py                 Test manuel direct
└── requirements.txt
```

### Protocole série

PC → M5Stack (1 ligne JSON terminée `\n`) :
```json
{"type":"approval","id":12345,"title":"Commit","body":"..."}
```

M5Stack → PC :
```json
{"type":"response","id":12345,"approved":true}
{"type":"response","id":12345,"approved":false,"cancelled":true}
{"type":"ping"}    // toutes les 5s en IDLE
```

Le bridge Python **filtre** les pings et **matche par id** la réponse (pour ne pas
prendre un ping pour une approbation).

---

## Limites connues

- **MCP ne capte que les outils que l'agent décide d'appeler**. Les approbations
  natives de Vibe (bash, write_file, search_replace) passent par sa TUI Textual et
  ne touchent pas le M5Stack. L'instruction dans `instructions.md` aide mais ne
  garantit rien — l'agent peut oublier.
- **Couverture totale** = passer par ACP (Agent Client Protocol). En cours,
  voir `Roadmap`.
- **Brown-out au premier MCP** avec NeoPixel branchés + alim USB faiblarde →
  prendre un chargeur 1A+.
- **Port C inutilisable si PSRAM activée** dans `platformio.ini` (GPIO 16/17
  réservées). Le firmware actuel a PSRAM commentée.
- **NeoMatrix** : code assume 50 LEDs par matrice. Adapter `MATRIX_LEDS` dans
  `leds.cpp:14` si différent.

## Roadmap

- **Phase 2 — ACP** : remplacer la TUI Vibe par un client ACP custom qui spawn
  `vibe-acp.exe`, intercepte 100 % des `RequestPermissionRequest` JSON-RPC et
  les forward au M5Stack. Plus aucune action sensible ne passe sans le bouton.
- Animation matrices plus riche (motif M reconnaissable une fois le mapping
  serpentin connu)
- Word-wrap automatique des `body` longs dans l'écran d'approbation
- Profil d'instructions Vibe distribuable (`~/.vibe/agents/m5stack.toml`)

## Licence

MIT.
