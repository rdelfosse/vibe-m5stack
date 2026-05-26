#pragma once
#include <stdint.h>

// Lightweight shake-state timer. Owns no graphics — just decides when to wobble
// the cat's draw position. The actual offset is applied to GifAnimator via
// `setOffset()` from main.cpp.
class ShakeAnimation {
public:
    void trigger();
    bool isActive() const { return active; }

    // Call every loop tick while active. Returns true the single tick the
    // animation just finished, so the caller can clear the offset.
    bool tick();

    // Random small offset (-MAX_OFFSET..MAX_OFFSET) on each call. Re-roll every
    // frame to get the jittery shake look.
    void rollOffset(int8_t& dx, int8_t& dy) const;

private:
    bool     active = false;
    uint32_t startMs = 0;

    static constexpr uint32_t DURATION_MS = 800;
    static constexpr int8_t   MAX_OFFSET  = 8;
};

extern ShakeAnimation shakeAnimation;
