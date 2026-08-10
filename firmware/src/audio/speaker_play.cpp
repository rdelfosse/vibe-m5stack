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
#include <driver/gpio.h>
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
static bool s_finishing = false;   // fin de flux : drainer le buffer puis stop
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
// AUTO-CALIBRATION : l'horloge I2S-DAC ne respecte pas la fréquence demandée
// (facteur 2-5x selon la config — même famille de quirks que l'ADC micro).
// On chronomètre l'écriture de silence (i2s_write bloque au rythme réel du
// DMA) et on corrige le sample rate. À CHAQUE lecture, pas une fois par
// boot : le facteur dépend de l'état du driver, qui change après un passage
// micro (ADC) — une calibration de boot donnait une voix « accélérée » sur
// les lectures suivantes. Précautions de mesure : préchauffage (les
// premières trames sont absorbées par le DMA vide sans bloquer, ce qui
// gonfle le débit apparent) puis fenêtre de 2 s nominale.
// Mesure le débit réel de consommation du DMA (trames stéréo/s) au réglage
// courant : préchauffage (DMA vide absorbé sans bloquer), puis ~1 s de
// silence chronométré.
static uint32_t measureEffectiveRate() {
    static uint16_t sil[256];
    for (size_t i = 0; i < 256; i++) sil[i] = 0x8000;
    size_t frames = 0;
    while (frames < 4096) {
        size_t written = 0;
        i2s_write(SPEAKER_I2S_PORT, sil, sizeof(sil), &written, portMAX_DELAY);
        frames += written / 4;
    }
    uint32_t t0 = millis();
    frames = 0;
    while (frames < 16000) {
        size_t written = 0;
        i2s_write(SPEAKER_I2S_PORT, sil, sizeof(sil), &written, portMAX_DELAY);
        frames += written / 4;     // 4 octets par trame stéréo 16 bits
    }
    uint32_t dt = millis() - t0;
    if (dt < 50) return 0;         // aberrant
    return 16000UL * 1000UL / dt;
}

// Facteur de duplication des échantillons (voir calibrateDacClock).
static float s_dupRatio = 5.52f;

static void calibrateDacClock() {
    // On NE corrige PAS l'horloge : mesures [cal] — req 16000 → eff 88397
    // (5,52×, reproductible au Hz près entre les boots), req 4000 → 22130,
    // et en dessous le diviseur devient chaotique (req 1763 → eff 250000 !).
    // Le minimum atteignable (~22 kHz) reste 1,38× trop rapide : impossible
    // d'obtenir 16 kHz réels via i2s_set_sample_rates. Stratégie inverse :
    // horloge laissée au réglage nominal STABLE, et chaque échantillon est
    // dupliqué eff/16000 fois à l'alimentation (suréchantillonnage ZOH,
    // inaudible : le DAC produit le même escalier qu'à 16 kHz natifs).
    uint32_t effective = measureEffectiveRate();
    if (effective == 0) return;                       // mesure ratée : garder l'ancien ratio
    float ratio = (float)effective / SPEAKER_SAMPLE_RATE;
    if (ratio < 1.0f) ratio = 1.0f;
    if (ratio > 20.0f) ratio = 20.0f;
    s_dupRatio = ratio;
}

static void i2sWriterTask(void* arg) {
    (void)arg;
    constexpr size_t PCM_SAMPLES = 128;
    static uint16_t pcmBuffer[PCM_SAMPLES];  // non signé : format du DAC intégré

    // Calibrer l'horloge pendant que le pré-buffer se remplit (le flux BT
    // s'accumule dans le ring PSRAM de 10 s : rien n'est perdu).
    calibrateDacClock();

    // PRÉ-BUFFER : ne pas commencer à jouer avant ~1,5 s d'audio (ou fin de
    // flux). Le PC envoie 64 ms d'audio par 60 ms : partir immédiatement
    // laisse le buffer au bord du vide et chaque micro-retard BT injecte du
    // silence entre les vrais échantillons -> hachage continu (le symptôme
    // « grésillement long de la durée du wav »). L'entrée étant légèrement
    // plus rapide que la sortie, après le pré-buffer la famine ne revient pas.
    while (s_active && !s_finishing) {
        size_t buffered = (s_writePos >= s_readPos) ? (s_writePos - s_readPos)
                                                    : (s_bufferSize - s_readPos + s_writePos);
        if (buffered >= SPEAKER_SAMPLE_RATE * 3 / 2) break;   // 1,5 s
        vTaskDelay(pdMS_TO_TICKS(20));
    }

    while (s_active) {
        size_t available = (s_writePos >= s_readPos) ? (s_writePos - s_readPos)
                                                     : (s_bufferSize - s_readPos + s_writePos);
        // ⚠️ Compte d'ÉCHANTILLONS (la v1 bornait à sizeof() = 2x trop ->
        // écrasement de pile de la tâche -> panic/reboot).
        size_t toRead = (available > PCM_SAMPLES) ? PCM_SAMPLES : available;

        if (toRead == 0) {
            // Fin de flux (tts_end) ET buffer vide : sortie propre — c'est le
            // drain qui évite d'avaler la fin des phrases (l'ancien handler
            // stoppait dès le dernier chunk reçu, buffer encore plein).
            if (s_finishing) {
                break;
            }
            // Pas de données : silence (mi-échelle DAC) pour éviter les pops.
            for (size_t i = 0; i < PCM_SAMPLES; i++) pcmBuffer[i] = 0x8000;
            size_t written = 0;
            i2s_write(SPEAKER_I2S_PORT, pcmBuffer, sizeof(pcmBuffer), &written,
                      20 / portTICK_PERIOD_MS);
            continue;
        }

        // µ-law -> PCM16 signé -> non signé (le DAC intégré lit les 8 bits
        // hauts d'un échantillon non signé ; du signé brut = distorsion).
        // Chaque échantillon source est répété s_dupRatio fois (accumulateur
        // fractionnaire) pour compenser l'horloge 5,5× trop rapide, chaque
        // répétition occupant les slots gauche+droit d'une trame stéréo.
        static float dupAcc = 0.0f;
        size_t frames = 0;
        esp_err_t err = ESP_OK;
        for (size_t i = 0; i < toRead && err == ESP_OK; i++) {
            int16_t s = ulaw2linear(s_buffer[s_readPos]);
            uint16_t u = (uint16_t)(s + 32768);
            s_readPos = (s_readPos + 1) % s_bufferSize;
            dupAcc += s_dupRatio;
            int reps = (int)dupAcc;
            dupAcc -= reps;
            for (int r = 0; r < reps; r++) {
                pcmBuffer[2 * frames] = u;
                pcmBuffer[2 * frames + 1] = u;
                frames++;
                if (frames == PCM_SAMPLES / 2) {
                    size_t written = 0;
                    err = i2s_write(SPEAKER_I2S_PORT, pcmBuffer,
                                    frames * 2 * sizeof(uint16_t), &written,
                                    100 / portTICK_PERIOD_MS);
                    frames = 0;
                    if (err != ESP_OK) break;
                }
            }
        }
        if (frames > 0 && err == ESP_OK) {
            size_t written = 0;
            err = i2s_write(SPEAKER_I2S_PORT, pcmBuffer,
                            frames * 2 * sizeof(uint16_t), &written,
                            100 / portTICK_PERIOD_MS);
        }
        if (err != ESP_OK) {
            break;
        }
    }

    // Teardown par la tâche uniquement.
    s_active = false;            // (cas drain : personne n'appellera stop())
    s_finishing = false;
    i2s_driver_uninstall(SPEAKER_I2S_PORT);
    // ÉTEINDRE le DAC : après l'uninstall il reste figé à mi-échelle
    // (~1,65 V) dans l'ampli toujours alimenté du Fire -> courant continu.
    dac_output_disable(DAC_CHANNEL_1);
    // Et re-libérer GPIO 26 (Port B / NeoHEX) que le mode DAC a réquisitionné
    // — FastLED le reconfigurera à son prochain show().
    dac_output_disable(DAC_CHANNEL_2);
    gpio_reset_pin(GPIO_NUM_26);
    gpio_set_direction(GPIO_NUM_26, GPIO_MODE_OUTPUT);
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
    // Trames STÉRÉO : le périphérique consomme 32 bits (G+D) par trame — en
    // mono il avalait deux échantillons par trame = lecture 2x trop rapide
    // (la voix embarquée jouait en chipmunk). Chaque échantillon est dupliqué
    // G/D par la tâche.
    cfg.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;
    // MSB : convention attendue par le DAC intégré (STAND_I2S décale d'un
    // bit l'alignement des échantillons sur les 8 bits utiles du DAC).
    cfg.communication_format = I2S_COMM_FORMAT_STAND_MSB;
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
    // Ré-activer explicitement le DAC : après un uninstall (cycle précédent
    // ou passage micro), le routage ne survit pas toujours au réinstall.
    dac_output_enable(DAC_CHANNEL_1);
    // ⚠️ LIBÉRER le canal 2 : i2s_set_pin(NULL) en mode DAC réquisitionne
    // LES DEUX broches DAC (25 ET 26) — or GPIO 26 = Port B = la ligne de
    // données du NeoHEX. Sans cette libération, les LED du port B meurent
    // dès le premier passage du speaker (donc dès le bip de boot).
    dac_output_disable(DAC_CHANNEL_2);
    gpio_reset_pin(GPIO_NUM_26);
    gpio_set_direction(GPIO_NUM_26, GPIO_MODE_OUTPUT);

    // La calibration de l'horloge se fait DANS la tâche de lecture (en
    // parallèle du pré-buffer) — voir calibrateDacClock().

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

void speakerPlayFinish() {
    // Fin de flux : la tâche draine le buffer puis fait le teardown seule.
    if (s_active) {
        s_finishing = true;
    }
}

void speakerPlayTestTone() {
    // Bip 440 Hz (~0,4 s) par le pipeline complet : diagnostic du chemin
    // DAC indépendamment du PC. Bloquant, réservé au boot.
    if (!speakerPlayStart()) return;
    const int SAMPLES = SPEAKER_SAMPLE_RATE * 2 / 5;
    uint8_t chunk[160];
    size_t idx = 0;
    for (int i = 0; i < SAMPLES; i++) {
        float v = sinf(2.0f * 3.14159265f * 440.0f * i / SPEAKER_SAMPLE_RATE);
        int16_t s = (int16_t)(12000.0f * v);
        // encodeur µ-law local (miroir de ulaw2linear)
        int16_t pcm = s; uint8_t sign = 0;
        if (pcm < 0) { pcm = -pcm; sign = 0x80; }
        if (pcm > 32635) pcm = 32635;
        pcm += 0x84;
        uint8_t exponent = 7;
        for (int16_t mask = 0x4000; (pcm & mask) == 0 && exponent > 0; mask >>= 1) exponent--;
        uint8_t mantissa = (pcm >> (exponent + 3)) & 0x0F;
        chunk[idx++] = ~(sign | (exponent << 4) | mantissa);
        if (idx == sizeof(chunk)) { speakerPlayFeed(chunk, idx); idx = 0; }
    }
    if (idx > 0) speakerPlayFeed(chunk, idx);
    // Fin de flux : la tâche saute le pré-buffer, joue tout et s'arrête seule.
    speakerPlayFinish();
    for (int i = 0; i < 100 && speakerPlayIsPlaying(); i++) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }
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
