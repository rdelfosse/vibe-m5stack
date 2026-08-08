# Changelog

Toutes les modifications notables de ce projet seront documentées dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr-CH/1.0.0/),
et ce projet adhère au [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (SemVer).

En pré-1.0, la version *minor* (0.X.0) est incrémentée pour les nouvelles fonctionnalités,
et la version *patch* (0.0.Y) pour les corrections de bugs.

## [Unreleased]
## [0.5.0] - 2026-08-08

### Ajouté
- **Instructions vocales push-to-talk** : parler au M5Stack pour donner des instructions à Vibe
  - Appui long **A** en IDLE/WELCOME : nouvelle instruction vocale (mode prompt)
  - Appui long **A** en approbation : approuver immédiatement + commentaire vocal injecté en follow-up
  - Appui long **B** en approbation : rejeter avec consigne vocale comme raison du refus
  - État visuel **LISTENING** avec animation LED pendant l'enregistrement
  - Le micro est celui du PC, transcription via **Mistral Voxtral API**
  - Protocole série : messages `{"type":"voice","action":"start|stop","mode":"prompt|approve|reject","id":X}`
  - Feedback PC → device : `{"type":"voice_ack","state":"transcribing|done","text":"..."}`

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
