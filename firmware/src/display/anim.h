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
