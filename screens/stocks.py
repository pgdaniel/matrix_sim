"""Stocks screen — stub for now; replace render() with a real quote fetch later."""

from PIL import Image, ImageDraw, ImageFont

from .base import FONT_PATH, HEIGHT, Screen, WIDTH

TEXT_COLOR = (255, 255, 255)
SUBTITLE_COLOR = (110, 110, 125)


class StocksScreen(Screen):
    name = "stocks"

    def __init__(self):
        self.title_font = ImageFont.truetype(FONT_PATH, 13)
        self.subtitle_font = ImageFont.load_default()

    def render(self):
        img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        title = "STOCKS"
        x0, y0, x1, y1 = self.title_font.getbbox(title)
        tw, th = x1 - x0, y1 - y0
        draw.text(((WIDTH - tw) // 2, HEIGHT // 2 - th - 2 - y0), title, font=self.title_font, fill=TEXT_COLOR)

        subtitle = "SOON"
        sx0, sy0, sx1, sy1 = self.subtitle_font.getbbox(subtitle)
        sw = sx1 - sx0
        draw.text(((WIDTH - sw) // 2, HEIGHT // 2 + 4), subtitle, font=self.subtitle_font, fill=SUBTITLE_COLOR)

        return img
