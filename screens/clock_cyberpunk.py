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
        self.date_font = ImageFont.truetype(RETRO_FONT_PATH, 12)

    def start(self, stop_event, notify_update):
        def ticker():
            while not stop_event.is_set():
                notify_update()
                stop_event.wait(1)

        threading.Thread(target=ticker, daemon=True).start()

    def render(self):
        now = datetime.now()
        time_text = now.strftime("%H:%M")
        date_text = now.strftime("%a %m/%d").upper()

        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_scanlines(draw)

        x0, y0, x1, y1 = self.time_font.getbbox(time_text)
        tw, th = x1 - x0, y1 - y0
        tx = (WIDTH - tw) // 2
        ty = 3 - y0
        draw_glow_text(draw, (tx, ty), time_text, self.time_font)

        dx0, dy0, dx1, dy1 = self.date_font.getbbox(date_text)
        dw, dh = dx1 - dx0, dy1 - dy0
        ddx = (WIDTH - dw) // 2
        ddy = HEIGHT - dh - 4 - dy0
        draw_glow_text(draw, (ddx, ddy), date_text, self.date_font)

        return img
