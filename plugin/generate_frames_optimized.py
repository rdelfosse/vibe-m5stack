#!/usr/bin/env python3
"""
Vibe M5Stack - M5Stack integration for Mistral Vibe CLI
Copyright 2026 Romain Delfosse

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
""""""
Mistral GIF to C++ Frame Converter - OPTIMIZED VERSION

This script:
1. Downloads the Mistral chat GIF (896x896)
2. Resizes it to 240x240 (for M5Stack screen)
3. Extracts each frame
4. Converts to RGB565 format
5. Generates C++ header file using draw16bitBeRGBBitmap for MAX SPEED

Usage:
    python generate_frames_optimized.py

Requirements:
    pip install pillow requests
"""

import os
import sys
import requests
from PIL import Image

# Configuration
GIF_URL = "https://cms.mistral.ai/assets/920e56ee-25c5-439d-bd31-fbdf5c92c87f"
TARGET_WIDTH = 240
TARGET_HEIGHT = 240
OUTPUT_DIR = "../firmware/src/display"
OUTPUT_FILE = "mistral_gif_frames.h"

def rgb_to_rgb565(r, g, b):
    """Convert RGB888 to RGB565 (BIG ENDIAN for draw16bitBeRGBBitmap)"""
    # draw16bitBeRGBBitmap expects BIG ENDIAN RGB565
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

def download_gif(url):
    """Download GIF from URL"""
    print(f"Downloading GIF from {url}...")
    response = requests.get(url)
    response.raise_for_status()
    
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
    """Convert a frame to C array of RGB565 values (BIG ENDIAN)"""
    if frame.mode == 'RGBA':
        background = Image.new('RGB', frame.size, (0, 0, 0))
        background.paste(frame, mask=frame.split()[3])
        frame = background
    
    pixels = list(frame.getdata())
    
    # Convert to RGB565 BIG ENDIAN (for draw16bitBeRGBBitmap)
    c_array = []
    for rgb in pixels:
        if len(rgb) == 4:
            r, g, b, a = rgb
            if a < 128:
                c_array.append(0x0000)  # Transparent = Black
            else:
                c_array.append(rgb_to_rgb565(r, g, b))
        else:
            r, g, b = rgb
            c_array.append(rgb_to_rgb565(r, g, b))
    
    return c_array

def generate_c_header(frames):
    """Generate C++ header with OPTIMIZED draw16bitBeRGBBitmap"""
    
    header = f"""#pragma once
#include <stdint.h>
#include <pgmspace.h>
#include <M5Stack.h>

// Frame dimensions
#define GIF_WIDTH   {TARGET_WIDTH}
#define GIF_HEIGHT  {TARGET_HEIGHT}
#define NUM_FRAMES  {len(frames)}

// Total pixels per frame
#define FRAME_SIZE  (GIF_WIDTH * GIF_HEIGHT)

"""
    
    # Frame data arrays (BIG ENDIAN RGB565 for draw16bitBeRGBBitmap)
    for i, frame in enumerate(frames):
        pixels = frame_to_c_array(frame)
        
        header += f"// Frame {i} (RGB565 BIG ENDIAN for draw16bitBeRGBBitmap)\n"
        header += f"static const uint16_t frame_{i}_data[FRAME_SIZE] PROGMEM = {{\n"
        
        for j, pixel in enumerate(pixels):
            if j % 16 == 0:
                header += "    "
            header += f"0x{pixel:04X}, "
            if j % 16 == 15:
                header += "\n"
        
        header += "};\n\n"
    
    # OPTIMIZED draw function using draw16bitBeRGBBitmap
    header += """
// OPTIMIZED: Use draw16bitBeRGBBitmap for MAX SPEED (no flicker!)
static inline void drawFrame(uint8_t frameIdx, int16_t x, int16_t y) {
    const uint16_t* frame = NULL;
    switch (frameIdx) {
"""
    
    for i in range(len(frames)):
        header += f"        case {i}: frame = frame_{i}_data; break;\n"
    
    header += """
        default: return;
    }
    
    // Use draw16bitBeRGBBitmap - MUCH FASTER than drawPixel!
    M5.Lcd.draw16bitBeRGBBitmap(x, y, (uint16_t*)frame, GIF_WIDTH, GIF_HEIGHT);
}

// Draw frame centered on screen
static inline void drawFrameCentered(uint8_t frameIdx) {
    int16_t x = (320 - GIF_WIDTH) / 2;
    int16_t y = (240 - GIF_HEIGHT) / 2;
    drawFrame(frameIdx, x, y);
}

// High-speed animation controller
class MistralGifAnimator {
public:
    MistralGifAnimator() : currentFrame(0), lastFrameTime(0) {}
    
    void update() {
        uint32_t now = millis();
        // ~200ms per frame (adjust to match original GIF speed)
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
    print("Mistral GIF to C++ Converter - OPTIMIZED")
    print("=" * 60)
    
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
    
    print(f"\n✓ Generated OPTIMIZED: {output_path}")
    print(f"  {len(frames)} frames, {TARGET_WIDTH}x{TARGET_HEIGHT}px")
    print(f"  File size: {os.path.getsize(output_path):,} bytes")
    print("\n  Using draw16bitBeRGBBitmap = NO MORE FLICKERING!")
    
    # Cleanup
    if os.path.exists(gif_path):
        os.remove(gif_path)
        print(f"  Cleaned up: {gif_path}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
