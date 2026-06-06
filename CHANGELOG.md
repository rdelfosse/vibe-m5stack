# Changelog

Toutes les modifications notables de ce projet seront documentées dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr-CH/1.0.0/),
et ce projet adhère au [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (SemVer).

En pré-1.0, la version *minor* (0.X.0) est incrémentée pour les nouvelles fonctionnalités,
et la version *patch* (0.0.Y) pour les corrections de bugs.

## [Unreleased]

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

[Unreleased]: https://github.com/romai/vibe-m5stack/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/romai/vibe-m5stack/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/romai/vibe-m5stack/releases/tag/v0.1.0
