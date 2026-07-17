"""Cyberpunk-themed clock screen: current time, same neon palette, scanlines,
and VT323 font as screens/weather_cyberpunk.py. The current temperature is
shown underneath the time instead of the calendar date, with the day's low
(far left) and high (far right) in a smaller font."""

import threading
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from .base import HEIGHT, Screen, WIDTH
from .cyberpunk_theme import BG_COLOR, RETRO_FONT_PATH, draw_glow_text, draw_scanlines
from .weather import get_daily_range, get_location, get_weather


class ClockCyberpunkScreen(Screen):
    name = "clock-cyberpunk"

    def __init__(self, latitude=None, longitude=None, refresh_minutes=10):
        self.time_font = ImageFont.truetype(RETRO_FONT_PATH, 24)
        self.weather_font = ImageFont.truetype(RETRO_FONT_PATH, 12)
        self.range_font = ImageFont.truetype(RETRO_FONT_PATH, 11)
        self.latitude = latitude
        self.longitude = longitude
        self.refresh_minutes = refresh_minutes
        self.city = None
        self._lock = threading.Lock()
        self._temp_f = None
        self._low_f = None
        self._high_f = None

    def start(self, stop_event, notify_update):
        def ticker():
            while not stop_event.is_set():
                notify_update()
                stop_event.wait(1)

        threading.Thread(target=ticker, daemon=True).start()

        if self.latitude is None or self.longitude is None:
            self.latitude, self.longitude, self.city = get_location()
        else:
            self.city = f"{self.latitude:.2f}, {self.longitude:.2f}"

        def updater():
            while not stop_event.is_set():
                try:
                    temp_f, _icon_kind = get_weather(self.latitude, self.longitude)
                    low_f, high_f = get_daily_range(self.latitude, self.longitude)
                    with self._lock:
                        self._temp_f = temp_f
                        self._low_f = low_f
                        self._high_f = high_f
                    notify_update()
                except Exception as e:
                    print(f"[clock-cyberpunk] weather fetch failed: {e}")
                stop_event.wait(max(1, self.refresh_minutes) * 60)

        threading.Thread(target=updater, daemon=True).start()

    def render(self):
        now = datetime.now()
        time_text = now.strftime("%H:%M")
        with self._lock:
            temp_f, low_f, high_f = self._temp_f, self._low_f, self._high_f
        weather_text = f"{round(temp_f)}°" if temp_f is not None else ""
        low_text = f"{round(low_f)}°" if low_f is not None else ""
        high_text = f"{round(high_f)}°" if high_f is not None else ""

        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_scanlines(draw)

        x0, y0, x1, y1 = self.time_font.getbbox(time_text)
        tw, th = x1 - x0, y1 - y0
        tx = (WIDTH - tw) // 2
        ty = 3 - y0
        draw_glow_text(draw, (tx, ty), time_text, self.time_font)

        if weather_text:
            wx0, wy0, wx1, wy1 = self.weather_font.getbbox(weather_text)
            ww, wh = wx1 - wx0, wy1 - wy0
            wwx = (WIDTH - ww) // 2
            wwy = HEIGHT - wh - 4 - wy0
            draw_glow_text(draw, (wwx, wwy), weather_text, self.weather_font)

        if low_text:
            lx0, ly0, lx1, ly1 = self.range_font.getbbox(low_text)
            lh = ly1 - ly0
            lwy = HEIGHT - lh - 4 - ly0
            draw_glow_text(draw, (1, lwy), low_text, self.range_font)

        if high_text:
            hx0, hy0, hx1, hy1 = self.range_font.getbbox(high_text)
            hw, hh = hx1 - hx0, hy1 - hy0
            hwy = HEIGHT - hh - 4 - hy0
            draw_glow_text(draw, (WIDTH - hw - 1, hwy), high_text, self.range_font)

        return img
