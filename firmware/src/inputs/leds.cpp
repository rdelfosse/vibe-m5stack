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
// Port B (NeoPixel, NeoHEX 37) : GPIO 26.
// Port C                  : GPIO 17 (réservé PSRAM, désactivé — voir begin()).
static constexpr int RING_LEDS    = 10;
static constexpr int RING_PIN     = 15;
static constexpr int MATRIX_LEDS  = 37;  // NeoHEX has 37 LEDs, not 38
static constexpr int MATRIX_B_PIN = 26;
static constexpr int MATRIX_C_PIN = 17;

// --- NeoHEX Geometry (37 LEDs, 0-based indexing) -----------------------------
// Concentric rings: 1 + 6 + 12 + 18 = 37
static constexpr uint8_t RINGS = 4;      // 0 = centre, 1-3 = rings
static constexpr uint8_t CENTER_LED = 18; // LED centrale (index 0-based)

// Ring of each LED (index 0..36 in wiring order by rows)
static const uint8_t RING_OF[MATRIX_LEDS] = {
    3,3,3,3,          // rangée 0 (idx 0..3)
    3,2,2,2,3,        // rangée 1 (idx 4..8)
    3,2,1,1,2,3,      // rangée 2 (idx 9..14)
    3,2,1,0,1,2,3,    // rangée 3 (idx 15..21)  -> idx 18 = centre
    3,2,1,1,2,3,      // rangée 4 (idx 22..27)
    3,2,2,2,3,        // rangée 5 (idx 28..32)
    3,3,3,3           // rangée 6 (idx 33..36)
};

// Outer ring (ring 3, 18 LEDs) in clockwise angular order, starting from top-left
static const uint8_t OUTER_RING_CW[18] = {
    0,1,2,3, 8,14,21,27,32, 36,35,34,33, 28,22,15,9,4
};

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

// Thinking activity colors
static const CRGB COLOR_THINK_CYAN    = CRGB(0, 180, 255);
static const CRGB COLOR_THINK_BLUE    = CRGB(0, 90, 255);
static const CRGB COLOR_THINK_VIOLET  = CRGB(150, 0, 255);

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
static ThinkingActivity currentThinkingActivity = ThinkingActivity::REASONING;
static bool flourishActive = false;
static uint32_t flourishStartMs = 0;
static constexpr uint32_t FLOURISH_DURATION_MS = 1500;

// --- Thinking animation state ----------------------------------------------
// Sparkle (REASONING)
static uint32_t lastSparkleMs = 0;

// Ripple (TOOL_EXEC)
static uint32_t lastRippleMs = 0;
static uint8_t rippleRadius = 0;  // 0 to RINGS-1
static constexpr uint32_t RIPPLE_PERIOD_MS = 700;

// Radar (READING)
static uint32_t lastRadarMs = 0;
static uint8_t radarHead = 0;     // position in OUTER_RING_CW
static constexpr uint32_t RADAR_STEP_MS = 60;

// Fill (STREAMING)
static uint32_t lastFillMs = 0;
static uint8_t fillLevel = 0;     // 0 to RINGS (then resets)
static bool fillFilling = true;   // true = filling, false = emptying
static constexpr uint32_t FILL_PERIOD_MS = 900;

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

// --- Thinking animation helpers --------------------------------------------

// Sparkle: random LEDs twinkle and fade (REASONING)
static void animSparkle(uint32_t now) {
    if (now - lastSparkleMs > 80) {
        lastSparkleMs = now;
        // Fade all LEDs
        fadeToBlackBy(matrixB, MATRIX_LEDS, 40);
        // Light 1-2 random LEDs in cyan at random brightness
        int num = random8(2) + 1; // 1 or 2 LEDs
        for (int i = 0; i < num; i++) {
            uint8_t idx = random8(MATRIX_LEDS);
            uint8_t brightness = random8(128, 255);
            matrixB[idx] = COLOR_THINK_CYAN;
            matrixB[idx] %= brightness;
        }
    }
}

// Ripple: radial wave from center to outer ring (TOOL_EXEC)
static void animRipple(uint32_t now) {
    if (now - lastRippleMs > 20) {
        lastRippleMs = now;
        
        // Calculate radius based on time
        uint32_t periodElapsed = now % RIPPLE_PERIOD_MS;
        rippleRadius = map(periodElapsed, 0, RIPPLE_PERIOD_MS, 0, RINGS * 255);
        rippleRadius /= 255;
        if (rippleRadius >= RINGS) rippleRadius = RINGS - 1;
        
        // For each LED, brightness based on distance from ripple radius
        for (int i = 0; i < MATRIX_LEDS; i++) {
            uint8_t ring = RING_OF[i];
            int8_t dist = abs((int8_t)ring - (int8_t)rippleRadius);
            // Brightness: peak at rippleRadius, falloff on neighbors
            uint8_t brightness = 255 - (dist * 85);
            if (brightness > 255) brightness = 255;
            
            matrixB[i] = COLOR_THINK_BLUE;
            matrixB[i] %= brightness;
        }
    }
}

// Radar: rotating point on outer ring with trail (READING)
static void animRadar(uint32_t now) {
    if (now - lastRadarMs > RADAR_STEP_MS) {
        lastRadarMs = now;
        
        // Fade the outer ring by applying fade to all LEDs
        for (int i = 0; i < MATRIX_LEDS; i++) {
            if (RING_OF[i] == 3) { // Only outer ring
                matrixB[i].fadeToBlackBy(64);
            }
        }
        
        // Advance head and light it
        radarHead = (radarHead + 1) % 18;
        uint8_t headIdx = OUTER_RING_CW[radarHead];
        matrixB[headIdx] = COLOR_THINK_CYAN;
        
        // Light a few LEDs behind with violet for trail
        for (int i = 1; i <= 2; i++) {
            uint8_t trailPos = (radarHead - i + 18) % 18;
            uint8_t trailIdx = OUTER_RING_CW[trailPos];
            matrixB[trailIdx] = COLOR_THINK_VIOLET;
            matrixB[trailIdx] %= 128;
        }
        
        // Inner rings: dim cyan base
        for (int i = 0; i < MATRIX_LEDS; i++) {
            if (RING_OF[i] < 3) { // Rings 0, 1, 2
                matrixB[i] = COLOR_THINK_CYAN;
                matrixB[i] %= 32;
            }
        }
    }
}

// Fill: progressive fill from center to outer, then empty (STREAMING)
static void animFill(uint32_t now) {
    if (now - lastFillMs > 20) {
        lastFillMs = now;
        
        // Calculate fill level based on time
        uint32_t periodElapsed = now % FILL_PERIOD_MS;
        fillLevel = map(periodElapsed, 0, FILL_PERIOD_MS, 0, RINGS * 255);
        fillLevel /= 255;
        if (fillLevel >= RINGS) {
            fillLevel = RINGS - 1;
        }
        
        // Fill all LEDs in rings <= fillLevel
        for (int i = 0; i < MATRIX_LEDS; i++) {
            uint8_t ring = RING_OF[i];
            if (ring <= fillLevel) {
                // Filled: interpolate from blue to cyan based on ring
                uint8_t blend = map(ring, 0, RINGS - 1, 0, 255);
                // Manual linear interpolation
                uint8_t r = map(blend, 0, 255, COLOR_THINK_BLUE.r, COLOR_THINK_CYAN.r);
                uint8_t g = map(blend, 0, 255, COLOR_THINK_BLUE.g, COLOR_THINK_CYAN.g);
                uint8_t b = map(blend, 0, 255, COLOR_THINK_BLUE.b, COLOR_THINK_CYAN.b);
                matrixB[i] = CRGB(r, g, b);
                matrixB[i] %= 200;
            } else {
                // Not filled: off
                matrixB[i] = CRGB::Black;
            }
        }
    }
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

void setAgentState(AgentState state, bool flourish, ThinkingActivity activity) {
    const uint32_t now = millis();
    currentAgentState = state;
    currentThinkingActivity = activity;

    if (state == AgentState::DONE && flourish) {
        flourishActive = true;
        flourishStartMs = now;
    }
    if (flourishActive && (now - flourishStartMs) >= FLOURISH_DURATION_MS) {
        flourishActive = false;
    }

    switch (state) {
        case AgentState::THINKING: {
            // Ring: bleu qui respire (unchanged from original)
            static uint8_t pulse = 80; static bool up = true; static uint32_t lastP = 0;
            if (now - lastP > 30) { lastP = now; breathe(pulse, up, 8, 40, 210); }
            CRGB rc = COLOR_THINKING; rc %= pulse;
            fill_solid(ring, RING_LEDS, rc);

            // Matrix B: dispatch based on activity
            switch (activity) {
                case ThinkingActivity::REASONING:
                    animSparkle(now);
                    break;
                case ThinkingActivity::TOOL_EXEC:
                    animRipple(now);
                    break;
                case ThinkingActivity::READING:
                    animRadar(now);
                    break;
                case ThinkingActivity::STREAMING:
                    animFill(now);
                    break;
            }
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
