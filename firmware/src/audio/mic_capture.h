// Vibe M5Stack - Capture micro embarqué (MEMS analogique du socle M5GO)
// Copyright 2026 Romain Delfosse
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
#pragma once
#include <cstdint>
#include <cstddef>

// Micro MEMS analogique du M5Stack Fire (socle M5GO) : GPIO 34 = ADC1_CH6.
// Capture via I2S-ADC intégré à 16 kHz, encodée en G.711 µ-law (8 bits/éch.,
// 16 Ko/s) directement dans un buffer PSRAM — 10 s max par session PTT.
//
// Usage (push-to-talk) :
//   micCaptureStart();            // à l'appui long (entrée LISTENING)
//   micCapturePump();             // à chaque tour de loop() pendant LISTENING
//   micCaptureStop();             // au relâchement
//   micCaptureData()/Size();      // buffer µ-law à uploader
//   micCaptureRelease();          // après upload (libère la PSRAM)

constexpr uint32_t MIC_SAMPLE_RATE = 16000;
// Borne de sécurité PSRAM (960 Ko), pas une limite d'usage : l'audio est
// streamé vers le PC PENDANT l'enregistrement, le buffer n'absorbe que les
// à-coups du lien BT.
constexpr uint32_t MIC_MAX_RECORD_MS = 60000;
constexpr size_t   MIC_BUFFER_SIZE = MIC_SAMPLE_RATE * MIC_MAX_RECORD_MS / 1000; // µ-law: 1 o/éch.

// Démarre une session de capture. false si I2S/PSRAM indisponible.
bool micCaptureStart();

// Draine le DMA vers le buffer (non bloquant). À appeler à chaque frame.
// Retourne false quand le buffer est plein (borne 10 s atteinte).
bool micCapturePump();

// Arrête la capture (I2S relâché). Le buffer reste disponible.
void micCaptureStop();

// Accès au buffer µ-law capturé.
const uint8_t* micCaptureData();
size_t micCaptureSize();

// Durée réelle de la capture (ms), mesurée à l'horloge du device : permet au
// PC de calculer le débit effectif de l'ADC (les quirks I2S-ADC de l'ESP32
// font dériver la fréquence réelle) et de rééchantillonner à 16 kHz.
uint32_t micCaptureDurationMs();

// Libère le buffer PSRAM (fin d'upload ou abandon).
void micCaptureRelease();
