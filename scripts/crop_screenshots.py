"""Trims trailing background-color padding off docs/screenshots/*.png after
regenerating them (see README.md's "Screenshots" note) -- msedge's headless
--screenshot flag captures the full --window-size, and the app's content is
usually shorter than the tall window used so every screen fits regardless
of how much it has. Run from the repo root: python scripts/crop_screenshots.py
"""

import os
from PIL import Image

BG = (15, 17, 21)  # --bg from app/web/style.css
SCREEN_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots")
SCREENS = ["setup", "review", "results", "settings", "ios", "import"]


def crop_to_content(path):
    img = Image.open(path)
    w, h = img.size
    px = img.load()
    sample_xs = range(0, w, 7)  # a handful of columns is enough, not every pixel
    last_content_row = 0
    for y in range(h - 1, -1, -1):
        if any(px[x, y][:3] != BG for x in sample_xs):
            last_content_row = y
            break
    crop_h = min(h, last_content_row + 24)  # small bottom margin
    img.crop((0, 0, w, crop_h)).save(path)
    return w, h, crop_h


if __name__ == "__main__":
    for name in SCREENS:
        p = os.path.join(SCREEN_DIR, f"{name}.png")
        if not os.path.exists(p):
            print(f"{name}: skipped (not found)")
            continue
        w, h, crop_h = crop_to_content(p)
        print(f"{name}: {w}x{h} -> {w}x{crop_h}")
