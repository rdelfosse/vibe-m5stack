#include "gif_animator.h"
#include "gif_frames.h"  // Contient TOUTES les frames + all_frames[]
#include <esp_heap_caps.h>

GifAnimator::GifAnimator() :
    currentFrame(0), lastFrameTime(0), totalFrames(NUM_FRAMES), spriteCreated(false),
    lastPsramFree(0), lastDramFree(0), lastBytesNeeded(0),
    creditPercent(0), creditInfoValid(false) {
}

void GifAnimator::begin() {
    // Frame pixels are stored as big-endian RGB565 (high byte first),
    // ESP32 is little-endian, so tell TFT_eSPI to swap bytes during SPI write.
    M5.Lcd.setSwapBytes(true);

    lastPsramFree = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    lastDramFree  = heap_caps_get_free_size(MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL);
    lastBytesNeeded = 0;
    spriteCreated = true;
}

void GifAnimator::draw() {
    update();

    // Mistral Rainbow palette (must match reset()).
    static const uint16_t bands[5] = { 0xE020, 0xFA81, 0xFC00, 0xFD60, 0xFEC0 };
    constexpr int16_t bandH  = 240 / 5;                // 48
    constexpr int16_t centerX = (320 - GIF_WIDTH) / 2; // 40

    // 240*48 = 11520 px = 23 KB. Static => .bss, zero runtime alloc.
    static uint16_t bandBuf[GIF_WIDTH * bandH];

    const uint16_t* frame = all_frames[currentFrame % totalFrames];

    // Last band is shortened from 48 → 28 px so the bottom y=220..240 strip
    // stays untouched and the credit gauge drawn there isn't erased every frame.
    constexpr int16_t lastBandH = 28;

    for (int b = 0; b < 5; b++) {
        const uint16_t color = bands[b];
        const uint16_t* src  = frame + b * bandH * GIF_WIDTH;
        const int16_t  h     = (b == 4) ? lastBandH : bandH;
        for (int i = 0; i < GIF_WIDTH * h; i++) {
            uint16_t px = src[i];
            bandBuf[i] = (px == MISTRAL_BG) ? color : px;
        }
        M5.Lcd.pushImage(centerX, b * bandH, GIF_WIDTH, h, bandBuf);
    }
    // No drawCreditGauge() here: it's painted once in reset() and only re-painted
    // by setCreditInfo() when the value actually changes.
}

void GifAnimator::drawStatic(uint8_t frameIdx) {
    const uint16_t* frame = all_frames[frameIdx % totalFrames];
    M5.Lcd.pushImage((320 - GIF_WIDTH) / 2, (240 - GIF_HEIGHT) / 2,
                     GIF_WIDTH, GIF_HEIGHT, (uint16_t*)frame, MISTRAL_BG);
}

void GifAnimator::update() {
    if (!spriteCreated) return;
    
    uint32_t now = ::millis();
    // Original GIF speed: 100ms per frame for smooth animation
    if (now - lastFrameTime > 100) {
        lastFrameTime = now;
        currentFrame = (currentFrame + 1) % totalFrames;
    }
}

void GifAnimator::reset() {
    currentFrame = 0;
    lastFrameTime = 0;

    // Mistral Rainbow background: 5 horizontal bands of 48px
    static const uint16_t bands[5] = {
        0xE020,  // Red          225/5/0
        0xFA81,  // Orange Dark  250/80/15
        0xFC00,  // Orange       255/130/5
        0xFD60,  // Orange Light 255/175/0
        0xFEC0,  // Yellow       255/216/0
    };
    constexpr int16_t bandH = 240 / 5;
    for (int i = 0; i < 5; i++) {
        M5.Lcd.fillRect(0, i * bandH, 320, bandH, bands[i]);
    }
}

void GifAnimator::setCreditInfo(uint8_t percent, bool valid) {
    creditPercent = percent;
    creditInfoValid = valid;
}

void GifAnimator::drawCreditGauge() const {
    if (!creditInfoValid) {
        // Draw "N/A" in the gauge area
        M5.Lcd.setTextFont(2);
        M5.Lcd.setTextSize(1);
        M5.Lcd.setTextColor(0xC618, BLACK);  // Light grey
        M5.Lcd.setCursor(10, 222);
        M5.Lcd.print("Credit: N/A");
        return;
    }

    // Gauge area: bottom of screen (y=220 to 240)
    constexpr int16_t gaugeY = 220;
    constexpr int16_t gaugeH = 20;
    constexpr int16_t gaugeW = 200;
    constexpr int16_t gaugeX = (320 - gaugeW) / 2;
    
    // Draw "Vibe" logo/text on the left
    M5.Lcd.setTextFont(2);
    M5.Lcd.setTextSize(1);
    M5.Lcd.setTextColor(MISTRAL_WHITE, BLACK);
    M5.Lcd.setCursor(10, gaugeY + 2);
    M5.Lcd.print("Vibe");
    
    // Draw credit label
    M5.Lcd.setCursor(55, gaugeY + 2);
    M5.Lcd.print("Credit:");
    
    // Calculate bar width based on percentage
    int16_t barW = (creditPercent * gaugeW) / 100;
    
    // Choose color based on percentage
    uint16_t barColor;
    if (creditPercent <= 70) {
        barColor = 0x07E0;  // Green
    } else if (creditPercent <= 90) {
        barColor = 0xFFA0;  // Orange/Yellow
    } else {
        barColor = 0xF800;  // Red
    }
    
    // Draw background (dark grey)
    M5.Lcd.fillRect(gaugeX, gaugeY, gaugeW, gaugeH, 0x4208);
    
    // Draw filled bar
    if (barW > 0) {
        M5.Lcd.fillRect(gaugeX, gaugeY, barW, gaugeH, barColor);
    }
    
    // Draw percentage text
    char percentStr[8];
    snprintf(percentStr, sizeof(percentStr), "%d%%", creditPercent);
    M5.Lcd.setTextColor(MISTRAL_WHITE, 0x4208);
    M5.Lcd.setCursor(gaugeX + gaugeW + 5, gaugeY + 2);
    M5.Lcd.print(percentStr);
}
