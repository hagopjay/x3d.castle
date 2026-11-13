#!/usr/bin/env python3
"""Writes the tiny PNGs the phase 3 fixtures use (8x8 checker, 8x8 flat normal map with a bump, 8x8 half-transparent)."""
import os
from PIL import Image
here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "img")
os.makedirs(here, exist_ok=True)
chk = Image.new("RGBA", (8, 8))
for y in range(8):
    for x in range(8):
        chk.putpixel((x, y), (230, 90, 40, 255) if (x // 2 + y // 2) % 2 else (40, 90, 230, 255))
chk.save(os.path.join(here, "checker.png"))
nm = Image.new("RGB", (8, 8), (128, 128, 255))
for y in range(2, 6):
    for x in range(2, 6):
        nm.putpixel((x, y), (180, 128, 230) if x < 4 else (76, 128, 230))
nm.save(os.path.join(here, "normal.png"))
al = Image.new("RGBA", (8, 8))
for y in range(8):
    for x in range(8):
        al.putpixel((x, y), (255, 255, 255, 255 if x < 4 else 40))
al.save(os.path.join(here, "half-alpha.png"))
