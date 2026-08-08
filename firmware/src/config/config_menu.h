// Vibe M5Stack - Configuration Menu UI
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
#include "config.h"

// Menu item types
enum class ConfigMenuItem {
    QUIET_MODE,
    LED_BRIGHTNESS,
    DEVICE_MODEL,
    EXIT,
    COUNT
};

class ConfigMenu {
public:
    ConfigMenu(ConfigManager& configManager);
    
    // Initialize the menu
    void begin();
    
    // Update menu state based on button input
    // btnCLongPress doit être un front « appui long C détecté » calculé par
    // l'appelant (timer ~1 s), PAS le niveau brut isHeld() — sinon tout tap C
    // fermerait le menu à la frame suivante.
    // Returns true if menu should remain open, false if it should close
    bool update(bool btnAPressed, bool btnBPressed, bool btnCPressed, bool btnCLongPress);
    
    // Draw the menu
    void draw(bool forced = false);
    
    // Get current selected item
    ConfigMenuItem getSelectedItem() const;
    
    // Check if menu is currently active
    bool isActive() const;
    
    // Open the menu (reset to first item)
    void open();
    
    // Close the menu
    void close();
    
    // Get the current configuration reference
    const DeviceConfig& getConfig() const;
    
private:
    ConfigManager& configManager;
    ConfigMenuItem selectedItem;
    bool active;
    bool needsRedraw;
    uint32_t lastDrawTime;
    
    // Navigation
    void moveNext();
    void movePrevious();
    void selectItem();
    
    // Value manipulation
    void toggleQuietMode();
    void cycleBrightness(bool forward);
    void cycleModel(bool forward);
};
