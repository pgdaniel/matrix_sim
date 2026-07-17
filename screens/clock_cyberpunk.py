"""Cyberpunk-themed clock screen: current time, same neon palette, scanlines,
and VT323 font as screens/weather_cyberpunk.py. Current temperature (far
left) and AQI (far right) underneath instead of the calendar date."""

import threading
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from .base import HEIGHT, Screen, WIDTH
from .cyberpunk_theme import BG_COLOR, RETRO_FONT_PATH, draw_glow_text, draw_scanlines
from .weather import get_aqi, get_location, get_weather


class ClockCyberpunkScreen(Screen):
    name = "clock-cyberpunk"

    def __init__(self, latitude=None, longitude=None, refresh_minutes=10):
        self.time_font = ImageFont.truetype(RETRO_FONT_PATH, 24)
        self.info_font = ImageFont.truetype(RETRO_FONT_PATH, 11)
        self.latitude = latitude
        self.longitude = longitude
        self.refresh_minutes = refresh_minutes
        self.city = None
        self._lock = threading.Lock()
        self._temp_f = None
        self._aqi = None

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
                    aqi = get_aqi(self.latitude, self.longitude)
                    with self._lock:
                        self._temp_f = temp_f
                        self._aqi = aqi
                    notify_update()
                except Exception as e:
                    print(f"[clock-cyberpunk] weather fetch failed: {e}")
                stop_event.wait(max(1, self.refresh_minutes) * 60)

        threading.Thread(target=updater, daemon=True).start()

    def render(self):
        now = datetime.now()
        time_text = now.strftime("%H:%M")
        with self._lock:
            temp_f, aqi = self._temp_f, self._aqi
        temp_text = f"{round(temp_f)}°" if temp_f is not None else ""
        aqi_text = f"AQI {aqi}" if aqi is not None else ""

        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_scanlines(draw)

        x0, y0, x1, y1 = self.time_font.getbbox(time_text)
        tw, th = x1 - x0, y1 - y0
        tx = (WIDTH - tw) // 2
        ty = 3 - y0
        draw_glow_text(draw, (tx, ty), time_text, self.time_font)

        if temp_text:
            _x0, ty0, _x1, ty1 = self.info_font.getbbox(temp_text)
            th2 = ty1 - ty0
            tyy = HEIGHT - th2 - 4 - ty0
            draw_glow_text(draw, (1, tyy), temp_text, self.info_font)

        if aqi_text:
            ax0, ay0, ax1, ay1 = self.info_font.getbbox(aqi_text)
            aw, ah = ax1 - ax0, ay1 - ay0
            ayy = HEIGHT - ah - 4 - ay0
            draw_glow_text(draw, (WIDTH - aw - 1, ayy), aqi_text, self.info_font)

        return img
