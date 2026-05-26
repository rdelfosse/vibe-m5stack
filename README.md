# appro-vibe

Approbation physique pour [Mistral Vibe CLI](https://mistral.ai/) via un M5Stack Fire.
Quand l'agent veut faire quelque chose de sensible (commit, push, écriture fichier
critique), un écran s'allume sur le M5Stack avec un chat Mistral qui danse et tu
valides au bouton. LEDs latérales + matrices NeoPixel optionnelles aux ports B/C
pour signaler l'attente.

```
PC (vibe-m5stack)  ──hook Python──>  plugin/vibe_m5stack_hook.py
                                              │
                                         USB Serial 115200
                                              ▼
                                      M5Stack Fire (firmware/)
                                         écran + boutons A/B/C
                                         + ring LED + (optionnel) NeoMatrix
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

---

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

Pour utiliser `vibe-m5stack` depuis n'importe quel dossier :

```bash
# Depuis la racine du repo
pip install -e .
```

Cela installe le package en mode editable et crée la commande globale :
- `vibe-m5stack` — lance Vibe avec le hook M5Stack

**Ajout au PATH (Windows PowerShell admin) :**
```powershell
$scriptsDir = "$env:USERPROFILE\AppData\Roaming\uv\tools\mistral-vibe\Scripts"
[Environment]::SetEnvironmentVariable("Path", "$env:Path;$scriptsDir", "User")
```

Après ça, tu peux lancer `vibe-m5stack` depuis n'importe quel projet.

### 2bis. Variables d'environnement obligatoires

| Variable | Obligatoire | Rôle |
|---|---|---|
| `M5STACK_PORT` | Oui (Windows) | Port serial où le M5Stack est branché. L'auto-detect a un bug connu (probe 1s vs ping firmware 5s, ~80% de chance de rater). Force toujours le port. |
| `VIBE_SESSION_NAME` | Non | Préfixe affiché sur l'écran M5Stack pour distinguer plusieurs sessions parallèles. ≤ 12 chars. Auto-généré (short UUID) sinon. |

**Set en permanent (PowerShell)** :
```powershell
[Environment]::SetEnvironmentVariable("M5STACK_PORT", "COM8", "User")
# Adapte COM8 selon ton port (Get-PnpDevice -Class Ports te le donne)

Set pour une session :
$env:M5STACK_PORT = "COM8"
$env:VIBE_SESSION_NAME = "mon-projet"
```

### 3. Tester

Avec l'installation globale :
```powershell
$env:M5STACK_PORT = "COM8"  # ou variable user permanente, voir 2bis
cd C:\un_projet_quelconque
vibe-m5stack
```

Dans la session vibe : demande quelque chose qui déclenche un write_file, par exemple :
"crée un fichier hello.txt avec le texte 'salut'".

L'écran M5Stack doit s'allumer avec [VIBE_SESSION_NAME] write hello.txt et un body
décrivant l'action. Appuie sur A = approve, B = reject, C = cancel.

En parallèle, la modal Textual de Vibe s'affiche aussi — c'est le filet de sécu
si le M5Stack est débranché. Tu peux répondre dans la modal OU sur le M5Stack,
le premier gagne.

### Plusieurs sessions Vibe en parallèle

Tu peux lancer `vibe-m5stack` dans plusieurs terminaux sur des projets différents.
Le bridge ouvre/ferme le port serial à chaque approval (mode éphémère + lock file
sur `~/.vibe/m5stack.lock`), donc les demandes sont sérialisées FIFO.

```powershell
# Terminal 1
cd C:\projets\alpha
$env:VIBE_SESSION_NAME = "alpha"
vibe-m5stack

# Terminal 2 (en parallèle)
cd C:\projets\beta
$env:VIBE_SESSION_NAME = "beta"
vibe-m5stack

L'écran M5Stack affiche [alpha] write foo.py ou [beta] git commit selon
qui demande. Si deux sessions demandent en même temps, la deuxième attend
que la première relâche le M5Stack (timeout 60s).
```

### Comment ça marche — le hook approval

`vibe-m5stack` lance Vibe normalement, mais charge avant un hook Python qui
monkey-patche `AgentLoop.set_approval_callback`. À chaque fois que Vibe va
demander une permission (write_file, bash mutant, search_replace, etc.), le
hook lance en parallèle :

1. La modal Textual native de Vibe (qui affiche dans le terminal)
2. Une requête au M5Stack via le bridge serial

**Le premier à répondre gagne.** Si tu appuies sur A sur le M5Stack, le Future
attendu par la modal Vibe est résolu via `self._pending_approval.set_result(...)`
et la modal se ferme automatiquement. Inversement, si tu réponds via le clavier
dans la modal Textual, la requête M5Stack est annulée.

**Si le M5Stack n'est pas branché ou pas joignable**, le hook se met en mode
"short-circuit" (retourne immédiatement NO côté M5Stack) et laisse la modal
Textual gérer seule. Pas de blocage 30s, fallback transparent.

Code : `plugin/vibe_m5stack_hook.py`, fonction `_patched_approval_callback`.

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

### Animation "shake"

Secouer physiquement le M5Stack pendant qu'il est en IDLE déclenche pendant 800 ms
une animation où le chat Mistral tremble (offset aléatoire ±8 px). Détection via
l'IMU (MPU6886) intégré, seuil ~3.5g (`firmware/src/inputs/imu.h`). Plus du tout
de signification fonctionnelle, juste un easter egg.

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
    │   ├── imu.{h,cpp}            IMU MPU6886 pour la détection de mouvement (shake)
    │   └── leds.{h,cpp}           FastLED — ring 10 + matrix B + matrix C
    └── serial/
        └── protocol.{h,cpp}       JSON in/out, filtrage ping/response par id

plugin/                            Python — pont serial ↔ Vibe
├── __main__.py                   Entrypoint console (`vibe-m5stack`)
├── bridge.py                      M5StackBridge: auto-detect port, thread reader, mode éphémère + lock file
├── m5stack_utils.py               SessionManager pour multi-session
├── vibe_m5stack_hook.py           Hook approval (monkey-patch AgentLoop.set_approval_callback)
├── vibe_hook.py                   legacy console fallback (avant MCP)
├── mcp_server.py                  Server MCP stdio asyncio — optionnel, désactivé par défaut
└── requirements.txt
```

### Protocole série

PC → M5Stack (1 ligne JSON terminée `\n`) :
```json
{"type":"approval","id":12345,"title":"Commit","body":"..."}
{"type":"credit_info","percent":45}
```

M5Stack → PC :
```json
{"type":"response","id":12345,"approved":true}
{"type":"response","id":12345,"approved":false,"cancelled":true}
{"type":"ping"}    // toutes les 5s en IDLE
```

Le bridge Python **filtre** les pings et **matche par id** la réponse (pour ne pas
prendre un ping pour une approbation). Mode éphémère : ouvre/ferme le port à
chaque requête avec un lock file pour la synchronisation multi-session.

---

## API Mistral — endpoint d'usage manquant

**L'API publique Mistral (`api.mistral.ai`) n'expose aucun endpoint d'usage /
quota Vibe.** Tous les chemins évidents répondent 404 :
`/v1/usage`, `/v1/credits`, `/v1/billing`, `/v1/account`, `/v1/organizations`.

L'info existe pourtant : la console web Mistral l'utilise en interne via
`https://console.mistral.ai/api/billing/v2/vibe-usage` (réponse JSON propre
avec champ `usage_percentage`). Mais cet endpoint :

- N'est pas documenté dans l'OpenAPI public
- Refuse l'API key Bearer standard
- Exige une **session cookie Ory + header CSRF token** (auth web frontend)

**Solution adoptée** : le hook lit `agent_loop.stats.context_tokens` en
direct (data interne Vibe) et envoie au M5Stack via le protocole `credit_info`
existant. Plus de dépendance à un cookie web fragile. Roadmap pour
l'implémenter, voir section précédente.

---

## Limites connues

- **Auto-détect port serial bugué** : probe timeout 1s alors que le firmware ping
toutes les 5s → ~80% de chance de rater. **Set `M5STACK_PORT` explicitement**
(voir 2bis). Fix futur : passer probe à 6s ou ping actif côté PC.
- **Brown-out au premier MCP** avec NeoPixel branchés + alim USB faiblarde →
prendre un chargeur 1A+.
- **Port C inutilisable si PSRAM activée** dans `platformio.ini` (GPIO 16/17
réservées). Le firmware actuel a PSRAM commentée.
- **NeoMatrix** : code assume 50 LEDs par matrice. Adapter `MATRIX_LEDS` dans
`leds.cpp:14` si différent.
- **Repo dans OneDrive/Dropbox/iCloud → casse les venv Python**. Mettre le repo
hors d'un dossier sync cloud (ex: `C:\Users\<user>\github\`).

---

## Roadmap / idées

- Jauge "saturation context" en temps réel via `agent_loop.stats._listeners`
  (afficher % du context vs `auto_compact_threshold` du modèle)
- Auto-detect port plus fiable (probe 6s ou ping actif côté PC)
- Profil d'agent Vibe distribuable (`~/.vibe/agents/m5stack.toml`)
- Word-wrap automatique des `body` longs dans l'écran d'approbation
- Animation matrices plus riche

---

## Licence

MIT.
