"""Cyberpunk-themed weather screen: same data as screens/weather.py, neon
outlines, scanlines, and a magenta/cyan glow instead of filled icons."""

import math
import threading

from PIL import Image, ImageDraw, ImageFont

from .base import HEIGHT, Screen, WIDTH
from .cyberpunk_theme import (
    BG_COLOR,
    NEON_CYAN,
    NEON_PINK,
    RETRO_FONT_PATH,
    draw_glow_text,
    draw_scanlines,
)
from .weather import get_location, get_weather

# Retro/synthwave sun: a vertical orange-to-magenta gradient sliced by a few
# horizontal gap bands that thicken toward the bottom.
SUN_TOP_COLOR = (255, 214, 10)
SUN_BOTTOM_COLOR = (255, 0, 110)
SUN_GAPS = [(0.55, 1), (0.68, 2), (0.82, 3)]  # (fraction down, gap thickness in px)


def _lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _draw_retro_sun(draw, cx, cy, r):
    top, bottom = cy - r, cy + r
    for y in range(int(top), int(bottom) + 1):
        dy = y - cy
        if abs(dy) > r:
            continue
        dx = math.sqrt(max(0, r * r - dy * dy))
        t = (y - top) / (2 * r) if r else 0
        draw.line((cx - dx, y, cx + dx, y), fill=_lerp_color(SUN_TOP_COLOR, SUN_BOTTOM_COLOR, t))

    for frac, thickness in SUN_GAPS:
        gy0 = top + 2 * r * frac
        gy1 = gy0 + thickness
        dy_max = max(abs(gy0 - cy), abs(gy1 - cy))
        if dy_max > r:
            continue
        dx = math.sqrt(max(0, r * r - dy_max * dy_max))
        draw.rectangle((cx - dx, gy0, cx + dx, gy1), fill=BG_COLOR)


def _draw_neon_cloud(draw, x0, y0, x1, y1):
    w, h = x1 - x0, y1 - y0
    draw.rectangle((x0, y0 + h * 0.45, x1, y1), outline=NEON_PINK, width=1)
    draw.ellipse((x0, y0 + h * 0.10, x0 + w * 0.55, y0 + h * 0.70), outline=NEON_PINK, width=1)
    draw.ellipse((x0 + w * 0.35, y0, x0 + w * 0.95, y0 + h * 0.60), outline=NEON_PINK, width=1)


def _draw_neon_icon(draw, kind, x0, y0, x1, y1):
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    if kind == "sun":
        _draw_retro_sun(draw, cx, cy, min(w, h) / 2 - 5)
    elif kind == "partly_cloudy":
        _draw_retro_sun(draw, x0 + w * 0.35, y0 + h * 0.30, min(w, h) / 6)
        _draw_neon_cloud(draw, x0 + w * 0.05, y0 + h * 0.35, x1, y1)
    elif kind == "cloudy":
        _draw_neon_cloud(draw, x0, y0 + h * 0.10, x1, y1)
    elif kind == "fog":
        step = max(2, int(h // 5))
        for yy in range(int(y0 + h * 0.15), int(y1), step):
            draw.line((x0, yy, x1, yy), fill=NEON_CYAN, width=1)
    elif kind == "rain":
        _draw_neon_cloud(draw, x0, y0, x1, y0 + h * 0.65)
        for i in range(3):
            dx = x0 + w * (0.2 + 0.3 * i)
            draw.line((dx, y0 + h * 0.75, dx - 2, y1), fill=NEON_CYAN, width=1)
    elif kind == "snow":
        _draw_neon_cloud(draw, x0, y0, x1, y0 + h * 0.60)
        for i in range(3):
            dx = x0 + w * (0.2 + 0.3 * i)
            dy = y0 + h * 0.85
            draw.line((dx - 2, dy, dx + 2, dy), fill=NEON_CYAN, width=1)
            draw.line((dx, dy - 2, dx, dy + 2), fill=NEON_CYAN, width=1)
    elif kind == "storm":
        _draw_neon_cloud(draw, x0, y0, x1, y0 + h * 0.60)
        draw.line([(cx + 2, y0 + h * 0.55), (cx - 4, y0 + h * 0.82),
                   (cx, y0 + h * 0.82), (cx - 3, y1)], fill=NEON_CYAN, width=1)


class CyberpunkWeatherScreen(Screen):
    name = "weather-cyberpunk"

    def __init__(self, latitude=None, longitude=None, refresh_minutes=10):
        self.latitude = latitude
        self.longitude = longitude
        self.refresh_minutes = refresh_minutes
        self.city = None
        self.font = ImageFont.truetype(RETRO_FONT_PATH, 24)
        self._lock = threading.Lock()
        self._temp_f = None
        self._icon_kind = None

    def start(self, stop_event, notify_update):
        if self.latitude is None or self.longitude is None:
            self.latitude, self.longitude, self.city = get_location()
        else:
            self.city = f"{self.latitude:.2f}, {self.longitude:.2f}"

        def updater():
            while not stop_event.is_set():
                try:
                    temp_f, icon_kind = get_weather(self.latitude, self.longitude)
                    with self._lock:
                        self._temp_f = temp_f
                        self._icon_kind = icon_kind
                    notify_update()
                except Exception as e:
                    print(f"[weather-cyberpunk] fetch failed: {e}")
                stop_event.wait(max(1, self.refresh_minutes) * 60)

        threading.Thread(target=updater, daemon=True).start()

    def render(self):
        with self._lock:
            temp_f, icon_kind = self._temp_f, self._icon_kind
        if temp_f is None:
            return None

        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_scanlines(draw)

        icon_size = HEIGHT
        _draw_neon_icon(draw, icon_kind, 1, 0, icon_size - 1, icon_size)

        text = f"{round(temp_f)}°"
        x0, y0, x1, y1 = self.font.getbbox(text)
        tw, th = x1 - x0, y1 - y0
        tx = icon_size + max(0, (WIDTH - icon_size - tw) // 2)
        ty = (HEIGHT - th) // 2 - y0
        draw_glow_text(draw, (tx, ty), text, self.font)

        return img
