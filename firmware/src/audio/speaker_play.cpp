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
#include "speaker_play.h"
#include <Arduino.h>
#include <driver/i2s.h>
#include <driver/dac.h>
#include <esp_heap_caps.h>
#include <freertos/semphr.h>
#include <ArduinoJson.h>

// I2S_NUM_0 est partagé avec la capture micro (ADC).
// Exclusion mutuelle : une seule des deux peut être active à la fois.
static const i2s_port_t SPEAKER_I2S_PORT = I2S_NUM_0;
static const int SPEAKER_I2S_BCK_PIN = -1;    // non utilisé pour DAC intégré
static const int SPEAKER_I2S_WS_PIN = -1;    // non utilisé pour DAC intégré
static const int SPEAKER_I2S_DOUT_PIN = 25;  // GPIO 25 = DAC intégré du Fire

// Buffer circulaire en PSRAM pour les données µ-law
static uint8_t* s_buffer = nullptr;
static size_t s_bufferSize = 0;
static size_t s_writePos = 0;
static size_t s_readPos = 0;
static bool s_active = false;
static bool s_stopRequested = false;
static TaskHandle_t s_i2sTaskHandle = nullptr;

// Sémaphore pour synchroniser l'écriture (depuis le thread réseau/loop)
// et la lecture (depuis le callback I2S).
static SemaphoreHandle_t s_bufferMutex = nullptr;

// G.711 µ-law -> PCM16 (miroir de linear2ulaw côté capture).
// BIAS et CLIP doivent correspondre exactement.
static int16_t ulaw2linear(uint8_t ulaw) {
    const int16_t BIAS = 0x84;
    const int16_t CLIP = 32635;
    
    ulaw = ~ulaw;
    uint8_t sign = ulaw & 0x80;
    uint8_t exponent = (ulaw >> 4) & 0x07;
    uint8_t mantissa = ulaw & 0x0F;

    // Formule EXACTEMENT inverse de l'encodeur PC (plugin/voice.py) :
    // << exponent, PAS << (exponent+3) — l'ancienne version sortait des
    // valeurs 8x trop grandes qui débordaient l'int16 (bruit pur).
    int32_t sample = (((int32_t)(mantissa << 3) + BIAS) << exponent) - BIAS;
    if (sign) sample = -sample;

    if (sample > CLIP) sample = CLIP;
    if (sample < -CLIP) sample = -CLIP;

    return (int16_t)sample;
}

// Tâche de lecture I2S : lit du buffer circulaire et envoie à I2S DAC.
// TOUT le teardown du driver appartient à cette tâche (jamais à stop() —
// désinstaller pendant qu'un i2s_write est en cours = LoadProhibited/reboot).
static void i2sWriterTask(void* arg) {
    (void)arg;
    constexpr size_t PCM_SAMPLES = 128;
    static uint16_t pcmBuffer[PCM_SAMPLES];  // non signé : format du DAC intégré

    while (s_active) {
        size_t available = (s_writePos >= s_readPos) ? (s_writePos - s_readPos)
                                                     : (s_bufferSize - s_readPos + s_writePos);
        // ⚠️ Compte d'ÉCHANTILLONS (la v1 bornait à sizeof() = 2x trop ->
        // écrasement de pile de la tâche -> panic/reboot).
        size_t toRead = (available > PCM_SAMPLES) ? PCM_SAMPLES : available;

        if (toRead == 0) {
            // Pas de données : silence (mi-échelle DAC) pour éviter les pops.
            for (size_t i = 0; i < PCM_SAMPLES; i++) pcmBuffer[i] = 0x8000;
            size_t written = 0;
            i2s_write(SPEAKER_I2S_PORT, pcmBuffer, sizeof(pcmBuffer), &written,
                      20 / portTICK_PERIOD_MS);
            continue;
        }

        // µ-law -> PCM16 signé -> non signé (le DAC intégré lit les 8 bits
        // hauts d'un échantillon non signé ; du signé brut = distorsion).
        for (size_t i = 0; i < toRead; i++) {
            int16_t s = ulaw2linear(s_buffer[s_readPos]);
            pcmBuffer[i] = (uint16_t)(s + 32768);
            s_readPos = (s_readPos + 1) % s_bufferSize;
        }

        size_t written = 0;
        esp_err_t err = i2s_write(SPEAKER_I2S_PORT, pcmBuffer,
                                  toRead * sizeof(uint16_t), &written,
                                  100 / portTICK_PERIOD_MS);
        if (err != ESP_OK) {
            break;
        }
    }

    // Teardown par la tâche uniquement.
    i2s_driver_uninstall(SPEAKER_I2S_PORT);
    s_i2sTaskHandle = nullptr;   // signale à stop() que le teardown est fini
    vTaskDelete(nullptr);
}


bool speakerPlayStart() {
    if (s_active) return true;  // déjà en cours
    if (s_buffer == nullptr) {
        // Allouer buffer en PSRAM (10 s de µ-law 16kHz = 20 Ko)
        s_buffer = (uint8_t*)heap_caps_malloc(SPEAKER_BUFFER_SIZE, MALLOC_CAP_SPIRAM);
        if (s_buffer == nullptr) {
            s_buffer = (uint8_t*)malloc(SPEAKER_BUFFER_SIZE);  // fallback DRAM
        }
        if (s_buffer == nullptr) return false;
        s_bufferSize = SPEAKER_BUFFER_SIZE;
    }
    
    s_writePos = 0;
    s_readPos = 0;
    s_stopRequested = false;
    
    // Créer le mutex
    if (s_bufferMutex == nullptr) {
        s_bufferMutex = xSemaphoreCreateMutex();
        if (s_bufferMutex == nullptr) {
            free(s_buffer);
            s_buffer = nullptr;
            return false;
        }
    }
    
    // Configuration I2S pour DAC intégré
    i2s_config_t cfg = {};
    cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX | I2S_MODE_DAC_BUILT_IN);
    cfg.sample_rate = SPEAKER_SAMPLE_RATE;
    cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
    // Le DAC intégré utilise le canal droit pour GPIO 25
    cfg.channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT;
    cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
    cfg.dma_buf_count = 8;
    cfg.dma_buf_len = 64;
    cfg.use_apll = false;
    
    // Installer le driver I2S
    if (i2s_driver_install(SPEAKER_I2S_PORT, &cfg, 0, nullptr) != ESP_OK) {
        return false;
    }
    
    // OBLIGATOIRE en mode DAC intégré : route la sortie I2S vers les broches
    // DAC (sans cet appel, rien ne sort — juste un grésillement résiduel).
    i2s_set_pin(SPEAKER_I2S_PORT, nullptr);
    // HP du Fire sur GPIO 25 = DAC canal 1 = slot DROIT de l'I2S.
    // (i2s_set_dac_mode attend un i2s_dac_mode_t, pas un i2s_mode_t.)
    i2s_set_dac_mode(I2S_DAC_CHANNEL_RIGHT_EN);
    
    // Démarrer la tâche de lecture
    s_active = true;
    xTaskCreatePinnedToCore(i2sWriterTask, "i2sWriter", 4096, nullptr, 10, &s_i2sTaskHandle, APP_CPU_NUM);
    
    return true;
}

bool speakerPlayFeed(const uint8_t* data, size_t len) {
    if (!s_active || s_buffer == nullptr || data == nullptr || len == 0) {
        return false;
    }
    
    // Attendre le mutex (timeout pour éviter un deadlock)
    if (xSemaphoreTake(s_bufferMutex, pdMS_TO_TICKS(50)) != pdTRUE) {
        return false;
    }
    
    bool success = true;
    
    // Vérifier l'espace disponible
    size_t available = (s_writePos >= s_readPos) ? (s_bufferSize - s_writePos + s_readPos) : (s_readPos - s_writePos);
    
    if (len > available) {
        // Buffer plein : attendre BORNÉ que la tâche draine, puis abandonner
        // le chunk. ⚠️ La v1 se rappelait RÉCURSIVEMENT — récursion infinie
        // et débordement de pile (reboot) dès que le producteur dépassait le
        // consommateur.
        xSemaphoreGive(s_bufferMutex);
        for (int retry = 0; retry < 20; retry++) {   // <= 200 ms
            vTaskDelay(pdMS_TO_TICKS(10));
            if (xSemaphoreTake(s_bufferMutex, pdMS_TO_TICKS(50)) != pdTRUE) {
                return false;
            }
            available = (s_writePos >= s_readPos)
                ? (s_bufferSize - s_writePos + s_readPos)
                : (s_readPos - s_writePos);
            if (len <= available) {
                goto copy_data;   // la place s'est libérée
            }
            xSemaphoreGive(s_bufferMutex);
        }
        return false;  // chunk abandonné plutôt que device gelé/crashé
    }
copy_data:
    
    // Copier les données
    if (s_writePos + len <= s_bufferSize) {
        memcpy(&s_buffer[s_writePos], data, len);
        s_writePos += len;
    } else {
        // Wrap around
        size_t firstPart = s_bufferSize - s_writePos;
        memcpy(&s_buffer[s_writePos], data, firstPart);
        memcpy(s_buffer, &data[firstPart], len - firstPart);
        s_writePos = len - firstPart;
    }
    
    if (s_writePos >= s_bufferSize) {
        s_writePos = 0;
    }
    
    // Libérer le mutex
    xSemaphoreGive(s_bufferMutex);
    
    return success;
}

void speakerPlayStop() {
    if (!s_active) return;

    s_stopRequested = true;
    s_active = false;

    // Attendre (borné) que LA TÂCHE fasse le teardown : désinstaller le
    // driver ici pendant qu'un i2s_write est en vol = LoadProhibited/reboot.
    // La tâche sort en <= ~120 ms (timeouts des i2s_write).
    for (int i = 0; i < 50 && s_i2sTaskHandle != nullptr; i++) {
        vTaskDelay(10 / portTICK_PERIOD_MS);
    }

    s_writePos = 0;
    s_readPos = 0;
    s_stopRequested = false;
}

void speakerPlayRelease() {
    speakerPlayStop();
    
    if (s_buffer != nullptr) {
        free(s_buffer);
        s_buffer = nullptr;
        s_bufferSize = 0;
    }
    
    if (s_bufferMutex != nullptr) {
        vSemaphoreDelete(s_bufferMutex);
        s_bufferMutex = nullptr;
    }
}

bool speakerPlayIsPlaying() {
    return s_active;
}

void speakerPlayReset() {
    speakerPlayStop();
    speakerPlayRelease();
}
