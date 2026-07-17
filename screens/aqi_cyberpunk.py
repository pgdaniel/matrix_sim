"""Cyberpunk-themed AQI screen: same neon palette, scanlines, and VT323 font
as the other cyberpunk screens, showing just the current US AQI — the number
glows in a color for its severity category, from green (good) to maroon
(hazardous)."""

import threading

from PIL import Image, ImageDraw, ImageFont

from .base import HEIGHT, Screen, WIDTH
from .cyberpunk_theme import BG_COLOR, NEON_YELLOW, RETRO_FONT_PATH, draw_glow_text, draw_scanlines
from .weather import get_aqi, get_location

# (upper bound, label, neon color) for each US AQI category, in order.
_AQI_LEVELS = [
    (50, "GOOD", (0, 255, 120)),
    (100, "MODERATE", NEON_YELLOW),
    (150, "SENSITIVE", (255, 140, 0)),
    (200, "UNHEALTHY", (255, 40, 40)),
    (300, "V.UNHLTHY", (180, 40, 255)),
    (float("inf"), "HAZARDOUS", (170, 0, 60)),
]


def _aqi_level(aqi):
    for cutoff, label, color in _AQI_LEVELS:
        if aqi <= cutoff:
            return label, color
    return _AQI_LEVELS[-1][1], _AQI_LEVELS[-1][2]


class AqiCyberpunkScreen(Screen):
    name = "aqi-cyberpunk"

    def __init__(self, latitude=None, longitude=None, refresh_minutes=10):
        self.latitude = latitude
        self.longitude = longitude
        self.refresh_minutes = refresh_minutes
        self.number_font = ImageFont.truetype(RETRO_FONT_PATH, 24)
        self.label_font = ImageFont.truetype(RETRO_FONT_PATH, 11)
        self._lock = threading.Lock()
        self._aqi = None

    def start(self, stop_event, notify_update):
        if self.latitude is None or self.longitude is None:
            self.latitude, self.longitude, _city = get_location()

        def updater():
            while not stop_event.is_set():
                try:
                    aqi = get_aqi(self.latitude, self.longitude)
                    with self._lock:
                        self._aqi = aqi
                    notify_update()
                except Exception as e:
                    print(f"[aqi-cyberpunk] fetch failed: {e}")
                stop_event.wait(max(1, self.refresh_minutes) * 60)

        threading.Thread(target=updater, daemon=True).start()

    def render(self):
        with self._lock:
            aqi = self._aqi
        if aqi is None:
            return None

        label, color = _aqi_level(aqi)
        number = str(round(aqi))

        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_scanlines(draw)

        nx0, ny0, nx1, ny1 = self.number_font.getbbox(number)
        nw = nx1 - nx0
        draw_glow_text(draw, ((WIDTH - nw) // 2, 3 - ny0), number, self.number_font, fill=color)

        lx0, ly0, lx1, ly1 = self.label_font.getbbox(label)
        lw, lh = lx1 - lx0, ly1 - ly0
        ly = HEIGHT - lh - 3 - ly0
        draw_glow_text(draw, ((WIDTH - lw) // 2, ly), label, self.label_font, fill=color)

        return img
