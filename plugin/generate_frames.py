#!/usr/bin/env python3
"""
Mistral GIF to C++ Frame Converter

This script:
1. Downloads the Mistral chat GIF (896x896)
2. Resizes it to 240x240 (for M5Stack screen)
3. Extracts each frame
4. Converts to RGB565 format
5. Generates C++ header file with frame data

Usage:
    python generate_frames.py

Requirements:
    pip install pillow requests
"""

import os
import sys
import requests
from PIL import Image, GifImagePlugin
import numpy as np

# Configuration
GIF_URL = "https://cms.mistral.ai/assets/920e56ee-25c5-439d-bd31-fbdf5c92c87f"
TARGET_WIDTH = 240
TARGET_HEIGHT = 240
OUTPUT_DIR = "../firmware/src/display"
OUTPUT_FILE = "mistral_gif_frames.h"

# Mistral brand colors (RGB565)
COLOR_BG = 0x0000      # Black
COLOR_VIOLET = 0x9075  # #920E56
COLOR_ORANGE = 0xF48F  # #F7931E
COLOR_WHITE = 0xFFFF   # White

# Palette for quantization (if GIF has many colors)
MISTRAL_PALETTE = [
    (0, 0, 0),        # Black
    (146, 14, 86),   # Violet #920E56
    (247, 147, 30),  # Orange #F7931E
    (255, 255, 255)  # White
]

def rgb_to_rgb565(r, g, b):
    """Convert RGB888 to RGB565"""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

def closest_color(rgb, palette):
    """Find closest color in palette"""
    r, g, b = rgb
    min_dist = float('inf')
    best_idx = 0
    for i, (pr, pg, pb) in enumerate(palette):
        dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if dist < min_dist:
            min_dist = dist
            best_idx = i
    return best_idx

def download_gif(url):
    """Download GIF from URL"""
    print(f"Downloading GIF from {url}...")
    response = requests.get(url)
    response.raise_for_status()
    
    # Save temporarily
    temp_file = "mistral_chat_temp.gif"
    with open(temp_file, 'wb') as f:
        f.write(response.content)
    
    print(f"✓ GIF downloaded: {temp_file}")
    return temp_file

def process_gif(gif_path):
    """Process GIF and extract frames"""
    print(f"Opening GIF: {gif_path}")
    gif = Image.open(gif_path)
    
    frames = []
    try:
        while True:
            # Convert to RGBA if needed
            frame = gif.convert('RGBA')
            frames.append(frame)
            gif.seek(gif.tell() + 1)
    except EOFError:
        pass
    
    print(f"✓ Extracted {len(frames)} frames from GIF")
    
    # Resize all frames to target size
    resized_frames = []
    for i, frame in enumerate(frames):
        resized = frame.resize((TARGET_WIDTH, TARGET_HEIGHT), Image.LANCZOS)
        resized_frames.append(resized)
        print(f"  Frame {i}: {frame.size} -> {resized.size}")
    
    return resized_frames

def frame_to_c_array(frame):
    """Convert a frame to C array of RGB565 values"""
    # Convert to RGB if RGBA
    if frame.mode == 'RGBA':
        # Create white background
        background = Image.new('RGB', frame.size, (0, 0, 0))
        background.paste(frame, mask=frame.split()[3])  # Use alpha channel
        frame = background
    
    # Quantize to Mistral palette (optional, reduces colors)
    # For now, convert each pixel to RGB565 directly
    pixels = list(frame.getdata())
    
    c_array = []
    for i, rgb in enumerate(pixels):
        if len(rgb) == 4:  # RGBA
            r, g, b, a = rgb
            if a < 128:  # Transparent
                c_array.append(COLOR_BG)
            else:
                c_array.append(rgb_to_rgb565(r, g, b))
        else:  # RGB
            r, g, b = rgb
            c_array.append(rgb_to_rgb565(r, g, b))
    
    return c_array

def generate_c_header(frames):
    """Generate C++ header file with frame data"""
    
    # Header content
    header = f"""#pragma once
#include <stdint.h>

// Mistral brand colors (RGB565)
#define MISTRAL_BG     0x0000  // Black
#define MISTRAL_VIOLET 0x9075  // #920E56
#define MISTRAL_ORANGE 0xF48F  // #F7931E
#define MISTRAL_WHITE  0xFFFF  // White

// Frame dimensions
#define GIF_WIDTH   {TARGET_WIDTH}
#define GIF_HEIGHT  {TARGET_HEIGHT}
#define NUM_FRAMES  {len(frames)}

// Total pixels per frame
#define FRAME_SIZE  (GIF_WIDTH * GIF_HEIGHT)

"""
    
    # Frame data arrays
    for i, frame in enumerate(frames):
        pixels = frame_to_c_array(frame)
        
        # Convert to C array
        header += f"// Frame {i} (Original GIF frame {i+1})\n"
        header += f"static const uint16_t frame_{i}_data[FRAME_SIZE] PROGMEM = {{\n"
        
        # 16 values per line for readability
        for j, pixel in enumerate(pixels):
            if j % 16 == 0:
                header += "    "
            header += f"0x{pixel:04X}, "
            if j % 16 == 15:
                header += "\n"
        
        header += "};\n\n"
    
    # Draw function
    header += """
// Draw a frame at position (x, y)
static inline void drawFrame(uint8_t frameIdx, int16_t x, int16_t y) {
    const uint16_t* frame = NULL;
    switch (frameIdx) {
"""
    
    for i in range(len(frames)):
        header += f"        case {i}: frame = frame_{i}_data; break;\n"
    
    header += """
        default: return;
    }
    
    for (int py = 0; py < GIF_HEIGHT; py++) {
        for (int px = 0; px < GIF_WIDTH; px++) {
            uint16_t color = pgm_read_word(&frame[py * GIF_WIDTH + px]);
            if (color != MISTRAL_BG) {
                M5.Lcd.drawPixel(x + px, y + py, color);
            }
        }
    }
}

// Draw frame centered on screen
static inline void drawFrameCentered(uint8_t frameIdx) {
    int16_t x = (320 - GIF_WIDTH) / 2;
    int16_t y = (240 - GIF_HEIGHT) / 2;
    drawFrame(frameIdx, x, y);
}

// Animation controller
class MistralGifAnimator {
public:
    MistralGifAnimator() : currentFrame(0), lastFrameTime(0) {}
    
    void update() {
        uint32_t now = millis();
        // Assuming ~200ms per frame (adjust based on original GIF)
        if (now - lastFrameTime > 200) {
            lastFrameTime = now;
            currentFrame = (currentFrame + 1) % NUM_FRAMES;
        }
    }
    
    void draw() {
        drawFrameCentered(currentFrame);
    }
    
    void reset() {
        currentFrame = 0;
        lastFrameTime = 0;
    }
    
private:
    uint8_t currentFrame;
    uint32_t lastFrameTime;
};
"""
    
    return header

def main():
    print("=" * 60)
    print("Mistral GIF to C++ Converter")
    print("=" * 60)
    
    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Download GIF
    gif_path = download_gif(GIF_URL)
    
    # Process GIF
    frames = process_gif(gif_path)
    
    # Generate C header
    header_code = generate_c_header(frames)
    
    # Write output
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    with open(output_path, 'w') as f:
        f.write(header_code)
    
    print(f"\n✓ Generated: {output_path}")
    print(f"  {len(frames)} frames, {TARGET_WIDTH}x{TARGET_HEIGHT}px")
    print(f"  File size: {os.path.getsize(output_path)} bytes")
    
    # Cleanup temp file
    if os.path.exists(gif_path):
        os.remove(gif_path)
        print(f"  Cleaned up: {gif_path}")
    
    print("\n" + "=" * 60)
    print("Done! Copy the generated header to your firmware project.")
    print("=" * 60)

if __name__ == "__main__":
    main()
