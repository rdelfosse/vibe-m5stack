// Vibe M5Stack - Configuration Manager
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
#include "config.h"
#include <Preferences.h>

// Valid brightness levels (stable cycle, includes 255)
static const uint8_t BRIGHTNESS_LEVELS[] = {16, 32, 64, 128, 255};
static const size_t BRIGHTNESS_COUNT = sizeof(BRIGHTNESS_LEVELS) / sizeof(BRIGHTNESS_LEVELS[0]);

// NVS namespace and keys
static const char* NVS_NAMESPACE = "vibe-config";
static const char* NVS_KEY_MAGIC = "magic";
static const char* NVS_KEY_QUIET = "quiet";
static const char* NVS_KEY_BRIGHT = "bright";
static const char* NVS_KEY_MODEL = "model";
static const char* NVS_KEY_DEMO = "demo";
static const char* NVS_KEY_DEBUG = "debug";
static const char* NVS_KEY_MIC = "mic";
static const char* NVS_KEY_VOUT = "vout";
static const char* NVS_KEY_VLANG = "vlang";

// Magic byte value to detect valid configuration
static const uint8_t CONFIG_MAGIC = 0x42;

ConfigManager::ConfigManager() : initialized(false) {
    applyDefaults();
}

void ConfigManager::begin() {
    if (!load()) {
        // Configuration not valid or not found, use defaults
        applyDefaults();
        save();
    }
    initialized = true;
}

const DeviceConfig& ConfigManager::get() const {
    return currentConfig;
}

void ConfigManager::set(const DeviceConfig& config) {
    currentConfig = config;
    if (initialized) {
        save();
    }
}

void ConfigManager::setQuietMode(bool enabled) {
    currentConfig.quietMode = enabled;
    if (initialized) {
        save();
    }
}

void ConfigManager::setLedBrightness(uint8_t brightness) {
    // Find the closest valid brightness level
    uint8_t closest = 32;
    uint8_t minDiff = 255;
    for (size_t i = 0; i < BRIGHTNESS_COUNT; i++) {
        uint8_t diff = abs((int)brightness - (int)BRIGHTNESS_LEVELS[i]);
        if (diff < minDiff) {
            minDiff = diff;
            closest = BRIGHTNESS_LEVELS[i];
        }
    }
    currentConfig.ledBrightness = closest;
    if (initialized) {
        save();
    }
}

void ConfigManager::setModel(DeviceModel model) {
    currentConfig.model = model;
    if (initialized) {
        save();
    }
}
void ConfigManager::setDemoMode(bool enabled) {
    currentConfig.demoMode = enabled;
    if (initialized) {
        save();
    }
}

uint8_t ConfigManager::cycleBrightness(bool forward) {
    // Find current index
    size_t currentIndex = 0;
    for (size_t i = 0; i < BRIGHTNESS_COUNT; i++) {
        if (BRIGHTNESS_LEVELS[i] == currentConfig.ledBrightness) {
            currentIndex = i;
            break;
        }
    }
    
    // Cycle through levels
    if (forward) {
        currentIndex = (currentIndex + 1) % BRIGHTNESS_COUNT;
    } else {
        currentIndex = (currentIndex == 0) ? BRIGHTNESS_COUNT - 1 : currentIndex - 1;
    }
    
    currentConfig.ledBrightness = BRIGHTNESS_LEVELS[currentIndex];
    if (initialized) {
        save();
    }
    return currentConfig.ledBrightness;
}

DeviceModel ConfigManager::cycleModel(bool forward) {
    int current = static_cast<int>(currentConfig.model);
    int max = static_cast<int>(DeviceModel::CHATON_FAT);
    
    if (forward) {
        current = (current + 1) % (max + 1);
    } else {
        current = (current == 0) ? max : current - 1;
    }
    
    currentConfig.model = static_cast<DeviceModel>(current);
    if (initialized) {
        save();
    }
    return currentConfig.model;
}

void ConfigManager::toggleQuietMode() {
    currentConfig.quietMode = !currentConfig.quietMode;
    if (initialized) {
        save();
    }
}

void ConfigManager::toggleDebugMode() {
    currentConfig.debugMode = !currentConfig.debugMode;
    if (initialized) {
        save();
    }
}

void ConfigManager::toggleMicSource() {
    currentConfig.micSource = (currentConfig.micSource == MicSource::DEVICE)
        ? MicSource::PC : MicSource::DEVICE;
    if (initialized) {
        save();
    }
}
void ConfigManager::toggleDemoMode() {
    currentConfig.demoMode = !currentConfig.demoMode;
    if (initialized) {
        save();
    }
}

void ConfigManager::setVoiceOutMode(VoiceOutMode mode) {
    currentConfig.voiceOutMode = mode;
    if (initialized) {
        save();
    }
}

VoiceOutMode ConfigManager::cycleVoiceOutMode(bool forward) {
    int current = static_cast<int>(currentConfig.voiceOutMode);
    int max = static_cast<int>(VoiceOutMode::PC);
    
    if (forward) {
        current = (current + 1) % (max + 1);
    } else {
        current = (current == 0) ? max : current - 1;
    }
    
    currentConfig.voiceOutMode = static_cast<VoiceOutMode>(current);
    if (initialized) {
        save();
    }
    return currentConfig.voiceOutMode;
}

VoiceOutMode ConfigManager::getVoiceOutMode() const {
    return currentConfig.voiceOutMode;
}

VoiceLang ConfigManager::cycleVoiceLang() {
    currentConfig.voiceLang = (currentConfig.voiceLang == VoiceLang::FR)
        ? VoiceLang::EN : VoiceLang::FR;
    if (initialized) {
        save();
    }
    return currentConfig.voiceLang;
}

bool ConfigManager::load() {
    Preferences preferences;
    
    if (!preferences.begin(NVS_NAMESPACE, true)) {
        return false;
    }
    
    // Check magic byte
    uint8_t magic = preferences.getUChar(NVS_KEY_MAGIC, 0);
    if (magic != CONFIG_MAGIC) {
        preferences.end();
        return false;
    }
    
    // Load configuration
    currentConfig.quietMode = preferences.getBool(NVS_KEY_QUIET, false);
    currentConfig.debugMode = preferences.getBool(NVS_KEY_DEBUG, false);
    uint8_t micValue = preferences.getUChar(NVS_KEY_MIC, 0);
    currentConfig.micSource = (micValue == 1) ? MicSource::PC : MicSource::DEVICE;
    uint8_t voutValue = preferences.getUChar(NVS_KEY_VOUT, 0);
    currentConfig.voiceOutMode = static_cast<VoiceOutMode>(voutValue);
    uint8_t vlangValue = preferences.getUChar(NVS_KEY_VLANG, 0);
    currentConfig.voiceLang = (vlangValue == 1) ? VoiceLang::EN : VoiceLang::FR;
    
    uint8_t brightness = preferences.getUChar(NVS_KEY_BRIGHT, 32);
    // Validate brightness is in our list
    bool validBrightness = false;
    for (size_t i = 0; i < BRIGHTNESS_COUNT; i++) {
        if (BRIGHTNESS_LEVELS[i] == brightness) {
            validBrightness = true;
            break;
        }
    }
    currentConfig.ledBrightness = validBrightness ? brightness : 32;
    
    uint8_t modelValue = preferences.getUChar(NVS_KEY_MODEL, 0);
    currentConfig.model = (modelValue <= static_cast<uint8_t>(DeviceModel::CHATON_FAT)) 
        ? static_cast<DeviceModel>(modelValue) 
        : DeviceModel::MISTRAL;
    currentConfig.demoMode = preferences.getBool(NVS_KEY_DEMO, false);
    
    preferences.end();
    return true;
}

bool ConfigManager::save() {
    Preferences preferences;
    
    if (!preferences.begin(NVS_NAMESPACE, false)) {
        return false;
    }
    
    // Save magic byte
    preferences.putUChar(NVS_KEY_MAGIC, CONFIG_MAGIC);
    
    // Save configuration
    preferences.putBool(NVS_KEY_QUIET, currentConfig.quietMode);
    preferences.putBool(NVS_KEY_DEBUG, currentConfig.debugMode);
    preferences.putUChar(NVS_KEY_MIC, currentConfig.micSource == MicSource::PC ? 1 : 0);
    preferences.putUChar(NVS_KEY_VOUT, static_cast<uint8_t>(currentConfig.voiceOutMode));
    preferences.putUChar(NVS_KEY_VLANG, currentConfig.voiceLang == VoiceLang::EN ? 1 : 0);
    preferences.putUChar(NVS_KEY_BRIGHT, currentConfig.ledBrightness);
    preferences.putUChar(NVS_KEY_MODEL, static_cast<uint8_t>(currentConfig.model));
    preferences.putBool(NVS_KEY_DEMO, currentConfig.demoMode);
    
    preferences.end();
    return true;
}

void ConfigManager::applyDefaults() {
    currentConfig.quietMode = false;
    currentConfig.debugMode = false;   // debug OFF par défaut (logs sobres)
    currentConfig.micSource = MicSource::DEVICE;  // micro embarqué par défaut
    currentConfig.voiceOutMode = VoiceOutMode::OFF; // TTS OFF par défaut
    currentConfig.voiceLang = VoiceLang::FR;        // voix française par défaut
    currentConfig.ledBrightness = 32;
    currentConfig.demoMode = false;
    currentConfig.model = DeviceModel::MISTRAL;
}
