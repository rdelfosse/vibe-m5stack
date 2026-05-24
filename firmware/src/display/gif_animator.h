#pragma once
#include <M5Stack.h>

// Mistral brand colors (RGB565)
#define MISTRAL_BG     0x0000  // Black
#define MISTRAL_VIOLET 0x9075  // #920E56
#define MISTRAL_ORANGE 0xF48F  // #F7931E
#define MISTRAL_WHITE  0xFFFF  // White

// Forward declarations (defined in gif_frames.h)
extern const uint16_t* const all_frames[];
extern const uint16_t NUM_FRAMES;
extern const uint16_t GIF_WIDTH;
extern const uint16_t GIF_HEIGHT;
extern const uint16_t FRAME_SIZE;

class GifAnimator {
public:
    GifAnimator();
    
    void begin();
    void draw();
    void update();
    void reset();
    
    // For approval screen (draw static frame without animation)
    void drawStatic(uint8_t frameIdx = 0);
    
    // Set credit percentage (0-100) and validity
    void setCreditInfo(uint8_t percent, bool valid);
    
    bool isReady() const { return spriteCreated; }

    uint32_t psramFree() const { return lastPsramFree; }
    uint32_t dramFree()  const { return lastDramFree; }
    uint32_t bytesNeeded() const { return lastBytesNeeded; }

private:
    void drawCreditGauge() const;
    
    uint8_t currentFrame;
    uint32_t lastFrameTime;
    uint8_t totalFrames;
    bool spriteCreated;
    uint32_t lastPsramFree;
    uint32_t lastDramFree;
    uint32_t lastBytesNeeded;
    uint8_t creditPercent;
    bool creditInfoValid;
};
