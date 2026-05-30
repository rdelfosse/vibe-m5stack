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
#include <M5Stack.h>

// Lightweight IMU helper for shake detection.
// `pollShake()` returns true ONCE per shake event (with cooldown) and is
// stateless between calls — no internal `wasShaking` flag to forget to reset.
class IMUManager {
public:
    void begin();
    bool pollShake();

private:
    uint32_t lastShakeMs = 0;
    static constexpr uint32_t SHAKE_COOLDOWN_MS = 1500;
    static constexpr float    SHAKE_THRESHOLD_G = 3.5f;
};

extern IMUManager imuManager;
