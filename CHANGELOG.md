# Changelog

Toutes les modifications notables de ce projet seront documentées dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr-CH/1.0.0/),
et ce projet adhère au [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (SemVer).

En pré-1.0, la version *minor* (0.X.0) est incrémentée pour les nouvelles fonctionnalités,
et la version *patch* (0.0.Y) pour les corrections de bugs.

## [Unreleased]

## [0.7.0] - 2026-10-20

### Ajouté
- **Compatibilité Mistral Vibe 3.x** : la TUI Rust de Vibe 3 ne peut plus
  être monkey-patchée — le plugin s'y insère par un **proxy app server**
  (`VIBE_APP_SERVER_BIN` → `vibe-m5stack-app-server`) qui relaie le
  protocole JSON-RPC et intercepte les approbations au niveau protocole
  (`callback/call` → bouton A/B/C, `callback/result`). Attente illimitée :
  le callback reste ouvert jusqu'au bouton, quoi qu'il arrive. Course
  TUI/device : premier répondant gagne, réponse TUI tardive avalée.
  Modes : `off`, `auto-approve`, `auto-deny` (tests), `device` ;
  `M5STACK_APPROVAL_TUI=0` pour que le device arbitre seul.
- **Défaut device-only** : quand le wrapper active le mode `device`, il pose
  aussi `M5STACK_APPROVAL_TUI=0` — la TUI n'affiche pas de dialogue
  d'approbation. Sinon le dialogue TUI reste ouvert après un arbitrage
  bouton/voix du device (le client TUI ne peut pas apprendre qu'un
  callback a été arbitré ailleurs). `M5STACK_APPROVAL_TUI=1` restaure la
  course TUI/device.
- **Statuts device** : le proxy devient propriétaire du port M5Stack
  (connexion persistante, heartbeat 3 s) et mappe les notifications app
  server vers les états firmware (thinking/reasoning, tool_exec avec nom
  d'outil, waiting sur approbation, done/error).
- **TTS Voxtral 3** (`voxtral-mini-tts-3-0`, REST direct sans SDK) :
  lecture de la réponse de l'agent sur le haut-parleur du Fire, décision
  par le menu Voice Out du device, pacing µ-law inchangé côté firmware.
  **Voix émotionnelle** : `fr_marie_{neutral,happy,sad,excited,angry}`
  (variants vérifiées sur l'API) choisies selon le ton de la réponse
  (heuristique locale). Interruption : bouton device, nouveau tour.
- **Voix entrante** : dicée sur le device → STT REST
  (`voxtral-mini-transcribe-3-0`, détection de langue auto) → tour injecté
  via `session/turn/enqueue` (la file d'input du CLI). Rejet vocal d'une
  approbation avec la raison dictée (`router.deny_latest`).
- `tools/spike_app_server_client.py`, `tools/e2e_proxy_check.py` (modes
  approve/deny/speak) et un fake app server autonome ; 19 nouveaux tests
  (protocole pur, sans LLM ni matériel).
- `plugin/app_server_client.py` : bibliothèque client compagnon réutilisable
  (transport tamponné > 64 KiB, sessions, tours, callbacks).

### Changé
- **Dépendance** : `mistral-vibe>=2.23` sans borne supérieure — le wrapper
  (`plugin/__main__.py`) détecte la version à l'exécution : 3.x → flow
  proxy, 2.x → flow legacy monkey-patch. La borne `<3` du 0.6.2 n'a plus
  de raison d'être.
- `voice_handler.py` : transcriber injectable (`set_transcriber`) — le
  legacy retombe sur le SDK mistralai, le proxy sur le REST.
- Logs du proxy dans `%TEMP%\vibe-m5stack-proxy.log` (la TUI Rust avale
  la stderr).

### Validé sur le matériel
- Approbation arbitrée par bouton physique en mode device-only (fichier
  créé / refusé selon A/B), course TUI/device, statuts pendant un tour,
  TTS (180 chunks, diag firmware à zéro erreur), voix émotionnelle
  (`fr_marie_happy` sur réponse positive), round-trip TTS→STT exact.

## [0.6.1] - 2026-08-24

### Corrigé
- **Suite de tests réparée** : `tests/conftest.py` avait une docstring fusionnée
  avec l'import (`"""import json`) → SyntaxError, pytest ne collectait plus rien.
  Les tests hérités de `plugin/test_*.py` importaient `bridge` en module à plat
  (`ModuleNotFoundError` depuis le passage au package `plugin.`) et étaient
  masqués par `testpaths = ["tests"]`.
- **Tests unifiés dans `tests/`** : les 10 fichiers de `plugin/` migrent vers
  `tests/`, imports fixés sur `plugin.*`. Les stubs `sys.modules["vibe.*"]`
  (fragiles — l'ordre de collecte pytest décidait qui voit le mock) sont
  remplacés par les vrais modules `mistral-vibe`, désormais dépendance dure.
- **Scripts de test reclassifiés** : `plugin/test_bridge.py` (diagnostic
  matériel, pas un test unitaire) → `tools/test_bridge_hw.py` ;
  `plugin/test_hook.py` renommé `tests/test_hook_race.py` pour lever
  l'ambiguïté avec `tests/test_hook_format.py`.
- **Tests d'intégration mis à jour pour l'API ≥ 2.23** : assertions sur
  `AgentLoop.act` (patched_act) et `VibeApp.__init__` (captured_init) au lieu
  des globals `_original_set_approval_callback` / `_patched_vibe_app` supprimés
  en 0.5.1 ; échec d'init bridge attendu = retour None (fallback TUI).
- **`OwnerBroker.aggregated_activity` non initialisé** (plugin/broker.py) :
  le premier heartbeat avant tout `push_status` levait une AttributeError
  avalée en ERROR log (« Failed to send aggregated status ») et rien n'était
  envoyé au device — à chaque démarrage owner.
- **Arrêt du serveur broker** : le CancelledError de `serve_forever()` sortait
  du thread au `close()` (traceback + warning pytest) ; il est maintenant
  intercepté comme arrêt normal.
- **Port hardcodé COM8 dans le serveur MCP** (`mcp_server.py`) : ignorait
  `M5STACK_PORT`/config.toml → inutilisable tel quel sur toute machine dont
  le device n'est pas sur COM8. Passe par la résolution standard
  (`config.resolve_port()`), et l'échec de push crédit (device absent)
  repasse en debug.
- **Sonde MCP conforme au protocole** : le « test » `test_mcp_server`
  envoyait un initialize invalide (sans protocolVersion/capabilities/
  clientInfo, rejeté par le SDK MCP) puis retournait False — que pytest
  ignorait silencieusement. Le test pytest couvre désormais un vrai handshake
  JSON-RPC sans matériel ; la sonde complète avec approbation device reste
  disponible en script (`python -m tests.test_mcp_server`).

### Ajouté
- **CI Python** (`.github/workflows/tests.yml`) : pytest sur push main / PR,
  matrix Python 3.12 + 3.13. Le workflow firmware passe aussi à Python 3.12.

### Changé
- **Python 3.12 partout** : README aligné sur `requires-python = ">=3.12"` du
  pyproject (README et CI mentionnaient encore 3.10).

## [0.6.0] - 2026-08-10

### Ajouté
- **Réponses vocales (TTS Voxtral)** : la réponse finale de l'agent est lue à
  voix haute par le haut-parleur du M5Stack Fire (ou les enceintes du PC)
  - Menu **Voice Out** : Off (défaut) / Device / PC, persisté en NVS et annoncé
    au PC (pings + messages config)
  - Menu **Voice Lang** : FR (voix `fr_marie_neutral`, défaut) / EN
    (`gb_jane_neutral`) — changement de voix appliqué à la lecture suivante
  - **Lecture intégrale** du message (révision P2 du 2026-08-10) : nettoyage
    markdown/blocs de code, garde-fou technique à 4000 caractères ; n'importe
    quel bouton interrompt la lecture, une nouvelle dictée (A long) aussi
  - Audio G.711 µ-law 16 kHz streamé en chunks base64 sur Bluetooth SPP,
    pré-buffer 1,5 s, normalisation crête ~90 %, passe-bas anti-repliement
    avant décimation 24→16 kHz
  - Télémétrie `tts_diag` : le device remonte au PC chunks/octets reçus et
    erreurs de parse à chaque fin de stream (visible dans le log du hook)

### Corrigé
- **Queue Bluetooth SPP de 512 octets** : le callback jetait des octets en
  plein stream TTS (« RX Full! Discarding ») — drainage continu par une tâche
  dédiée (core 1, 1 ms) vers un ring de 16 Ko + chunks PC ≤ 390 octets
- **Horloge I2S-DAC 5,5× trop rapide** (minimum réel ~22 kHz, chaotique sous
  4 kHz demandés) : compensation par duplication d'échantillons (ZOH) avec
  ratio mesuré à chaque lecture — c'était la voix « accélérée »
- **Pacing d'envoi** : échéances absolues (asyncio.sleep(15 ms) dort ~21 ms
  sous Windows → buffer à sec, voix hachée) ; débit calé à 16 Ko/s exactement
- **Appuis résiduels** : un front bouton antérieur à la lecture la tuait à la
  première frame ; purge au démarrage de lecture + le PC notifie le device
  quand il annule un stream + watchdog 12 s sans données
- **RX multi-messages** : jusqu'à 12 messages traités par itération de loop()
  (une ligne par tour ne suivait pas les ~60 lignes/s d'un stream TTS)

## [0.5.1] - 2026-08-09

### Changé
- **Migration API approbation Mistral Vibe ≥ 2.23** : suppression de `AgentLoop.set_approval_callback` (remplacé par `InteractionRequestBroker`).
- **Pin levé** : dépendance `mistral-vibe` mise à jour de `>=2.11,<2.23` à `>=2.23`.
- **Code legacy supprimé** : `patch_agent_loop()`, `_original_set_approval_callback`, wrapper modal/TUI, hack `_pending_approval`.

### Corrigé
- Course native TUI vs M5Stack pour les approbations (plus de fouillage des internals Textual).
- Timeout device ne résout plus l'approbation en refus automatique (décision laissée à la TUI).

## [0.5.0] - 2026-08-09

### Ajouté
- **Instructions vocales push-to-talk, micro embarqué** : parler AU M5Stack (MEMS
  du socle M5GO) pour piloter Vibe, sans rester derrière le PC
  - Appui long **A** (Ready/welcome) : nouvelle instruction vocale — le texte
    apparaît dans Vibe comme un vrai message et démarre un tour
  - Appui long **A** en approbation : approuver immédiatement + commentaire
    dicté injecté dans le tour EN COURS (pilote la todo en direct)
  - Appui long **B** en approbation : rejeter avec la consigne dictée comme
    raison du refus ; appuis courts A/B/C inchangés
  - Audio **streamé en direct** pendant l'enregistrement sur le lien Bluetooth
    (G.711 µ-law 16 kHz, décimation anti-repliement, base64 par chunks) —
    latence quasi nulle au relâchement, jusqu'à 60 s de dictée
  - Auto-calibration du débit ADC (durée mesurée par le device, rééchantillonnage
    côté PC) ; transcription **Mistral Voxtral**, clé résolue comme Vibe
    (variable d'env ou keyring du login navigateur)
  - États visuels **LISTENING** / **TRANSCRIBING** avec animation LED dédiée
  - Item de menu **Mic : Device / PC** (fallback micro PC conservé)
- **Mode démo** (dicté à la voix depuis le canapé 🛋️) : item de menu « Demo
  Mode » ; sans session PC, le device enchaîne les 7 animations LED (welcome,
  activités thinking, waiting, done), chaque état légendé à l'écran dans sa
  couleur, chat animé ou Chaton Fat en vedette ; sortie par n'importe quel bouton
- **Mode debug** : item de menu « Debug » (OFF par défaut) — audit des flux côté
  PC (dump `last_ptt.wav`, logs de capture) uniquement quand il est actif
- **Reconnexion à chaud** : un reboot du device (flash, coupure BT) ne tue plus
  la session vibe-m5stack — reconnexion automatique et resynchronisation

### Corrigé
- Écran d'approbation non bloquant : les boutons sont gérés dans la boucle
  principale (l'ancienne boucle bloquante transformait chaque appui en skip)
- Deadlocks de verrous dans la capture audio PC (record_stop/cancel)
- Capture micro PC sans numpy (RawInputStream) ; SDK mistralai 2.x
  (`mistralai.client.Mistral`, `transcriptions.complete`)

## [0.4.0] - 2026-08-08

### Ajouté
- Menu de configuration sur le device : appui long **C** (~1 s) depuis IDLE/DONE,
  navigation C (suivant) / B (précédent), sélection A, sortie via « Exit » ou appui long C
- **Quiet mode** : coupe vibrations et bips (approbations, alarmes watchdog)
- **Luminosité LED** réglable (16 / 32 / 64 / 128 / 255), appliquée au boot
- Sélecteur de « modèle » : Mistral (chat animé) ou easter egg **Chaton Fat** 😼
  (sprite fixe corps blanc/contour noir + faux bandeau « le nouveau modèle Mistral »)
- Persistance **NVS** (Preferences) : magic byte de validation, défauts sûrs sur
  device neuf (quiet OFF, luminosité 32, modèle Mistral)

### Changé
- `ButtonManager::isHeld()` renvoie un vrai niveau (bouton maintenu) au lieu d'un
  front — base des appuis longs du menu

## [0.3.1] - 2026-08-08

### Changé
- **Fonctionnement dégradé temporaire** : dépendance épinglée à `mistral-vibe>=2.11,<2.23`.
  La 2.23 remplace `AgentLoop.set_approval_callback` par un `InteractionRequestBroker`
  (les approbations deviennent des `ApprovalRequestEvent` résolus via
  `resolve_approval_request`) : le hook M5Stack n'est pas encore adapté et crashe au
  lancement sur ≥2.23. Le pin sera levé quand le hook aura été porté sur la nouvelle API.

## [0.3.0] - 2026-06-02

### Ajoute
- Ecrans daccueil (welcome screen) affiche du boot jusquau premier message status
- Nouveau etat AppState::WELCOME avec transition automatique
- Affichage LCD: titre, auteur, version, tagline, hint, chat + QR code
- QR code scannable vers https://www.romaindelfosse.fr/blog/m5stack-vibe-bouton-physique-agents-ia/
- Animation LED led::welcome(): NeoHEX blanc qui respire + anneau lateral



## [0.2.0] - 2026-05-30

### Ajouté
- Système de versioning SemVer à source unique via le fichier `VERSION`
- Affichage de la version firmware sur l'écran canary (vX.Y.Z)
- Le firmware annonce sa version au PC via le champ `fw` dans les messages ping
- Commande `vibe-m5stack doctor` : détection et affichage de la version firmware, avec avertissement de compatibilité
- Vérification CI : le tag vX.Y.Z doit correspondre au contenu du fichier VERSION
- Le manifest.json du web flasher utilise la version depuis VERSION

### Changé
- `pyproject.toml` utilise maintenant une version dynamique lue depuis le fichier VERSION
- Le ping du firmware inclut maintenant le champ `fw` avec la version

###Corrigé
- Système de statut ambiant (bandeau, couleurs, animations LED)
- Watchdog pour détecter les states DEAD (PC déconnecté) et STUCK (génération infinie)
- Animations NeoHEX (throttling écran, PSRAM)
- Mécanisme owner-broker pour la gestion des ports série
- Installateur (Phase A : détection auto + config, Phase B : web flasher, Phase C : doctor)

## [0.1.0] - 2026-01-XX

### Ajouté
- Version initiale du projet Vibe M5Stack
- Communication série basique avec le firmware
- Système d'approbation avec le M5Stack

[Unreleased]: https://github.com/romai/vibe-m5stack/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/romai/vibe-m5stack/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/romai/vibe-m5stack/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/romai/vibe-m5stack/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/romai/vibe-m5stack/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/romai/vibe-m5stack/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/romai/vibe-m5stack/releases/tag/v0.1.0
