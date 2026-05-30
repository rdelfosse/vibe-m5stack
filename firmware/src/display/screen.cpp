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
#include "screen.h"
#include "mistral_logo.h"
#include "../inputs/leds.h"
#include <M5Stack.h>
// FreeSans*/FreeSansBold* fonts are pulled in transitively via M5Stack.h
// (In_eSPI.h includes them). Including them again would redefine symbols
// because the font headers have no include guards.

#define SCREEN_W 320
#define SCREEN_H 240

// Mistral Rainbow palette, sourced from the official logo SVG.
static const uint16_t RAINBOW[5] = {
    0xE920,  // Red          #E92700
    0xFA81,  // Orange Dark  #FA500F
    0xFC00,  // Orange       #FF8205
    0xFD60,  // Orange Light #FFAF00
    0xFEA0,  // Yellow       #FFD700
};
static constexpr int16_t BAND_H = SCREEN_H / 5;  // 48 px per band

ApprovalScreen::ApprovalScreen()
    : response(-1), responseRequestId(0), displayStartTime(0) {}

static void drawRainbowBackground() {
    for (int i = 0; i < 5; i++) {
        M5.Lcd.fillRect(0, i * BAND_H, SCREEN_W, BAND_H, RAINBOW[i]);
    }
}

static void drawMistralLogo(int16_t originX, int16_t originY, uint8_t scale) {
    for (int i = 0; i < MISTRAL_LOGO_RECT_COUNT; i++) {
        const MistralLogoRect& r = mistral_logo_rects[i];
        M5.Lcd.fillRect(
            originX + r.x * scale,
            originY + r.y * scale,
            r.w * scale,
            r.h * scale,
            r.color
        );
    }
}

bool ApprovalScreen::showRequest(const char* title, const char* body,
                                 uint32_t requestId, uint32_t timeoutMs) {
    response = -1;
    responseRequestId = requestId;
    displayStartTime = ::millis();

    drawRequestFrame(title, body);

    while (::millis() - displayStartTime < timeoutMs) {
        M5.update();
        led::updateApprovalAnimation();
        if (M5.BtnA.wasPressed()) { response = 1; return true; }
        if (M5.BtnB.wasPressed()) { response = 2; return true; }
        if (M5.BtnC.wasPressed()) { response = 0; return true; }
        ::delay(10);
    }
    response = 0;
    return false;
}

int ApprovalScreen::getResponse() const { return response; }
uint32_t ApprovalScreen::getResponseRequestId() const { return responseRequestId; }

void ApprovalScreen::drawRequestFrame(const char* title, const char* body) {
    // 1. Plain black background (only the idle screen uses rainbow).
    M5.Lcd.fillScreen(BLACK);

    // 2. Mistral "M" logo, centered horizontally near top.
    //    scale=1 => 28x22 px (height capped under 30 as requested).
    constexpr uint8_t LOGO_SCALE = 1;
    constexpr int16_t logoW = MISTRAL_LOGO_SVG_W * LOGO_SCALE;
    drawMistralLogo((SCREEN_W - logoW) / 2, 6, LOGO_SCALE);

    // 3. Title — FreeSans 9pt, white, centered horizontally.
    M5.Lcd.setFreeFont(&FreeSans9pt7b);
    M5.Lcd.setTextColor(WHITE, BLACK);
    M5.Lcd.setTextDatum(TC_DATUM);
    M5.Lcd.drawString(title, SCREEN_W / 2, 44);

    // 4. Body — built-in font 2 (8x16 bitmap), light grey, top-left from x=10.
    //    setCursor + print avoids datum-baseline cropping issues.
    M5.Lcd.setTextDatum(TL_DATUM);
    M5.Lcd.setTextFont(2);
    M5.Lcd.setTextSize(1);
    M5.Lcd.setTextColor(0xC618, BLACK);  // light grey
    M5.Lcd.setCursor(10, 80);
    M5.Lcd.print(body);

    // 5. Button labels at the very bottom, built-in font 2 too, color-coded.
    constexpr int16_t BTN_Y = 218;
    M5.Lcd.setTextFont(2);
    M5.Lcd.setTextSize(1);

    M5.Lcd.setTextColor(0x07E0, BLACK);   // green
    M5.Lcd.setCursor(10, BTN_Y);
    M5.Lcd.print("A APPROVE");

    M5.Lcd.setTextColor(0xF800, BLACK);   // red
    M5.Lcd.setCursor(125, BTN_Y);
    M5.Lcd.print("B REJECT");

    M5.Lcd.setTextColor(0xFFE0, BLACK);   // yellow
    M5.Lcd.setCursor(235, BTN_Y);
    M5.Lcd.print("C CANCEL");
}
