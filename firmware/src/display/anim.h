#pragma once
#include "gif_animator.h"

// Wrapper for backward compatibility
class ChatAnimator {
public:
    ChatAnimator() = default;
    
    void begin() {
        animator.begin();
    }
    
    void draw() {
        animator.draw();
    }
    
    void update() {
        animator.update();
    }
    
    void reset() {
        animator.reset();
    }
    
    void setCreditInfo(uint8_t percent, bool valid) {
        animator.setCreditInfo(percent, valid);
    }

    bool isReady() const {
        return animator.isReady();
    }

    uint32_t psramFree()   const { return animator.psramFree(); }
    uint32_t dramFree()    const { return animator.dramFree(); }
    uint32_t bytesNeeded() const { return animator.bytesNeeded(); }

private:
    GifAnimator animator;
};
