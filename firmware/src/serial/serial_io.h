// Vibe M5Stack - M5Stack integration for Mistral Vibe CLI
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

// Transport switch: USB serial vs Bluetooth Classic (SPP).
//   USE_BT_SERIAL = 0 : standard USB serial (CDC over CP2104). Required for
//                       `pio device monitor` and PlatformIO upload-with-monitor.
//   USE_BT_SERIAL = 1 : Bluetooth Classic Serial Port Profile. M5Stack appears
//                       as "M5Stack-Vibe" in Windows pairing, exposes a COM
//                       virtuel that bridge.py reads exactly like USB serial.
//                       Bypasses the host USB stack entirely (cures the
//                       POWERON_RESET-on-port-open seen on some laptops).
#ifndef USE_BT_SERIAL
#define USE_BT_SERIAL 1
#endif

#if USE_BT_SERIAL
  #include <BluetoothSerial.h>
  extern BluetoothSerial bridgeSerial;
#else
  #include <Arduino.h>
  #define bridgeSerial Serial
#endif

void bridgeSerialBegin(uint32_t baud);

// Lecture RX via ring buffer drainé en continu par une tâche dédiée.
// ⚠️ La queue RX de BluetoothSerial ne fait que 512 octets et le callback SPP
// JETTE les octets quand elle est pleine (« RX Full! Discarding N bytes »).
// loop() (delay(16) + rendu LCD) laisse des trous de 20-40 ms pendant lesquels
// un stream TTS (~24 Ko/s) la fait déborder : il faut drainer toutes les 2 ms,
// indépendamment de la cadence de loop(). Toujours lire par ces helpers,
// jamais bridgeSerial.available()/read() directement.
size_t bridgeRxAvailable();
int bridgeRxRead();  // -1 si vide

// DIAG TEMPORAIRE (retirer avant merge) : octets drainés depuis la queue BT.
extern volatile uint32_t g_btDrained;
