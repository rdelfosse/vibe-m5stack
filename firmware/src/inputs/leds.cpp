// NOTE: this file does NOT include M5Stack.h. FastLED's headers define an
// enum with `RED` and `BLACK` identifiers, which collide with the macros
// `#define RED 0xF800` / `#define BLACK 0x0000` defined by M5Stack's
// ILI9341_Defines.h. Keeping FastLED isolated here avoids the conflict.
#include "leds.h"
#include <FastLED.h>
#include <Arduino.h>

namespace led {

// --- Hardware layout ---------------------------------------------------------
// M5Stack Fire side ring : 10 WS2812B on GPIO 15 (5 LEDs per side).
// Port B (NeoPixel, 38)   : GPIO 26.
// Port C                  : GPIO 17 (réservé PSRAM, désactivé — voir begin()).
static constexpr int RING_LEDS    = 10;
static constexpr int RING_PIN     = 15;
static constexpr int MATRIX_LEDS  = 38;
static constexpr int MATRIX_B_PIN = 26;
static constexpr int MATRIX_C_PIN = 17;

// Mistral palette (matches the logo SVG).
static const CRGB MISTRAL_PALETTE[5] = {
    CRGB(233,  39,   0),  // Red          #E92700
    CRGB(250,  80,  15),  // Orange Dark  #FA500F
    CRGB(255, 130,   5),  // Orange       #FF8205
    CRGB(255, 175,   0),  // Orange Light #FFAF00
    CRGB(255, 215,   0),  // Yellow       #FFD700
};

// Agent state colors
// THINKING = bleu (travaille tranquillement) ; WAITING = ambre (réclame ton
// attention) ; DONE/IDLE = vert. Couleurs volontairement contrastées pour
// distinguer les états d'un coup d'œil. L'arc-en-ciel Mistral est réservé à
// l'écran d'approbation (updateApprovalAnimation).
static const CRGB COLOR_THINKING = CRGB(0, 128, 255);
static const CRGB COLOR_WAITING  = CRGB(255, 191, 0);
static const CRGB COLOR_DONE     = CRGB(0, 200, 0);
static const CRGB COLOR_DONE_FLOURISH = CRGB(0, 255, 0);
static const CRGB COLOR_ERROR    = CRGB(255, 0, 0);

// --- LED buffers (static, zero-init in .bss) --------------------------------
static CRGB ring[RING_LEDS];
static CRGB matrixB[MATRIX_LEDS];
static CRGB matrixC[MATRIX_LEDS];

// --- Animation state ---------------------------------------------------------
static uint32_t lastRingStepMs   = 0;
static uint32_t lastMatrixStepMs = 0;
static uint8_t  ringOffset       = 0;
static uint8_t  matrixColorIdx   = 0;

// --- Agent state tracking --------------------------------------------------
static AgentState currentAgentState = AgentState::DONE;
static bool flourishActive = false;
static uint32_t flourishStartMs = 0;
static constexpr uint32_t FLOURISH_DURATION_MS = 1500;

// --- Blinking state for ERROR/DEAD/STUCK -------------------------------------
static uint32_t lastBlinkMs = 0;
static bool blinkOn = false;
static constexpr uint32_t BLINK_INTERVAL_MS = 500;

// --- Helpers ----------------------------------------------------------------
static void clear(CRGB* buf, int count) {
    for (int i = 0; i < count; i++) buf[i] = CRGB::Black;
}

// Breathing helper: triangular brightness ramp between lo and hi.
static uint8_t breathe(uint8_t& value, bool& up, uint8_t step, uint8_t lo, uint8_t hi) {
    if (up) {
        value = (value + step >= hi) ? hi : value + step;
        if (value >= hi) up = false;
    } else {
        value = (value <= lo + step) ? lo : value - step;
        if (value <= lo) up = true;
    }
    return value;
}

// Comet: a moving bright head with a fading tail (wraps around).
static void comet(CRGB* buf, int count, uint8_t& head, const CRGB& color, uint8_t fadeAmt) {
    fadeToBlackBy(buf, count, fadeAmt);
    buf[head % count] = color;
    head = (head + 1) % count;
}

// KITT scanner: a bright head bouncing back and forth with a fading tail.
static void scanner(CRGB* buf, int count, int& pos, int& dir, const CRGB& color, uint8_t fadeAmt) {
    fadeToBlackBy(buf, count, fadeAmt);
    if (pos < 0) pos = 0;
    if (pos > count - 1) pos = count - 1;
    buf[pos] = color;
    pos += dir;
    if (pos >= count - 1) { pos = count - 1; dir = -1; }
    else if (pos <= 0)    { pos = 0;         dir = 1; }
}

// --- Public API -------------------------------------------------------------
void begin() {
    FastLED.addLeds<WS2812B, RING_PIN,     GRB>(ring,    RING_LEDS);
    FastLED.addLeds<WS2812B, MATRIX_B_PIN, GRB>(matrixB, MATRIX_LEDS);
    // Port C (GPIO 17) est réservé par la PSRAM (board_build.psram = enable,
    // requis par le mode Bluetooth). NE PAS enregistrer ce contrôleur FastLED :
    // piloter le RMT sur GPIO 17 entre en conflit avec le bus PSRAM, corrompt le
    // heap et fait crasher btc_spp_init au boot (Guru Meditation / reboot loop).
    // Si tu désactives la PSRAM ET le BT dans platformio.ini, tu peux le réactiver.
    // FastLED.addLeds<WS2812B, MATRIX_C_PIN, GRB>(matrixC, MATRIX_LEDS);
    FastLED.setMaxPowerInVoltsAndMilliamps(5, 400);
    FastLED.setBrightness(32);
    off();
}

void off() {
    clear(ring,    RING_LEDS);
    clear(matrixB, MATRIX_LEDS);
    clear(matrixC, MATRIX_LEDS);
    FastLED.show();
}

void updateApprovalAnimation() {
    const uint32_t now = millis();
    bool changed = false;

    if (now - lastRingStepMs > 180) {
        lastRingStepMs = now;
        ringOffset = (ringOffset + 1) % 5;
        for (int i = 0; i < RING_LEDS; i++) {
            ring[i] = MISTRAL_PALETTE[(i + ringOffset) % 5];
        }
        changed = true;
    }

    if (now - lastMatrixStepMs > 400) {
        lastMatrixStepMs = now;
        matrixColorIdx = (matrixColorIdx + 1) % 5;
        const CRGB color = MISTRAL_PALETTE[matrixColorIdx];
        fill_solid(matrixB, MATRIX_LEDS, color);
        changed = true;
    }

    if (changed) FastLED.show();
}

void setAgentState(AgentState state, bool flourish) {
    const uint32_t now = millis();
    currentAgentState = state;

    if (state == AgentState::DONE && flourish) {
        flourishActive = true;
        flourishStartMs = now;
    }
    if (flourishActive && (now - flourishStartMs) >= FLOURISH_DURATION_MS) {
        flourishActive = false;
    }

    switch (state) {
        case AgentState::THINKING: {
            // Ring: bleu qui respire. Matrix: comète bleue qui défile.
            static uint8_t pulse = 80; static bool up = true; static uint32_t lastP = 0;
            if (now - lastP > 30) { lastP = now; breathe(pulse, up, 8, 40, 210); }
            CRGB rc = COLOR_THINKING; rc %= pulse;
            fill_solid(ring, RING_LEDS, rc);

            static uint32_t lastC = 0; static uint8_t head = 0;
            if (now - lastC > 45) { lastC = now; comet(matrixB, MATRIX_LEDS, head, COLOR_THINKING, 60); }
            FastLED.show();
            break;
        }

        case AgentState::WAITING: {
            // Pulse ambre (l'agent attend ta saisie).
            static uint8_t pulse = 128; static bool up = true; static uint32_t lastP = 0;
            if (now - lastP > 100) { lastP = now; breathe(pulse, up, 10, 50, 200); }
            CRGB c = COLOR_WAITING; c %= pulse;
            fill_solid(ring, RING_LEDS, c);
            fill_solid(matrixB, MATRIX_LEDS, c);
            FastLED.show();
            break;
        }

        case AgentState::DONE: {
            CRGB c = flourishActive ? COLOR_DONE_FLOURISH : COLOR_DONE;
            fill_solid(ring, RING_LEDS, c);
            fill_solid(matrixB, MATRIX_LEDS, c);
            FastLED.show();
            break;
        }

        case AgentState::ERROR:
        case AgentState::DEAD:
        case AgentState::STUCK: {
            // Ring: rouge clignotant. Matrix: scanner rouge KITT (alarme).
            if (now - lastBlinkMs > BLINK_INTERVAL_MS) { lastBlinkMs = now; blinkOn = !blinkOn; }
            fill_solid(ring, RING_LEDS, blinkOn ? COLOR_ERROR : CRGB::Black);

            static uint32_t lastS = 0; static int pos = 0; static int dir = 1;
            if (now - lastS > 35) { lastS = now; scanner(matrixB, MATRIX_LEDS, pos, dir, COLOR_ERROR, 90); }
            FastLED.show();
            break;
        }
    }
}

void idle() {
    // Vert qui respire : vivant mais calme, rien ne te réclame.
    const uint32_t now = millis();
    static uint8_t pulse = 60; static bool up = true; static uint32_t lastP = 0;
    if (now - lastP > 40) {
        lastP = now;
        breathe(pulse, up, 4, 30, 160);
        CRGB c = COLOR_DONE; c %= pulse;
        fill_solid(ring, RING_LEDS, c);
        fill_solid(matrixB, MATRIX_LEDS, c);
        FastLED.show();
    }
}

}  // namespace led
