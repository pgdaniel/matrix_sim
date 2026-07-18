"""Message screen — shows a short text message, "Hello" by default.
Updatable at runtime via POST /message on the control server (see
matrix_server.py), which calls set_message() below. Not written to
screen_config.json or anywhere else, so it resets to the default on
restart — deliberately in-memory only."""

import threading

from PIL import Image, ImageDraw, ImageFont

from .base import FONT_PATH, HEIGHT, Screen, WIDTH

TEXT_COLOR = (255, 255, 255)
DEFAULT_MESSAGE = "Hello"


class MessageScreen(Screen):
    name = "message"

    def __init__(self, message=DEFAULT_MESSAGE):
        self.font = ImageFont.truetype(FONT_PATH, 13)
        self._lock = threading.Lock()
        self._message = message
        self._notify_update = None

    def start(self, stop_event, notify_update):
        self._notify_update = notify_update

    @property
    def message(self):
        with self._lock:
            return self._message

    def set_message(self, message):
        message = message.strip() if message else ""
        with self._lock:
            self._message = message or DEFAULT_MESSAGE
        if self._notify_update:
            self._notify_update()

    def _width(self, text):
        x0, _y0, x1, _y1 = self.font.getbbox(text)
        return x1 - x0

    def _wrap(self, text):
        words = text.split()
        if not words:
            return [text]
        lines, line = [], words[0]
        for word in words[1:]:
            trial = f"{line} {word}"
            if self._width(trial) <= WIDTH:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
        return lines

    def render(self):
        img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        lines = self._wrap(self.message)
        _lx0, ly0, _lx1, ly1 = self.font.getbbox("Ag")
        line_height = (ly1 - ly0) + 2
        y = max(0, (HEIGHT - line_height * len(lines)) // 2)
        for line in lines:
            x0, y0, x1, _y1 = self.font.getbbox(line)
            draw.text(((WIDTH - (x1 - x0)) // 2, y - y0), line, font=self.font, fill=TEXT_COLOR)
            y += line_height

        return img
