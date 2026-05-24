#!/usr/bin/env python3
"""
Mistral GIF to C++ - ALL FRAMES VERSION
Extrait TOUTES les frames du GIF original avec double buffer PSRAM.

Usage:
    python generate_all_frames.py

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

def process_gif(gif_path):
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
    """Generate C++ header with ALL frame data"""
    num_frames = len(frames)
    
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
#define NUM_FRAMES  {num_frames}

// Total pixels per frame
#define FRAME_SIZE  (GIF_WIDTH * GIF_HEIGHT)

"""
    
    # Generate frame data arrays
    for i in range(num_frames):
        pixels = frame_to_c_array(frames[i])
        header += f"// Frame {i} data\n"
        header += f"const uint16_t frame_{i}_data[FRAME_SIZE] PROGMEM = {{\n"
        
        for j, pixel in enumerate(pixels):
            if j % 16 == 0:
                header += "    "
            header += f"0x{pixel:04X}, "
            if j % 16 == 15:
                header += "\n"
        
        header += "};\n\n"
    
    # Generate frame pointer array
    header += "// Frame pointer array for easy access\n"
    header += "const uint16_t* const all_frames[NUM_FRAMES] = {\n"
    for i in range(num_frames):
        header += f"    frame_{i}_data,\n"
    header += "};\n\n"
    
    return header

def main():
    print("=" * 60)
    print("Mistral GIF to C++ - ALL FRAMES")
    print("=" * 60)
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Download GIF
    gif_path = download_gif(GIF_URL)
    
    # Process GIF - ALL FRAMES
    frames = process_gif(gif_path)
    
    # Generate C header
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
    print("NEXT: gif_animator.cpp uses all_frames[] array")
    print("=" * 60)

if __name__ == "__main__":
    main()
