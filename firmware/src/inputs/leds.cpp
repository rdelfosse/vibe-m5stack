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
// Port B (NeoMatrix 5x5)  : GPIO 26.
// Port C (NeoMatrix 5x5)  : GPIO 17.  (Requires PSRAM disabled, else GPIO 17 is reserved.)
static constexpr int RING_LEDS    = 10;
static constexpr int RING_PIN     = 15;
static constexpr int MATRIX_LEDS  = 50;
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

// --- LED buffers (static, zero-init in .bss) --------------------------------
static CRGB ring[RING_LEDS];
static CRGB matrixB[MATRIX_LEDS];
static CRGB matrixC[MATRIX_LEDS];

// --- Animation state ---------------------------------------------------------
static uint32_t lastRingStepMs   = 0;
static uint32_t lastMatrixStepMs = 0;
static uint8_t  ringOffset       = 0;
static uint8_t  matrixColorIdx   = 0;

// --- Helpers ----------------------------------------------------------------
static void clear(CRGB* buf, int count) {
    for (int i = 0; i < count; i++) buf[i] = CRGB::Black;
}

// --- Public API -------------------------------------------------------------
void begin() {
    FastLED.addLeds<WS2812B, RING_PIN,     GRB>(ring,    RING_LEDS);
    FastLED.addLeds<WS2812B, MATRIX_B_PIN, GRB>(matrixB, MATRIX_LEDS);
    // Port C (GPIO 17) réservé par la PSRAM. Si tu désactives la PSRAM dans
    // platformio.ini, tu peux ré-activer cette ligne.
    // FastLED.addLeds<WS2812B, MATRIX_C_PIN, GRB>(matrixC, MATRIX_LEDS);

    // Cap total LED current at ~400 mA so the USB rail can also feed the
    // ESP32, the LCD backlight and the vibration motor without browning out.
    // FastLED will auto-scale colors before each show() to stay under budget.
    FastLED.setMaxPowerInVoltsAndMilliamps(5, 400);

    FastLED.setBrightness(32);  // pre-cap baseline; setMaxPower further trims
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

    // Side ring : 5-color Mistral chase rotating one step every 180 ms.
    if (now - lastRingStepMs > 180) {
        lastRingStepMs = now;
        ringOffset = (ringOffset + 1) % 5;
        for (int i = 0; i < RING_LEDS; i++) {
            ring[i] = MISTRAL_PALETTE[(i + ringOffset) % 5];
        }
        changed = true;
    }

    // Port B + Port C matrices : flood-fill, cycling through the 5 Mistral
    // colors every 400 ms (full cycle = 2 s).
    if (now - lastMatrixStepMs > 400) {
        lastMatrixStepMs = now;
        matrixColorIdx = (matrixColorIdx + 1) % 5;
        const CRGB color = MISTRAL_PALETTE[matrixColorIdx];
        fill_solid(matrixB, MATRIX_LEDS, color);
        fill_solid(matrixC, MATRIX_LEDS, color);
        changed = true;
    }

    if (changed) FastLED.show();
}

}  // namespace led
