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
#pragma once
#include <cstdint>

// Button definitions for M5Stack Core 2
enum class AppButton {
    A = 0,  // Left button (Approve)
    B = 1,  // Middle button (Reject)
    C = 2   // Right button (Cancel)
};

class ButtonManager {
public:
    ButtonManager();
    
    // Check if a button was just pressed (non-blocking)
    bool wasPressed(AppButton btn);
    
    // Check if a button is currently held
    bool isHeld(AppButton btn);
    
    // Update button states (call in loop)
    void update();
    
    // Vibrate the device
    void vibrate(uint8_t intensity = 100, uint16_t duration = 50);
    
private:
    bool prevStates[3];
    bool currStates[3];
    bool pressedFlags[3];
};
