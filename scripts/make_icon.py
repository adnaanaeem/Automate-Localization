"""
Generates the app icon: a globe (localization) with a circular sync arrow
badge (automation), in the app's UI accent blue. Pure PIL drawing -- no SVG
rasterizer dependency. Run once to produce app/icon.ico, app/icon.icns
(macOS -- Pillow can write ICNS directly, no `iconutil`/macOS host needed),
and a preview PNG; not part of the app's runtime.
"""

import math
import os

from PIL import Image, ImageDraw

SS = 4  # supersample factor for anti-aliasing
SIZE = 256 * SS

ACCENT_LIGHT = (91, 147, 255, 255)   # #5b93ff
ACCENT_DARK = (36, 80, 184, 255)     # #2450b8
WHITE = (255, 255, 255, 255)


def make_background(size):
    """Diagonal gradient rounded-square, matching the app's accent blue."""
    grad = Image.new("RGBA", (size, size))
    for y in range(size):
        for x in range(0, size, 4):  # step 4, then stretch -- plenty smooth after downsample
            t = (x + y) / (2 * size)
            r = int(ACCENT_LIGHT[0] + (ACCENT_DARK[0] - ACCENT_LIGHT[0]) * t)
            g = int(ACCENT_LIGHT[1] + (ACCENT_DARK[1] - ACCENT_LIGHT[1]) * t)
            b = int(ACCENT_LIGHT[2] + (ACCENT_DARK[2] - ACCENT_LIGHT[2]) * t)
            grad.paste((r, g, b, 255), (x, y, min(x + 4, size), y + 1))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255
    )
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg.paste(grad, (0, 0), mask)
    return bg


def draw_globe(draw, cx, cy, r, width):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=WHITE, width=width)
    draw.line([cx, cy - r, cx, cy + r], fill=WHITE, width=width)
    draw.line([cx - r, cy, cx + r, cy], fill=WHITE, width=width)
    ew = int(r * 0.42)
    draw.ellipse([cx - ew, cy - r, cx + ew, cy + r], outline=WHITE, width=width)


def draw_sync_badge(img, cx, cy, r):
    badge = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    bd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)

    arrow_r = int(r * 0.55)
    stroke = int(r * 0.20)
    # Two ~150-degree arcs (a broken ring) so it reads as a "sync" loop, not a closed circle.
    bd.arc([cx - arrow_r, cy - arrow_r, cx + arrow_r, cy + arrow_r],
           start=200, end=340, fill=ACCENT_DARK, width=stroke)
    bd.arc([cx - arrow_r, cy - arrow_r, cx + arrow_r, cy + arrow_r],
           start=20, end=160, fill=ACCENT_DARK, width=stroke)

    def arrowhead(angle_deg, point_angle_deg):
        ang = math.radians(angle_deg)
        tip_x = cx + arrow_r * math.cos(ang)
        tip_y = cy + arrow_r * math.sin(ang)
        size = stroke * 1.6
        pa = math.radians(point_angle_deg)
        left = (tip_x + size * math.cos(pa + 2.5), tip_y + size * math.sin(pa + 2.5))
        right = (tip_x + size * math.cos(pa - 2.5), tip_y + size * math.sin(pa - 2.5))
        bd.polygon([(tip_x, tip_y), left, right], fill=ACCENT_DARK)

    arrowhead(340, 340 + 90)
    arrowhead(160, 160 + 90)

    img.alpha_composite(badge)


def main():
    bg = make_background(SIZE)
    draw = ImageDraw.Draw(bg)

    globe_cx, globe_cy = int(SIZE * 0.42), int(SIZE * 0.42)
    globe_r = int(SIZE * 0.27)
    draw_globe(draw, globe_cx, globe_cy, globe_r, width=int(SIZE * 0.018))

    draw_sync_badge(bg, int(SIZE * 0.74), int(SIZE * 0.74), int(SIZE * 0.20))

    master = bg.resize((256, 256), Image.LANCZOS)

    out_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.join(os.path.dirname(out_dir), "app")

    preview_path = os.path.join(out_dir, "icon_preview.png")
    master.save(preview_path)

    ico_path = os.path.join(app_dir, "icon.ico")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(ico_path, format="ICO", sizes=sizes)

    # ICNS wants a square source at least 1024px for its largest (retina
    # Dock/Finder) representation -- use the pre-downsample supersampled
    # canvas (SIZE = 1024 here) rather than the 256px `master`, so the
    # large sizes Pillow generates from it aren't upscaled and blurry.
    icns_path = os.path.join(app_dir, "icon.icns")
    bg.save(icns_path, format="ICNS")

    print("wrote", preview_path)
    print("wrote", ico_path)
    print("wrote", icns_path)


if __name__ == "__main__":
    main()
