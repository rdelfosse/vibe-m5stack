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
#include "mic_capture.h"
#include <Arduino.h>
#include <driver/i2s.h>
#include <driver/adc.h>
#include <esp_heap_caps.h>

// GPIO 34 = ADC1_CHANNEL_6 (micro du socle M5GO, polarisé ~VCC/2).
// ADC1 est compatible avec le Bluetooth Classic actif (ADC2 ne l'est pas).
static const i2s_port_t MIC_I2S_PORT = I2S_NUM_0;
static const adc1_channel_t MIC_ADC_CHANNEL = ADC1_CHANNEL_6;

// Gain numérique (décalage) appliqué avant µ-law. x4 saturait (pics à 32124) ;
// µ-law encaisse bien la dynamique, mieux vaut sous-amplifier qu'écrêter.
static const int MIC_GAIN_SHIFT = 1;  // x2

static uint8_t* s_buffer = nullptr;
static size_t s_size = 0;
static bool s_active = false;
static uint32_t s_startMs = 0;
static uint32_t s_durationMs = 0;
// Décimation par moyenne (facteur 3) : l'I2S-ADC tourne réellement ~2,7x plus
// vite que demandé (42,7 kHz mesurés pour 16 k). Sans décimation le flux µ-law
// (42,7 Ko/s -> ~57 Ko/s en base64) sature le lien BT : l'envoi bloque loop(),
// le DMA déborde et l'audio se hache. À /3 : ~14,3 kHz, ~19 Ko/s encodé — ça
// passe, la moyenne fait office d'anti-repliement, et le PC recale sur 16 kHz
// grâce à la durée mesurée.
static const int MIC_DECIMATE = 3;
static int32_t s_decimAcc = 0;
static int s_decimCount = 0;
// Suppression DC dynamique (IIR) : la polarisation réelle du MEMS n'est pas
// exactement 2048 et dérive — un offset fixe laissait un DC massif.
static int32_t s_dcEstimate = 2048 << 8;

// G.711 µ-law : 16 bits signés -> 8 bits log. Suffisant pour de la parole STT,
// et divise par deux le volume à transférer sur le lien BT.
static uint8_t linear2ulaw(int16_t pcm) {
    const int16_t BIAS = 0x84;
    const int16_t CLIP = 32635;
    uint8_t sign = 0;
    if (pcm < 0) {
        pcm = -pcm;
        sign = 0x80;
    }
    if (pcm > CLIP) pcm = CLIP;
    pcm += BIAS;
    uint8_t exponent = 7;
    for (int16_t mask = 0x4000; (pcm & mask) == 0 && exponent > 0; mask >>= 1) {
        exponent--;
    }
    uint8_t mantissa = (pcm >> (exponent + 3)) & 0x0F;
    return ~(sign | (exponent << 4) | mantissa);
}

bool micCaptureStart() {
    if (s_active) return true;

    if (s_buffer == nullptr) {
        // PSRAM : 160 Ko pour 10 s de µ-law 16 kHz.
        s_buffer = (uint8_t*)heap_caps_malloc(MIC_BUFFER_SIZE, MALLOC_CAP_SPIRAM);
        if (s_buffer == nullptr) {
            s_buffer = (uint8_t*)malloc(MIC_BUFFER_SIZE);  // fallback DRAM
        }
        if (s_buffer == nullptr) return false;
    }
    s_size = 0;

    i2s_config_t cfg = {};
    cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_ADC_BUILT_IN);
    cfg.sample_rate = MIC_SAMPLE_RATE;
    cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
    // ONLY_RIGHT : l'ADC intégré livre ses données sur le slot droit (cf.
    // exemples officiels M5Stack Microphone). ONLY_LEFT donnait du garbage.
    cfg.channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT;
    cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
    // 8 x 512 éch. = ~96 ms de marge au débit ADC réel (~42,7 kHz) : encaisse
    // les blocages brefs de loop() quand le lien BT applique sa contre-pression.
    cfg.dma_buf_count = 8;
    cfg.dma_buf_len = 512;
    cfg.use_apll = false;

    if (i2s_driver_install(MIC_I2S_PORT, &cfg, 0, nullptr) != ESP_OK) return false;
    if (i2s_set_adc_mode(ADC_UNIT_1, MIC_ADC_CHANNEL) != ESP_OK) {
        i2s_driver_uninstall(MIC_I2S_PORT);
        return false;
    }
    if (i2s_adc_enable(MIC_I2S_PORT) != ESP_OK) {
        i2s_driver_uninstall(MIC_I2S_PORT);
        return false;
    }
    s_active = true;
    s_startMs = millis();
    s_durationMs = 0;
    s_dcEstimate = 2048 << 8;
    s_decimAcc = 0;
    s_decimCount = 0;
    return true;
}

bool micCapturePump() {
    if (!s_active || s_buffer == nullptr) return false;

    static uint16_t raw[256];
    size_t bytesRead = 0;
    // timeout 0 : draine ce qui est prêt, ne bloque jamais la loop.
    // Boucler tant que le DMA rend des buffers pleins : si loop() dépasse
    // 16 ms, un seul read par frame prendrait du retard et le DMA déborderait.
    do {
        bytesRead = 0;
        i2s_read(MIC_I2S_PORT, raw, sizeof(raw), &bytesRead, 0);
        size_t samples = bytesRead / 2;
        for (size_t i = 0; i < samples; i++) {
            if (s_size >= MIC_BUFFER_SIZE) return false;  // borne 60 s atteinte
            // Échantillon ADC 12 bits (canal dans les 4 bits hauts).
            int32_t adc = (int32_t)(raw[i] & 0x0FFF);
            // Retrait de la composante continue par IIR (alpha = 1/256) :
            // suit la polarisation réelle du MEMS et sa dérive.
            s_dcEstimate += ((adc << 8) - s_dcEstimate) >> 8;
            int32_t s = adc - (s_dcEstimate >> 8);
            // Décimation /3 par moyenne (voir MIC_DECIMATE ci-dessus).
            s_decimAcc += s;
            if (++s_decimCount < MIC_DECIMATE) continue;
            s = s_decimAcc / MIC_DECIMATE;
            s_decimAcc = 0;
            s_decimCount = 0;
            s <<= (4 + MIC_GAIN_SHIFT);   // 12 -> 16 bits, puis gain
            if (s > 32767) s = 32767;
            if (s < -32768) s = -32768;
            s_buffer[s_size++] = linear2ulaw((int16_t)s);
        }
    } while (bytesRead == sizeof(raw));
    return true;
}

void micCaptureStop() {
    if (!s_active) return;
    // Dernier drain avant de couper (récupère la fin de la phrase).
    micCapturePump();
    s_durationMs = millis() - s_startMs;
    i2s_adc_disable(MIC_I2S_PORT);
    i2s_driver_uninstall(MIC_I2S_PORT);
    s_active = false;
}

const uint8_t* micCaptureData() { return s_buffer; }
size_t micCaptureSize() { return s_size; }
uint32_t micCaptureDurationMs() { return s_durationMs; }

void micCaptureRelease() {
    if (s_buffer != nullptr) {
        free(s_buffer);
        s_buffer = nullptr;
    }
    s_size = 0;
}
