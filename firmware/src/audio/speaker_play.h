// Vibe M5Stack - Lecture audio via DAC intégré (HP du Fire)
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

// Haut-parleur du Fire : DAC intégré sur GPIO 25 (I2S_NUM_0, canal droit).
// Format : G.711 µ-law 16 kHz mono.
//
// Exclusion mutuelle stricte avec mic_capture (partage I2S_NUM_0) :
//   - Pas de lecture pendant LISTENING (capture micro active)
//   - Un appui long A pendant lecture = stop lecture PUIS capture
//
// Usage (streaming depuis le PC) :
//   speakerPlayStart();           // Alloue buffer, initialise I2S DAC
//   speakerPlayFeed(data, len);  // Alimente le buffer (µ-law 16kHz mono)
//   speakerPlayStop();            // Vide le buffer, stop I2S
//   speakerPlayRelease();        // Libère la PSRAM
//
// Le device peut recevoir :
//   {"type":"tts_audio","seq":N,"data":"<base64 1 Ko µ-law>"}
//   {"type":"tts_end","total":X}
//   {"type":"tts_stop"}          // annule la lecture en cours

constexpr uint32_t SPEAKER_SAMPLE_RATE = 16000;
// µ-law = 1 octet/échantillon : 10 s à 16 kHz = 160 Ko (le /8 donnait 1,25 s).
constexpr size_t   SPEAKER_BUFFER_SIZE = SPEAKER_SAMPLE_RATE * 10;

// Démarre la lecture. false si I2S/PSRAM indisponible ou déjà en lecture.
bool speakerPlayStart();

// Alimente le buffer avec des données µ-law. Bloquant si buffer plein.
// Retourne false si la lecture a été arrêtée (tts_stop reçu ou bouton pressé).
bool speakerPlayFeed(const uint8_t* data, size_t len);

// Arrête la lecture (I2S relâché, buffer vidé).
void speakerPlayStop();

// Fin de flux (tts_end) : draine le buffer restant puis s'arrête tout seul.
void speakerPlayFinish();

// Diagnostic : joue un bip 440 Hz (~0,4 s) par le pipeline complet (bloquant).
void speakerPlayTestTone();

// Libère le buffer PSRAM (appeler après tts_end ou abandon).
void speakerPlayRelease();

// Vrai si une lecture TTS est en cours.
bool speakerPlayIsPlaying();

// Réinitialise complètement le module (appelé au démarrage ou après erreur).
void speakerPlayReset();
