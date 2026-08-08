// Vibe M5Stack - Chaton Fat easter egg rendering
// Copyright 2026
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
#include "chaton_fat.h"

// Draw the Chaton Fat: filled body first, then outline on top, scaled.
// x0, y0: top-left corner in pixels
// scale : pixel multiplier (4 = 208x172)
// outline: outline color (e.g. BLACK)
// body  : body fill color (e.g. WHITE)
void drawChatonFat(int16_t x0, int16_t y0, uint8_t scale, uint16_t outline, uint16_t body);
