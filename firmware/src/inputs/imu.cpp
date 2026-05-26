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
