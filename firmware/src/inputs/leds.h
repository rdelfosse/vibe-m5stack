#pragma once

// Public LED API. Implementation is fully isolated in leds.cpp so that
// FastLED's headers (which use `RED`/`BLACK` as enum identifiers) never
// collide with M5Stack/TFT_eSPI's `#define RED 0xF800` etc.
namespace led {

void begin();
void off();

// Call repeatedly while waiting for the user's button press.
// Throttles itself; safe to call every loop tick.
//  - side ring (10 LEDs, GPIO 15) : Mistral palette chase
//  - port B + port C matrices (5x5, GPIO 26 + GPIO 17) : Mistral "M" blink
void updateApprovalAnimation();

}  // namespace led
