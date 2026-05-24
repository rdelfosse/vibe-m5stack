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
