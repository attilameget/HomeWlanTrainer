#!/usr/bin/env python3
"""Render deploy/macos/dmg-background.png.

The Finder window in deploy/macos/dmg-window.applescript places icons on top
of this image. Keep those positions in sync:

  window 680×560
  steadyGrind.app  (170, 180)
  Applications     (510, 180)
  Read Me.txt      (340, 445)

Requires Pillow. The DMG build uses the committed PNG and does not run this.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).with_name("dmg-background.png")
W, H = 680, 560
ARROW_Y = 180
FONT = "/usr/share/fonts/truetype/macos/Inter-SemiBold.ttf"
FONT_FALLBACK = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


def main() -> None:
    image = Image.new("RGBA", (W, H), (244, 248, 251, 255))
    # Soft glow only in the gap between the two icon slots (centers 170 and 510).
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((230, ARROW_Y - 48, 450, ARROW_Y + 48), fill=(156, 203, 229, 150))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=18))
    image = Image.alpha_composite(image, glow)
    draw = ImageDraw.Draw(image)

    # Tip stays left of the Applications icon (that icon's left edge is x=446).
    draw.rounded_rectangle((250, ARROW_Y - 7, 378, ARROW_Y + 7), radius=7, fill="#1f5f85")
    draw.polygon([(360, ARROW_Y - 20), (418, ARROW_Y), (360, ARROW_Y + 20)], fill="#1f5f85")

    font_path = FONT if Path(FONT).is_file() else FONT_FALLBACK
    font = ImageFont.truetype(font_path, 22)
    label = "Drag to Applications"
    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    text_x = (W - text_w) / 2
    text_y = 292
    draw.text((text_x, text_y), label, font=font, fill="#0c2132")

    image.convert("RGB").save(OUT, "PNG", dpi=(72, 72))
    print(f"wrote {OUT} ({W}x{H})")


if __name__ == "__main__":
    main()
