"""Cyberpunk-themed clock screen: current time, same neon palette, scanlines,
and VT323 font as screens/weather_cyberpunk.py."""

import threading
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from .base import HEIGHT, Screen, WIDTH
from .cyberpunk_theme import BG_COLOR, RETRO_FONT_PATH, draw_glow_text, draw_scanlines


class ClockCyberpunkScreen(Screen):
    name = "clock-cyberpunk"

    def __init__(self):
        self.time_font = ImageFont.truetype(RETRO_FONT_PATH, 24)

    def start(self, stop_event, notify_update):
        def ticker():
            while not stop_event.is_set():
                notify_update()
                stop_event.wait(1)

        threading.Thread(target=ticker, daemon=True).start()

    def render(self):
        now = datetime.now()
        time_text = now.strftime("%H:%M")

        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_scanlines(draw)

        x0, y0, x1, y1 = self.time_font.getbbox(time_text)
        tw, th = x1 - x0, y1 - y0
        tx = (WIDTH - tw) // 2
        ty = (HEIGHT - th) // 2 - y0
        draw_glow_text(draw, (tx, ty), time_text, self.time_font)

        return img
