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
#include "imu.h"
#include <math.h>

IMUManager imuManager;

void IMUManager::begin() {
    // M5.begin() already initialized the MPU6886 — nothing to do here.
}

bool IMUManager::pollShake() {
    float ax, ay, az;
    M5.Imu.getAccelData(&ax, &ay, &az);  // values returned in g

    const float magnitude = sqrtf(ax * ax + ay * ay + az * az);
    const uint32_t now = millis();

    if (magnitude > SHAKE_THRESHOLD_G && (now - lastShakeMs) > SHAKE_COOLDOWN_MS) {
        lastShakeMs = now;
        return true;
    }
    return false;
}
