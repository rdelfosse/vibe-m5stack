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
