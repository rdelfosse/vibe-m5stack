#pragma once
#include <stdint.h>

// Compile-time GIF dimensions, safe to include anywhere (no pixel data).
constexpr uint16_t GIF_WIDTH  = 240;
constexpr uint16_t GIF_HEIGHT = 240;
constexpr uint16_t NUM_FRAMES = 27;
constexpr uint32_t FRAME_SIZE = static_cast<uint32_t>(GIF_WIDTH) * GIF_HEIGHT;

// Defined in gif_frames.h, which is included only by gif_animator.cpp
// (3 MB of PROGMEM pixel data — including it from multiple TUs would
// duplicate that into the firmware binary).
extern const uint16_t* const all_frames[NUM_FRAMES];
