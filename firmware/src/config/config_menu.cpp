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
#include "config_menu.h"
#include <M5Stack.h>

ConfigMenu::ConfigMenu(ConfigManager& manager)
    : configManager(manager),
      selectedItem(ConfigMenuItem::QUIET_MODE),
      active(false),
      needsRedraw(true),
      lastDrawTime(0) {
}

void ConfigMenu::begin() {
    // Nothing to initialize here, M5Stack is already set up
}

bool ConfigMenu::update(bool btnAPressed, bool btnBPressed, bool btnCPressed, bool btnCLongPress) {
    if (!active) {
        return false;
    }

    // Handle navigation
    if (btnCLongPress) {
        // Long press C: exit menu without selecting (front calculé par l'appelant)
        close();
        return false;
    } else if (btnCPressed) {
        moveNext();
        needsRedraw = true;
    } else if (btnBPressed) {
        movePrevious();
        needsRedraw = true;
    } else if (btnAPressed) {
        selectItem();
        needsRedraw = true;

        // If EXIT was selected, close the menu
        if (selectedItem == ConfigMenuItem::EXIT) {
            close();
            return false;
        }
    }

    return true;
}

void ConfigMenu::draw(bool forced) {
    if (!active && !forced) {
        return;
    }

    // Ne repeindre que sur changement réel : un fillRect plein écran + textes à
    // 30 fps sature le bus SPI et fait bégayer les LED (cf. commentaire loop()).
    if (!forced && !needsRedraw) {
        return;
    }

    uint32_t now = ::millis();
    // Throttle anti-spam ; needsRedraw reste armé si on saute, donc le dessin
    // partira à la frame suivante.
    if (!forced && now - lastDrawTime < 33) {
        return;
    }
    
    lastDrawTime = now;
    
    // Draw menu background
    M5.Lcd.fillRect(0, 0, 320, 240, BLACK);
    
    // Draw title
    M5.Lcd.setTextFont(2);
    M5.Lcd.setTextSize(2);
    M5.Lcd.setTextColor(0xFDE0, BLACK);  // Yellow-ish
    M5.Lcd.setCursor(80, 10);
    M5.Lcd.print("CONFIG MENU");
    
    // Draw items
    M5.Lcd.setTextFont(2);
    M5.Lcd.setTextSize(1);
    
    // 8 items : 40 + 8*24 = 232 < 240 (bandeau d'aide 8px) — tient sur 240 px.
    // Recalculé pour 8 items : ITEM_HEIGHT = 24 au lieu de 26.
    const int ITEM_HEIGHT = 24;
    const int ITEM_Y_START = 40;
    const int ITEM_X = 20;
    const int SELECTOR_X = 5;
    
    for (int i = 0; i < static_cast<int>(ConfigMenuItem::COUNT); i++) {
        ConfigMenuItem item = static_cast<ConfigMenuItem>(i);
        int y = ITEM_Y_START + i * ITEM_HEIGHT;
        
        // Draw selector
        if (item == selectedItem && active) {
            M5.Lcd.fillRect(SELECTOR_X, y - 2, 10, ITEM_HEIGHT - 4, 0xFDE0);
        }
        
        // Draw item label
        M5.Lcd.setTextColor(WHITE, BLACK);
        M5.Lcd.setCursor(ITEM_X, y + 5);
        
        switch (item) {
            case ConfigMenuItem::QUIET_MODE: {
                const char* modeStr = configManager.get().quietMode ? "ON" : "OFF";
                M5.Lcd.printf("Quiet Mode: > %s\n", modeStr);
                break;
            }
            case ConfigMenuItem::LED_BRIGHTNESS: {
                M5.Lcd.printf("LED Brightness: > %d\n", configManager.get().ledBrightness);
                break;
            }
            case ConfigMenuItem::DEVICE_MODEL: {
                const char* modelStr = (configManager.get().model == DeviceModel::CHATON_FAT) ? "Chaton Fat" : "Mistral";
                M5.Lcd.printf("Model: > %s\n", modelStr);
                break;
            }
            case ConfigMenuItem::DEBUG_MODE: {
                const char* debugStr = configManager.get().debugMode ? "ON" : "OFF";
                M5.Lcd.printf("Debug: > %s\n", debugStr);
                break;
            }
            case ConfigMenuItem::MIC_SOURCE: {
                const char* micStr = (configManager.get().micSource == MicSource::PC) ? "PC" : "Device";
                M5.Lcd.printf("Mic: > %s\n", micStr);
                break;
            }
            case ConfigMenuItem::VOICE_OUT: {
                const char* voutStr;
                switch (configManager.get().voiceOutMode) {
                    case VoiceOutMode::OFF:     voutStr = "Off"; break;
                    case VoiceOutMode::DEVICE: voutStr = "Device"; break;
                    case VoiceOutMode::PC:     voutStr = "PC"; break;
                    default: voutStr = "Off";
                }
                M5.Lcd.printf("Voice Out: > %s\n", voutStr);
                break;
            }
            case ConfigMenuItem::DEMO_MODE: {
                const char* demoStr = configManager.get().demoMode ? "ON" : "OFF";
                M5.Lcd.printf("Demo Mode: > %s\n", demoStr);
                break;
            }
            case ConfigMenuItem::EXIT:
                M5.Lcd.setTextColor(0xF800, BLACK);  // Red
                M5.Lcd.printf("Exit\n");
                break;
            default:
                break;
        }
    }
    
    // Draw hint at bottom
    M5.Lcd.setTextSize(1);
    M5.Lcd.setTextColor(0x8888, BLACK);  // Gray
    M5.Lcd.setCursor(10, 225);
    M5.Lcd.print("A:select  B:prev  C:next  C-long:exit");
    
    needsRedraw = false;
}

ConfigMenuItem ConfigMenu::getSelectedItem() const {
    return selectedItem;
}

bool ConfigMenu::isActive() const {
    return active;
}

void ConfigMenu::open() {
    selectedItem = ConfigMenuItem::QUIET_MODE;
    active = true;
    needsRedraw = true;
}

void ConfigMenu::close() {
    active = false;
}

const DeviceConfig& ConfigMenu::getConfig() const {
    return configManager.get();
}

void ConfigMenu::moveNext() {
    int current = static_cast<int>(selectedItem);
    current = (current + 1) % static_cast<int>(ConfigMenuItem::COUNT);
    selectedItem = static_cast<ConfigMenuItem>(current);
}

void ConfigMenu::movePrevious() {
    int current = static_cast<int>(selectedItem);
    current = (current == 0) ? static_cast<int>(ConfigMenuItem::COUNT) - 1 : current - 1;
    selectedItem = static_cast<ConfigMenuItem>(current);
}

void ConfigMenu::selectItem() {
    switch (selectedItem) {
        case ConfigMenuItem::QUIET_MODE:
            toggleQuietMode();
            break;
        case ConfigMenuItem::LED_BRIGHTNESS:
            cycleBrightness(true);
            break;
        case ConfigMenuItem::DEVICE_MODEL:
            cycleModel(true);
            break;
        case ConfigMenuItem::DEBUG_MODE:
            configManager.toggleDebugMode();
            break;
        case ConfigMenuItem::MIC_SOURCE:
            configManager.toggleMicSource();
            break;
        case ConfigMenuItem::VOICE_OUT:
            cycleVoiceOutMode();
            break;
        case ConfigMenuItem::DEMO_MODE:
            toggleDemoMode();
            break;
        case ConfigMenuItem::EXIT:
            // Handled in update()
            break;
        default:
            break;
    }
}

void ConfigMenu::toggleQuietMode() {
    configManager.toggleQuietMode();
}

void ConfigMenu::cycleBrightness(bool forward) {
    configManager.cycleBrightness(forward);
}

void ConfigMenu::cycleModel(bool forward) {
    configManager.cycleModel(forward);
}

void ConfigMenu::cycleVoiceOutMode() {
    configManager.cycleVoiceOutMode();
}

void ConfigMenu::toggleDemoMode() {
    configManager.toggleDemoMode();
}
