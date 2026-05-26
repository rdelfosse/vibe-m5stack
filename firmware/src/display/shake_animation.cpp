#include "shake_animation.h"
#include <Arduino.h>   // millis(), random()

ShakeAnimation shakeAnimation;

void ShakeAnimation::trigger() {
    active = true;
    startMs = millis();
}

bool ShakeAnimation::tick() {
    if (!active) return false;
    if (millis() - startMs >= DURATION_MS) {
        active = false;
        return true;   // signal the caller to clear the offset
    }
    return false;
}

void ShakeAnimation::rollOffset(int8_t& dx, int8_t& dy) const {
    dx = static_cast<int8_t>(random(-MAX_OFFSET, MAX_OFFSET + 1));
    dy = static_cast<int8_t>(random(-MAX_OFFSET, MAX_OFFSET + 1));
}
