"""Shared palette, font, and helpers for the cyberpunk-themed screens."""

from .base import HEIGHT, WIDTH

BG_COLOR = (6, 3, 16)
SCANLINE_COLOR = (20, 8, 40)
NEON_CYAN = (0, 240, 255)
NEON_PINK = (255, 0, 170)
NEON_YELLOW = (255, 230, 60)

RETRO_FONT_PATH = "VT323-Regular.ttf"


def draw_scanlines(draw):
    for y in range(0, HEIGHT, 3):
        draw.line((0, y, WIDTH, y), fill=SCANLINE_COLOR, width=1)


def draw_glow_text(draw, xy, text, font, fill=NEON_CYAN, shadow=NEON_PINK, offset=1):
    """Cheap neon glow: a shadow-colored copy offset by one pixel, then the
    main color on top."""
    x, y = xy
    draw.text((x + offset, y + offset), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)
