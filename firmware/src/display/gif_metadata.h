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
