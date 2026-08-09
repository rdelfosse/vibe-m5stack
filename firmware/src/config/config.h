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
#pragma once
#include <cstdint>

// Device model selection
enum class DeviceModel {
    MISTRAL,
    CHATON_FAT
};

// Source du micro pour le push-to-talk
enum class MicSource {
    DEVICE,   // MEMS du socle M5GO (GPIO34), audio uploadé vers le PC
    PC        // micro du PC (sounddevice côté plugin)
};

// Configuration structure
struct DeviceConfig {
    bool quietMode;           // true = silent (no vibration/beep)
    bool debugMode;           // true = le PC dump/logge les flux (audit voix)
    MicSource micSource;      // micro PTT : device (défaut) ou PC
    uint8_t ledBrightness;    // LED brightness: 16, 32, 64, 128, or 255
    DeviceModel model;        // Active model
};

class ConfigManager {
public:
    ConfigManager();
    
    // Initialize configuration (load from NVS or use defaults)
    void begin();
    
    // Get current configuration
    const DeviceConfig& get() const;
    
    // Set configuration and save to NVS
    void set(const DeviceConfig& config);
    
    // Individual setters with auto-save
    void setQuietMode(bool enabled);
    void setLedBrightness(uint8_t brightness);
    void setModel(DeviceModel model);
    
    // Cycle through brightness levels
    uint8_t cycleBrightness(bool forward = true);
    
    // Cycle through models
    DeviceModel cycleModel(bool forward = true);
    
    // Toggle quiet mode
    void toggleQuietMode();

    // Toggle debug mode (audit des flux côté PC)
    void toggleDebugMode();

    // Bascule la source micro (Device <-> PC)
    void toggleMicSource();
    
private:
    DeviceConfig currentConfig;
    bool initialized;
    
    // Load configuration from NVS
    bool load();
    
    // Save configuration to NVS
    bool save();
    
    // Apply defaults
    void applyDefaults();
};
