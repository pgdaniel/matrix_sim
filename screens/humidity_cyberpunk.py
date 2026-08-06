"""Cyberpunk-themed humidity screen: same neon palette, scanlines, and VT323
font as the other cyberpunk screens, showing the current relative humidity
as a glowing percentage with a label below."""

import threading

from PIL import Image, ImageDraw, ImageFont

from .base import HEIGHT, Screen, WIDTH
from .cyberpunk_theme import BG_COLOR, RETRO_FONT_PATH, draw_glow_text, draw_scanlines
from .weather import get_humidity, get_location


class HumidityCyberpunkScreen(Screen):
    name = "humidity-cyberpunk"

    def __init__(self, latitude=None, longitude=None, refresh_minutes=10):
        self.latitude = latitude
        self.longitude = longitude
        self.refresh_minutes = refresh_minutes
        self.number_font = ImageFont.truetype(RETRO_FONT_PATH, 24)
        self.label_font = ImageFont.truetype(RETRO_FONT_PATH, 11)
        self._lock = threading.Lock()
        self._humidity = None

    def start(self, stop_event, notify_update):
        if self.latitude is None or self.longitude is None:
            self.latitude, self.longitude, _city = get_location()

        def updater():
            while not stop_event.is_set():
                try:
                    humidity = get_humidity(self.latitude, self.longitude)
                    with self._lock:
                        self._humidity = humidity
                    notify_update()
                except Exception as e:
                    print(f"[humidity-cyberpunk] fetch failed: {e}")
                stop_event.wait(max(1, self.refresh_minutes) * 60)

        threading.Thread(target=updater, daemon=True).start()

    def render(self):
        with self._lock:
            humidity = self._humidity
        if humidity is None:
            return None

        number = f"{round(humidity)}%"
        label = "HUMIDITY"

        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_scanlines(draw)

        nx0, ny0, nx1, ny1 = self.number_font.getbbox(number)
        nw = nx1 - nx0
        draw_glow_text(draw, ((WIDTH - nw) // 2, 3 - ny0), number, self.number_font)

        lx0, ly0, lx1, ly1 = self.label_font.getbbox(label)
        lw, lh = lx1 - lx0, ly1 - ly0
        ly = HEIGHT - lh - 3 - ly0
        draw_glow_text(draw, ((WIDTH - lw) // 2, ly), label, self.label_font)

        return img
