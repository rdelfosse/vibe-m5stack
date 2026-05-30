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
#include "buttons.h"
#include <M5Stack.h>

ButtonManager::ButtonManager() {
    for (int i = 0; i < 3; i++) {
        prevStates[i] = false;
        currStates[i] = false;
        pressedFlags[i] = false;
    }
}

void ButtonManager::update() {
    // Update previous states
    for (int i = 0; i < 3; i++) {
        prevStates[i] = currStates[i];
    }
    
    // Read current states (M5Stack button API - works on Core Fire & Core 2)
    currStates[0] = M5.BtnA.wasPressed();
    currStates[1] = M5.BtnB.wasPressed();
    currStates[2] = M5.BtnC.wasPressed();
    
    // Set pressed flags for rising edge detection
    for (int i = 0; i < 3; i++) {
        if (currStates[i] && !prevStates[i]) {
            pressedFlags[i] = true;
        }
    }
}

bool ButtonManager::wasPressed(AppButton btn) {
    bool result = pressedFlags[static_cast<int>(btn)];
    pressedFlags[static_cast<int>(btn)] = false; // Clear flag
    return result;
}

bool ButtonManager::isHeld(AppButton btn) {
    return currStates[static_cast<int>(btn)];
}

void ButtonManager::vibrate(uint8_t intensity, uint16_t duration) {
    // M5Stack Core 2 has vibration motor (AXP192 LDO3)
    // M5Stack Fire uses speaker beep as feedback
    #if defined(ARDUINO_M5STACK_CORE2)
        M5.Axp.SetLDOEnable(3, true);
        ::delay(duration);
        M5.Axp.SetLDOEnable(3, false);
    #else
        // Use speaker beep as vibration substitute (Core Fire, etc.)
        M5.Speaker.tone(1000, duration);
        ::delay(10); // Small delay to let tone finish
    #endif
}
