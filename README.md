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
# vibe-m5stack

Approbation physique pour [Mistral Vibe CLI](https://mistral.ai/) via un M5Stack Fire.
Quand l'agent veut faire quelque chose de sensible (commit, push, écriture fichier
critique), un écran s'allume sur le M5Stack avec un chat Mistral qui danse et tu
valides au bouton. LEDs latérales + matrices NeoPixel optionnelles aux ports B/C
pour signaler l'attente.

> 📝 **Article complet** : [Un bouton physique pour valider les actions des agents IA](https://www.romaindelfosse.fr/blog/m5stack-vibe-bouton-physique-agents-ia/) — contexte, démo et retour d'expérience.

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

#### 1.a. Pré-requis : driver USB

Le M5Stack Fire utilise une puce **Silicon Labs CP210x**. Sans le driver, l'OS
ne voit pas le device.

- **Windows** : installer https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers
  puis vérifier :
  ```powershell
  Get-PnpDevice -Class Ports -Status OK | Where-Object Name -like "*CP210*"
  ```
  Une ligne avec `(COMx)` doit apparaître après branchement USB.
- **Linux** : module `cp210x` en kernel standard, rien à installer.
  Vérifier après branchement : `dmesg | tail -20` → `cp210x converter now attached to ttyUSB0`.
- **Mac** : driver dans le même installer Silicon Labs, ou `brew install --cask silicon-labs-vcp-driver`.

#### 1.b. Installer PlatformIO Core

Pas l'IDE, juste le CLI. Si pas déjà fait :

```bash
pip install -U platformio
# ou via pipx pour isoler :
pipx install platformio
```

Vérifier : `pio --version` doit retourner `PlatformIO Core, version 6.x`.

#### 1.c. Cloner et identifier le port

```bash
git clone https://github.com/rdelfosse/vibe-m5stack.git
cd vibe-m5stack/firmware
```

Trouver le port serial du M5Stack :

```powershell
# Windows
Get-PnpDevice -Class Ports -Status OK | Where-Object Name -like "*CP210*"
# → Name : Silicon Labs CP210x USB to UART Bridge (COM8)  →  COM8
```

```bash
# Linux/Mac
ls /dev/tty* | grep -E "USB|usbserial|SLAB"
# → /dev/ttyUSB0 (Linux) ou /dev/cu.SLAB_USBtoUART (Mac)
```

Édite `platformio.ini` ligne `monitor_port =` avec ton port (le `upload_port`
est auto-détecté).

#### 1.d. Compiler et flasher

```bash
pio run -t upload
pio device monitor   # optionnel, pour voir les logs et messages JSON
```

**La première compile prend 1 à 3 minutes** : PlatformIO télécharge M5Stack
(~50 MB), FastLED, ArduinoJson et le toolchain ESP32 (~250 MB cumul). Les
compiles suivantes prennent ~10 s grâce au cache local. Si la console semble
figée 30 s sans output, c'est probablement un téléchargement, attends.

#### 1.e. Validation visuelle

Juste après l'upload, le M5Stack reboote automatiquement. Tu dois voir :

| Phase | Durée | Affichage | Signification |
|---|---|---|---|
| 1 | 0.8 s | 🔴 Rouge plein écran | `M5.begin()` OK, LCD répond |
| 2 | 5 s | 🟢 Vert ou 🔵 Bleu avec stats (`sprite: OK`, `dram: ...`) | Sprite d'animation alloué (vert) ou échec (bleu — vérifier `dram` vs `need`) |
| 3 | ∞ | **Chat Mistral pixel art** dansant sur 5 bandes rainbow | Mode IDLE, firmware tourne |

**Si tu vois le chat, le firmware est correctement flashé.** Reste à brancher le plugin Python (étape 2).

#### 1.f. Troubleshooting upload

| Erreur | Cause | Fix |
|---|---|---|
| `Failed to connect to ESP32: Timed out waiting for packet header` | M5Stack ne répond pas en mode bootloader | Maintiens le bouton **Reset** enfoncé, lance `pio run -t upload`, relâche dès "Connecting..." apparaît |
| `Access is denied` / `PermissionError(13)` sur le port | Port occupé par un autre process (souvent `pio device monitor` resté ouvert) | Ferme tous les terminaux qui écoutent le port. Sur Windows : `Get-Process` puis `Stop-Process` sur les pio résiduels |
| `Could not open <port>, the port doesn't exist` | Mauvais COM dans `platformio.ini` ou driver pas installé | Re-vérifie 1.a puis 1.c |
| `Écran reste noir après flash` | Câble USB sans data (charge only) ou flash incomplète | Essaie un autre câble USB-C → A, retry `pio run -t upload` |
| `Get-PnpDevice` montre le CP210x mais `Status: Unknown` / `Present: False`, écran allumé et chat danse pourtant | Câble USB charge-only (très fréquent sur câbles bon marché ou livrés avec accessoires non-data). Le M5Stack tire son 5V mais les paires data USB ne passent pas → Windows ne voit aucun device fonctionnel. | Changer le câble pour un câble USB-C → A clairement data (celui d'un smartphone qui fait la sync PC, ou le câble M5Stack d'origine). Un câble data déclenche le "ding" Windows de re-énumération à chaque branchement ; un câble charge-only reste silencieux. |
| `sprite: FAIL` en phase 2 du canary | DRAM insuffisante au moment de `createSprite` | Vérifie la valeur `dram` affichée vs `need`. Possible bug de fragmentation, fais un reset hardware (bouton Reset) puis re-flash |

#### 1.g. Note PSRAM (avancé, optionnel)

Le firmware **désactive la PSRAM par défaut** (`board_build.psram` est commenté
dans `platformio.ini`) pour libérer GPIO 16/17 = Port C, utilisé par les
NeoPixel optionnels. Si tu n'as **pas** de NeoMatrix sur Port C et veux plus
de RAM disponible, décommente la ligne dans `platformio.ini` et re-flash.

#### 1.h. Mode wireless Bluetooth Classic (SPP)

Sur certains laptops (typiquement chipsets Intel USB 3.1 sur Lenovo ThinkPad),
**chaque ouverture du port serial provoque un `POWERON_RESET` du M5Stack** —
la pile USB Windows cycle VBUS au moment de l'open, le M5Stack reboot, l'approval
JSON envoyé immédiatement après est perdu pendant le boot, timeout 35s. Symptôme
visible : à chaque approval, écran du M5Stack passe par la séquence canary (rouge
→ vert → chat) et l'approval n'arrive jamais. Un câble data correct, un port
USB 3.0 direct, un hub alimenté, et l'alim secteur ne changent rien. Cause :
chipset/driver USB de l'hôte, pas le M5Stack.

**Solution durable** : mode Bluetooth Classic SPP. Le M5Stack expose un service
Bluetooth nommé `M5Stack-Vibe`, Windows assigne un COM virtuel après pairing,
et `bridge.py` lit ce COM exactement comme un serial USB — aucune modification
côté Python. Le M5Stack est alimenté par n'importe quel chargeur USB-C (pas
besoin de data sur le câble d'alim) → 0 reset, jamais.

Trade-offs :
- Tu **perds `pio device monitor` over USB** (le firmware n'écoute plus le serial
  USB en mode BT). Pour debugger en série il faut repasser temporairement en USB,
  voir ci-dessous.
- Pairing Windows à faire 1×.
- Latence approval +~50 ms (imperceptible vs serial USB).
- Le firmware BT alourdit le binaire (~280 KB) et consomme ~30 KB DRAM supplémentaires.

##### Activer le mode BT

Le switch est dans `firmware/src/serial/serial_io.h` :

```cpp
#ifndef USE_BT_SERIAL
#define USE_BT_SERIAL 1   // 1 = Bluetooth Classic SPP, 0 = USB serial
#endif
```

Sur la branche `feat/bt-serial`, c'est déjà à `1` par défaut. Sur `main`, c'est
à `0` (USB) — flip à `1` si tu veux le mode wireless.

> ⚠️ **Le mode BT exige la PSRAM activée.** Le stack Bluetooth (Bluedroid) a
> besoin de ~50 KB de heap contigu pour `btc_spp_init`. Avec le sprite
> d'animation (115 KB) qui sature le DRAM, l'allocation BT crashe en
> `Guru Meditation Error: LoadProhibited` dans `tlsf_block_size_max` au boot
> (symptôme : reboot loop "canary → rainbow → canary", `sprite: OK` mais pas de
> chat). Sur la branche `feat/bt-serial`, `board_build.psram = enable` est déjà
> décommenté dans `platformio.ini` (le sprite part en PSRAM, le DRAM reste libre
> pour le BT). Conséquence : GPIO 16/17 = Port C réservés, la matrix C NeoPixel
> est désactivée dans `leds.cpp`. Si tu actives le BT sur `main`, pense à
> décommenter `board_build.psram = enable` toi-même.

Re-flasher :

```bash
cd firmware
pio run -t upload
```

L'upload se fait toujours par USB (le bootloader ESP32 reste sur USB serial,
seul le firmware applicatif bascule en BT). Donc tu gardes le câble data branché
pendant l'upload.

##### Pairing Windows

1. **Reset le M5Stack** (bouton rouge côté gauche) pour qu'il redémarre en BT.
2. Sur Windows : `Paramètres` → `Bluetooth et appareils` → `Ajouter un appareil`
   → `Bluetooth` → attends `M5Stack-Vibe` dans la liste → clique → `Se connecter`.
   Pas de code de pairing demandé (mode "just works").
3. Windows assigne 2 COM ports au device pairé (incoming + outgoing). **Note les deux**
   dans `Get-PnpDevice -Class Ports`. Celui à utiliser est le **outgoing**, en général
   le numéro le plus haut des deux.

```powershell
Get-PnpDevice -Class Ports -Status OK | Where-Object Name -like "*Standard Serial*" | Format-List Name
# → "Standard Serial over Bluetooth link (COM11)"  → outgoing
# → "Standard Serial over Bluetooth link (COM12)"  → incoming, ignorer
```

Astuce de test rapide pour savoir lequel : ouvre le COM le plus haut, attends
6s, tu dois voir un `{"type":"ping"}` (le firmware envoie un ping toutes les 5s).
Sinon essaie l'autre.

##### Mettre à jour M5STACK_PORT

```powershell
[Environment]::SetEnvironmentVariable("M5STACK_PORT", "COM11", "User")
# Ferme ce terminal et ouvre-en un nouveau pour que la var soit prise en compte
```

C'est tout. Lance `vibe-m5stack` dans un terminal neuf, le bridge se connecte
au COM BT exactement comme avant.

##### Repasser temporairement en USB (debug)

Pour faire `pio device monitor` ou diagnostiquer un truc côté firmware :

1. Édite `firmware/src/serial/serial_io.h` → `#define USE_BT_SERIAL 0`
2. `pio run -t upload` (le binaire repasse en USB serial pur)
3. `pio device monitor` fonctionne à nouveau

Une fois le debug terminé, remet `USE_BT_SERIAL` à `1` et re-flash.

##### Troubleshooting BT

| Symptôme | Cause | Fix |
|---|---|---|
| `M5Stack-Vibe` n'apparaît pas dans la liste Bluetooth Windows | Firmware pas flashé en mode BT, ou BT pas init côté ESP32 | Vérifie que `USE_BT_SERIAL=1` dans `serial_io.h`, re-flash, et que `BluetoothSerial::begin("M5Stack-Vibe")` n'a pas échoué (vérifier en repassant temporairement en USB + monitor) |
| Pairing OK mais `Get-PnpDevice` ne montre pas de Standard Serial over Bluetooth | Service SPP pas exposé par Windows | Va dans `Devices and Printers` → click droit sur `M5Stack-Vibe` → `Properties` → onglet `Services` → coche `Serial Port (SPP)` → `Apply` |
| Pings reçus de manière intermittente | Distance >10 m, interférences 2.4 GHz (WiFi, micro-onde) | Rapproche le M5Stack du PC, ou change le canal WiFi 2.4 GHz |
| `vibe-m5stack` ouvre le COM mais timeout au premier approval | Mauvais COM (tu as pris l'incoming au lieu de l'outgoing) | Essaie l'autre COM des deux assignés par Windows |
| M5Stack reboot quand même au pairing initial | Normal — le pairing redémarre la pile BT côté ESP32 | Aucun fix, ça arrive 1× lors du premier pairing. Les sessions suivantes ne reboot pas. |

### 2. Installer le plugin Python

`mistral-vibe` est installé via `uv tool install mistral-vibe`, ce qui crée un venv
isolé dans `~\AppData\Roaming\uv\tools\mistral-vibe\`. Le plugin `vibe-m5stack` doit
être injecté **dans ce même venv**, sinon l'import `vibe` échoue à l'exécution.

Depuis la racine du repo (le `.` final compte) :

```bash
uv tool install --reinstall mistral-vibe --with-editable . --with-executables-from vibe-m5stack
```

Cela :
1. Reconstruit le venv `mistral-vibe`.
2. Y installe `vibe-m5stack` en editable + dépendances (`pyserial`, `mcp`, `aiohttp`, `filelock`).
3. Expose les entrypoints **des deux packages** dans `~\.local\bin\` :
   `vibe`, `vibe-acp` (de mistral-vibe) + `vibe-m5stack`, `m5stack-mcp-server` (de vibe-m5stack).

> ⚠️ **`--with-executables-from vibe-m5stack` est obligatoire.** Sans cette flag,
> `uv tool install` n'expose que les entrypoints du tool principal (`mistral-vibe`).
> `vibe-m5stack.exe` est bien créé dans le venv (`~\AppData\Roaming\uv\tools\mistral-vibe\Scripts\`)
> mais n'apparaît jamais sur le PATH, et la commande `vibe-m5stack` reste introuvable.
> C'est le piège n°1 de l'install — la version "naïve" `uv tool install --reinstall mistral-vibe --with-editable .` semble réussir sans erreur mais laisse `vibe-m5stack` invisible.

#### 2.a. Vérifier l'install (à faire systématiquement)

```powershell
# Doit retourner C:\Users\<toi>\.local\bin\vibe-m5stack.exe
Get-Command vibe-m5stack | Select-Object Source

# Doit lister vibe.exe, vibe-acp.exe, vibe-m5stack.exe, m5stack-mcp-server.exe
Get-ChildItem $env:USERPROFILE\.local\bin -Filter "vibe*","m5stack*"
```

Si `Get-Command vibe-m5stack` ne retourne rien, l'install a échoué silencieusement.
Causes typiques :
- Tu as oublié `--with-executables-from vibe-m5stack` (cas n°1, voir encadré ci-dessus).
- Un `vibe-m5stack` tourne déjà et verrouille `vibe-m5stack.exe` → ferme le terminal
  qui héberge la session, ou `Stop-Process -Name vibe-m5stack`, puis relance la commande.
- Tu n'as pas lancé depuis la racine du repo (le `.` pointe sur le mauvais dossier).
- Le repo est dans OneDrive/Dropbox/iCloud (voir [Limites connues](#limites-connues)).

> ⚠️ **Ne pas faire `pip install -e .`** : ce `pip` est celui de ton Python système
> ou user, pas celui du venv `mistral-vibe`. Le binaire `vibe-m5stack` n'atterrit
> alors pas sur le PATH, et même s'il y était il échouerait au premier `import vibe`
> (`vibe` vit dans un autre venv).
>
> Cas particulier : `pip install -e .` *fonctionne* si tu actives manuellement le
> venv `mistral-vibe` (`. ~\AppData\Roaming\uv\tools\mistral-vibe\Scripts\Activate.ps1`)
> avant. La commande `uv tool install --with-editable --with-executables-from` ci-dessus
> fait ça proprement pour toi.

### 2bis. Variables d'environnement obligatoires

| Variable | Obligatoire | Rôle |
|---|---|---|
| `M5STACK_PORT` | Oui (Windows) | Port serial où le M5Stack est branché. L'auto-detect a un bug connu (probe 1s vs ping firmware 5s, ~80% de chance de rater). Force toujours le port. |
| `VIBE_SESSION_NAME` | Non | Préfixe affiché sur l'écran M5Stack pour distinguer plusieurs sessions parallèles. ≤ 12 chars. Auto-généré (short UUID) sinon. |

**Set en permanent (PowerShell)** :
```powershell
[Environment]::SetEnvironmentVariable("M5STACK_PORT", "COM8", "User")
# Adapte COM8 selon ton port (Get-PnpDevice -Class Ports te le donne)
```

**Set pour une session** :
```powershell
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
```

L'écran M5Stack affiche `[alpha] write foo.py` ou `[beta] git commit` selon
qui demande. Si deux sessions demandent en même temps, la deuxième attend
que la première relâche le M5Stack (timeout 60s).

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
| Couleurs Mistral (rainbow) | `firmware/src/display/gif_animator.cpp` (anim idle) + `firmware/src/inputs/leds.cpp` (LEDs) |
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

## Statut ambiant + Watchdog (feature A+B)

**Problème résolu** : Avec Vibe, on ne sait jamais si l'agent est en train de travailler,
en attente d'une approbation, ou crashé. Le terminal ne donne pas d'indication visuelle
claire, et quand on quitte l'écran, on ne sait pas si l'agent a besoin de nous.

**Solution** : Le M5Stack affiche en continu l'état de l'agent via écran + LEDs, et un
watchdog détecte les agents morts ou figés.

### États affichés

| État | Écran | LEDs | Signification |
|---|---|---|---|
| **THINKING** | Chat Mistral qui danse | Chase lent orange (palette Mistral) | Agent génère/exécute |
| **WAITING** | Bandeau ambre + chat | Pulse ambre | Approval en attente ou `WaitingForInputEvent` |
| **DONE/IDLE** | Chat + bandeau "Ready" | Vert fixe (après flourish vert vif ~1.5s) | Agent a fini, prêt pour nouvelle instruction |
| **ERROR/DEAD** | Bandeau rouge "Agent DEAD!" | Rouge clignotant + buzz | Exception ou watchdog déclenché (PC déconnecté) |
| **STUCK** | Bandeau rouge "Agent STUCK!" | Rouge clignotant + buzz | Agent figé (generating forever) |

### Watchdog

Le firmware détecte automatiquement deux cas d'erreur côté device :

- **DEAD** : plus aucun message reçu du PC depuis 12 secondes
- **STUCK** : état THINKING maintenu sans progression (seq inchangé) depuis 90 secondes

Le buzz + rouge clignotant = signal physique fort perceptible même en étant parti du bureau.

### Architecture multi-session (owner-broker)

Pour permettre la connexion persistante (nécessaire pour le status continu et le heartbeat)
tout en conservant le multi-session, une architecture **owner-broker** est implémentée :

- **OWNER** : Une session acquiert un lock (`~/.vibe/m5stack.owner.lock`) et devient owner.
  Elle ouvre la connexion serial persistante, lance un serveur socket localhost, et
  agrège les états de toutes les sessions.
- **CLIENT** : Les autres sessions se connectent au socket de l'owner et envoient leurs
  status/approval par ce canal.
- **Ré-élection** : Si l'owner meurt, un client devient automatiquement le nouvel owner.

Priorité d'affichage : WAITING > THINKING > DONE (le device montre l'état le plus urgent).

Variable d'environnement : `M5STACK_OWNER=0` pour forcer le mode client.

### Protocole étendu

Nouveau message PC → device :
```json
{"type":"status","state":"thinking","detail":"edit src/foo.py","seq":42}
```

- `state` : "thinking" | "waiting" | "done" | "error"
- `detail` : texte court (≤ 40 chars)
- `seq` : compteur monotone (pour le watchdog STUCK)
- **Cadence** : envoyé à chaque événement + heartbeat toutes les 3 secondes

Le broker agrège les status de toutes les sessions et envoie l'état prioritaire au device.

---

## Architecture

```
firmware/                          Arduino/PlatformIO, board m5stack-fire
├── platformio.ini                 M5Stack + ArduinoJson + FastLED
└── src/
    ├── main.cpp                   State machine: IDLE ↔ SHOWING_REQUEST ↔ THINKING/WAITING/DONE/ERROR/DEAD/STUCK
    ├── display/
    │   ├── anim.h                 ChatAnimator wrapper
    │   ├── gif_animator.{h,cpp}   pushImage direct + recomposition rainbow par bande
    │   ├── gif_frames.h           27 frames 240×240 RGB565 (≈3 MB en flash)
    │   ├── mistral_logo.h         10 rects du logo "M" Mistral
    │   └── screen.{h,cpp}         ApprovalScreen + bandeaux d'état (status banners)
    ├── inputs/
    │   ├── buttons.{h,cpp}        Wrapper boutons + vibration
    │   ├── imu.{h,cpp}            IMU MPU6886 pour la détection de mouvement (shake)
    │   └── leds.{h,cpp}           FastLED — ring 10 + matrix B + matrix C, setAgentState()
    └── serial/
        └── protocol.{h,cpp}       JSON in/out + MessageType::STATUS (state, detail, seq)

plugin/                            Python — pont serial ↔ Vibe
├── __main__.py                   Entrypoint console (`vibe-m5stack`)
├── bridge.py                      M5StackBridge: auto-detect port, thread reader, mode éphémère + lock file
├── broker.py                      OwnerBroker: serveur socket, agrégation état multi-session, ré-élection
├── m5stack_utils.py               SessionManager pour multi-session
├── vibe_m5stack_hook.py           Hook approval + status tracking (monkey-patch AgentLoop)
├── vibe_hook.py                   legacy console fallback (avant MCP)
├── mcp_server.py                  Server MCP stdio asyncio — optionnel, désactivé par défaut
├── test_broker.py                 Tests unitaires pour broker
├── test_status.py                Tests unitaires pour status tracking
└── requirements.txt
```

### Protocole série

PC → M5Stack (1 ligne JSON terminée `\n`) :
```json
{"type":"approval","id":12345,"title":"Commit","body":"..."}
{"type":"credit_info","percent":45}
{"type":"status","state":"thinking","detail":"edit foo.py","seq":42}
```

M5Stack → PC :
```json
{"type":"response","id":12345,"approved":true}
{"type":"response","id":12345,"approved":false,"cancelled":true}
{"type":"ping"}    // toutes les 5s en IDLE
```

**Nouveau message `status`** (feature A+B) :
- `state` : "thinking" | "waiting" | "done" | "error"
- `detail` : texte court (≤ 40 chars)
- `seq` : compteur monotone croissant (anti-faux-positif watchdog)
- **Fréquence** : à chaque événement + heartbeat toutes les 3s

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

- **`POWERON_RESET` du M5Stack à chaque ouverture du port serial sur certains PCs**
(constaté sur Lenovo ThinkPad avec chipset Intel USB 3.1). La pile USB Windows
cycle VBUS au moment de l'open → M5Stack reboot → approval JSON perdu pendant
le boot → timeout 35s. Aucun fix côté software possible (DTR/RTS désassertés
n'empêchent pas le reset). Solution durable : **passer en mode Bluetooth Classic
SPP**, voir [§1.h](#1h-mode-wireless-bluetooth-classic-spp). Le M5Stack devient
wireless, plus aucun reset, et `bridge.py` reste inchangé.
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
