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
#include "serial_io.h"
#include <Arduino.h>

#if USE_BT_SERIAL
BluetoothSerial bridgeSerial;

// Ring SPSC : la tâche de drainage écrit (head), receive() lit (tail).
// 16 Ko ≈ 700 ms de stream TTS — le consommateur suit largement.
static uint8_t rxRing[16384];
static volatile size_t rxHead = 0;
static volatile size_t rxTail = 0;

static void rxDrainTask(void*) {
    for (;;) {
        while (bridgeSerial.available()) {
            int c = bridgeSerial.read();
            if (c < 0) break;
            size_t next = (rxHead + 1) % sizeof(rxRing);
            if (next == rxTail) break;  // ring plein : l'octet reste dans la queue BT
            rxRing[rxHead] = (uint8_t)c;
            rxHead = next;
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}

void bridgeSerialBegin(uint32_t /*baud*/) {
    bridgeSerial.begin("M5Stack-Vibe");
    // Core 1 + priorité haute : le callback SPP pousse un événement ENTIER
    // (~729 o pour un chunk TTS de 512 o) d'un bloc depuis le core 0 — plus
    // gros que la queue de 512 o. Seul un drainage en VRAI parallèle (autre
    // core) peut vider pendant la poussée ; sur le même core, la tâche est
    // préemptée et 217 octets partent à la poubelle à chaque chunk.
    xTaskCreatePinnedToCore(rxDrainTask, "btRxDrain", 3072, nullptr, 19, nullptr, 1);
}

size_t bridgeRxAvailable() {
    size_t h = rxHead, t = rxTail;
    return (h >= t) ? (h - t) : (sizeof(rxRing) - t + h);
}

int bridgeRxRead() {
    if (rxTail == rxHead) return -1;
    uint8_t c = rxRing[rxTail];
    rxTail = (rxTail + 1) % sizeof(rxRing);
    return c;
}
#else
void bridgeSerialBegin(uint32_t baud) {
    Serial.begin(baud);
    while (!Serial) {
        delay(10);
    }
}

size_t bridgeRxAvailable() { return Serial.available(); }
int bridgeRxRead() { return Serial.read(); }
#endif
