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
Mistral GIF to C++ - FINAL OPTIMIZED VERSION

Generates ONLY 2 frames (normal + blink) at 240x240 for PSRAM double buffer.

Usage:
    python generate_frames_final.py

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
OUTPUT_FILE = "gif_frames.h"
MAX_FRAMES = 2  # Only keep first 2 frames: normal + blink

def rgb_to_rgb565(r, g, b):
    """Convert RGB888 to RGB565"""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

def download_gif(url):
    print(f"Downloading GIF from {url}...")
    response = requests.get(url)
    response.raise_for_status()
    temp_file = "mistral_chat_temp.gif"
    with open(temp_file, 'wb') as f:
        f.write(response.content)
    print(f"✓ Downloaded: {temp_file}")
    return temp_file

def process_gif(gif_path, max_frames=MAX_FRAMES):
    print(f"Opening GIF: {gif_path}")
    gif = Image.open(gif_path)
    
    frames = []
    try:
        frame_count = 0
        while frame_count < max_frames:
            frame = gif.convert('RGBA')
            frames.append(frame)
            gif.seek(gif.tell() + 1)
            frame_count += 1
    except EOFError:
        pass
    
    print(f"✓ Extracted {len(frames)} frames (limited to {max_frames})")
    
    # Resize all frames to target size
    resized_frames = []
    for i, frame in enumerate(frames):
        resized = frame.resize((TARGET_WIDTH, TARGET_HEIGHT), Image.LANCZOS)
        resized_frames.append(resized)
        print(f"  Frame {i}: {frame.size} -> {resized.size}")
    
    return resized_frames

def frame_to_c_array(frame):
    """Convert frame to C array of RGB565 values"""
    if frame.mode == 'RGBA':
        background = Image.new('RGB', frame.size, (0, 0, 0))
        background.paste(frame, mask=frame.split()[3])
        frame = background
    
    pixels = list(frame.getdata())
    c_array = []
    for rgb in pixels:
        if len(rgb) == 4:
            r, g, b, a = rgb
            c_array.append(rgb_to_rgb565(r, g, b) if a >= 128 else 0x0000)
        else:
            r, g, b = rgb
            c_array.append(rgb_to_rgb565(r, g, b))
    return c_array

def generate_c_header(frames):
    """Generate C++ header with ONLY the frame data arrays"""
    
    header = f"""#pragma once
#include <stdint.h>
#include <pgmspace.h>

// Mistral brand colors (RGB565)
#define MISTRAL_BG     0x0000  // Black
#define MISTRAL_VIOLET 0x9075  // #920E56
#define MISTRAL_ORANGE 0xF48F  // #F7931E
#define MISTRAL_WHITE  0xFFFF  // White

// Frame dimensions
#define GIF_WIDTH   {TARGET_WIDTH}
#define GIF_HEIGHT  {TARGET_HEIGHT}

"""
    
    # Only generate the 2 frame data arrays
    for i in range(min(len(frames), 2)):
        pixels = frame_to_c_array(frames[i])
        header += f"// Frame {i} data (240x240 RGB565)\n"
        header += f"const uint16_t frame_{i}_data[GIF_WIDTH * GIF_HEIGHT] PROGMEM = {{\n"
        
        for j, pixel in enumerate(pixels):
            if j % 16 == 0:
                header += "    "
            header += f"0x{pixel:04X}, "
            if j % 16 == 15:
                header += "\n"
        
        header += "};\n\n"
    
    return header

def main():
    print("=" * 60)
    print("Mistral GIF to C++ - FINAL (2 frames only)")
    print("=" * 60)
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Download GIF
    gif_path = download_gif(GIF_URL)
    
    # Process GIF - ONLY 2 FRAMES
    frames = process_gif(gif_path, max_frames=MAX_FRAMES)
    
    # Generate C header with ONLY frame data
    header_code = generate_c_header(frames)
    
    # Write output
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    with open(output_path, 'w') as f:
        f.write(header_code)
    
    print(f"\n✓ Generated: {output_path}")
    print(f"  {len(frames)} frames, {TARGET_WIDTH}x{TARGET_HEIGHT}px")
    print(f"  File size: {os.path.getsize(output_path):,} bytes")
    
    # Cleanup
    if os.path.exists(gif_path):
        os.remove(gif_path)
        print(f"  Cleaned up: {gif_path}")
    
    print("\n" + "=" * 60)
    print("NEXT: Update anim.h/cpp to use GifAnimator class")
    print("=" * 60)

if __name__ == "__main__":
    main()
