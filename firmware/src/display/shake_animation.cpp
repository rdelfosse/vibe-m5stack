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
