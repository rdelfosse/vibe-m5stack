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

#include "chaton_fat_draw.h"
#include <M5Stack.h>

// Dessine un bitmap 1-bit (MSB-first) agrandi scale x, couleur `color`,
// uniquement pour les bits a 1.
static void blit1bit(const uint8_t* bmp, int16_t x0, int16_t y0,
                     uint8_t scale, uint16_t color) {
    for (int ly = 0; ly < CHATON_FAT_H; ly++) {
        for (int lx = 0; lx < CHATON_FAT_W; lx++) {
            uint8_t b = bmp[ly * CHATON_FAT_STRIDE + (lx >> 3)];
            if ((b >> (7 - (lx & 7))) & 1) {
                M5.Lcd.fillRect(x0 + lx * scale, y0 + ly * scale, scale, scale, color);
            }
        }
    }
}

void drawChatonFat(int16_t x0, int16_t y0, uint8_t scale, uint16_t outline, uint16_t body) {
    // 1) corps plein en blanc, 2) contour noir par-dessus.
    blit1bit(CHATON_FAT_FILL_BITMAP, x0, y0, scale, body);
    blit1bit(CHATON_FAT_BITMAP,      x0, y0, scale, outline);
}
