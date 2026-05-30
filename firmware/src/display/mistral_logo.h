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
#include <cstdint>

// Mistral "M" logo, transcribed from official SVG (viewBox 28x28, 10 rects).
// Coordinates expressed in SVG units (1 unit = 3.457 px on the original asset).
// drawMistralLogo() multiplies by `scale` and offsets by (originX, originY).

struct MistralLogoRect {
    uint8_t x, y, w, h;   // in SVG units, rounded
    uint16_t color;       // RGB565
};

// RGB565 of the 5 official Mistral palette colors used in the logo:
// red=#E92700 (0xE920), orange-dark=#FA500F (0xFA81),
// orange=#FF8205 (0xFC00), orange-light=#FFAF00 (0xFD60),
// yellow=#FFD700 (0xFEA0).
static constexpr MistralLogoRect mistral_logo_rects[10] = {
    //  x  y  w   h  color
    {   5,  5,  3, 3, 0xFEA0 },  // yellow top-left
    {  19,  5,  3, 3, 0xFEA0 },  // yellow top-right
    {   5,  9,  7, 3, 0xFD60 },  // orange-light bar left
    {  16,  9,  7, 3, 0xFD60 },  // orange-light bar right
    {   5, 12, 17, 3, 0xFC00 },  // orange wide middle
    {   5, 16,  3, 3, 0xFA81 },  // orange-dark left
    {  12, 16,  3, 3, 0xFA81 },  // orange-dark center
    {  19, 16,  3, 3, 0xFA81 },  // orange-dark right
    {   2, 19, 10, 3, 0xE920 },  // red bottom-left
    {  16, 19, 10, 3, 0xE920 },  // red bottom-right
};

constexpr int MISTRAL_LOGO_SVG_W = 28;
constexpr int MISTRAL_LOGO_SVG_H = 28;
constexpr int MISTRAL_LOGO_RECT_COUNT = 10;
