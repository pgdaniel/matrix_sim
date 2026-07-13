"""Cyberpunk-themed weather screen: same data as screens/weather.py, neon
outlines, scanlines, and a magenta/cyan glow instead of filled icons."""

import math
import threading

from PIL import Image, ImageDraw, ImageFont

from .base import FONT_PATH, HEIGHT, Screen, WIDTH
from .weather import get_location, get_weather

BG_COLOR = (6, 3, 16)
SCANLINE_COLOR = (20, 8, 40)
NEON_CYAN = (0, 240, 255)
NEON_PINK = (255, 0, 170)
NEON_YELLOW = (255, 230, 60)


def _draw_scanlines(draw):
    for y in range(0, HEIGHT, 3):
        draw.line((0, y, WIDTH, y), fill=SCANLINE_COLOR, width=1)


def _draw_neon_sun(draw, cx, cy, r):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=NEON_YELLOW, width=1)
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        x1, y1 = cx + (r + 2) * math.cos(rad), cy + (r + 2) * math.sin(rad)
        x2, y2 = cx + (r + 5) * math.cos(rad), cy + (r + 5) * math.sin(rad)
        draw.line((x1, y1, x2, y2), fill=NEON_YELLOW, width=1)


def _draw_neon_cloud(draw, x0, y0, x1, y1):
    w, h = x1 - x0, y1 - y0
    draw.rectangle((x0, y0 + h * 0.45, x1, y1), outline=NEON_PINK, width=1)
    draw.ellipse((x0, y0 + h * 0.10, x0 + w * 0.55, y0 + h * 0.70), outline=NEON_PINK, width=1)
    draw.ellipse((x0 + w * 0.35, y0, x0 + w * 0.95, y0 + h * 0.60), outline=NEON_PINK, width=1)


def _draw_neon_icon(draw, kind, x0, y0, x1, y1):
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    if kind == "sun":
        _draw_neon_sun(draw, cx, cy, min(w, h) / 2 - 5)
    elif kind == "partly_cloudy":
        _draw_neon_sun(draw, x0 + w * 0.35, y0 + h * 0.30, min(w, h) / 6)
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
        self.font = ImageFont.truetype(FONT_PATH, 16)
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
        _draw_scanlines(draw)

        icon_size = HEIGHT
        _draw_neon_icon(draw, icon_kind, 1, 0, icon_size - 1, icon_size)

        text = f"{round(temp_f)}F"
        x0, y0, x1, y1 = self.font.getbbox(text)
        tw, th = x1 - x0, y1 - y0
        tx = icon_size + max(0, (WIDTH - icon_size - tw) // 2)
        ty = (HEIGHT - th) // 2 - y0
        # cheap glow: a pink "shadow" one pixel off, cyan text on top
        draw.text((tx + 1, ty + 1), text, font=self.font, fill=NEON_PINK)
        draw.text((tx, ty), text, font=self.font, fill=NEON_CYAN)

        return img
