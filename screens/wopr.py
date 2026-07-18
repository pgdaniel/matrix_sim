"""WOPR screen: a WarGames-style teletype terminal, endlessly typing out the
computer's own lines from the film in scrolling green phosphor text."""

import threading

from PIL import Image, ImageDraw, ImageFont

from .base import HEIGHT, Screen, WIDTH

FONT_PATH = "VT323-Regular.ttf"
FONT_SIZE = 9

TEXT_COLOR = (51, 255, 68)
SCANLINE_COLOR = (0, 24, 4)

CHAR_TICK = 0.09  # seconds per typed character
LINE_PAUSE_TICKS = 16  # ticks to hold a finished line before advancing
LOOP_PAUSE_TICKS = 40  # extra hold on the last line before restarting
CURSOR_BLINK_TICKS = 5
MAX_VISIBLE_LINES = 3

SCRIPT = [
    "GREETINGS PROFESSOR FALKEN.",
    "SHALL WE PLAY A GAME?",
    "FALKEN'S MAZE",
    "BLACK JACK",
    "GIN RUMMY",
    "HEARTS",
    "BRIDGE",
    "CHECKERS",
    "CHESS",
    "POKER",
    "GLOBAL THERMONUCLEAR WAR",
    "WOULDN'T YOU PREFER",
    "A NICE GAME OF CHESS?",
    "A STRANGE GAME.",
    "THE ONLY WINNING MOVE",
    "IS NOT TO PLAY.",
]


class WoprScreen(Screen):
    name = "wopr"

    def __init__(self):
        self.font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        self._lock = threading.Lock()
        self.completed_lines = []
        self.current_text = ""
        self.cursor_on = True
        self._script_index = 0
        self._char_index = 0

    def _wrap(self, text):
        """Split `text` into pixel-width-limited lines, same approach as
        MessageScreen._wrap — keeps a hand-tuned SCRIPT line safe even if it
        turns out too wide for the font/width in use."""
        words = text.split()
        if not words:
            return [text]
        lines, line = [], words[0]
        for word in words[1:]:
            trial = f"{line} {word}"
            x0, _y0, x1, _y1 = self.font.getbbox(trial)
            if x1 - x0 <= WIDTH:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
        return lines

    def start(self, stop_event, notify_update):
        lines = []
        for entry in SCRIPT:
            lines.extend(self._wrap(entry))
        self._lines = lines

        def animator():
            tick = 0
            pause_ticks_left = 0
            while not stop_event.is_set():
                with self._lock:
                    if tick % CURSOR_BLINK_TICKS == 0:
                        self.cursor_on = not self.cursor_on

                    if pause_ticks_left > 0:
                        pause_ticks_left -= 1
                    else:
                        target = self._lines[self._script_index]
                        if self._char_index < len(target):
                            self._char_index += 1
                            self.current_text = target[: self._char_index]
                        else:
                            self.completed_lines.append(target)
                            self.completed_lines = self.completed_lines[-MAX_VISIBLE_LINES:]
                            at_end = self._script_index == len(self._lines) - 1
                            self._script_index = (self._script_index + 1) % len(self._lines)
                            self._char_index = 0
                            self.current_text = ""
                            pause_ticks_left = LOOP_PAUSE_TICKS if at_end else LINE_PAUSE_TICKS
                            if self._script_index == 0:
                                self.completed_lines = []
                notify_update()
                tick += 1
                stop_event.wait(CHAR_TICK)

        threading.Thread(target=animator, daemon=True).start()

    def render(self):
        img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        for y in range(0, HEIGHT, 3):
            draw.line((0, y, WIDTH, y), fill=SCANLINE_COLOR, width=1)

        _lx0, ly0, _lx1, ly1 = self.font.getbbox("Ag")
        line_height = (ly1 - ly0) + 2

        with self._lock:
            visible = self.completed_lines[-(MAX_VISIBLE_LINES - 1):] + [self.current_text]
            cursor_on = self.cursor_on

        y = 0
        for i, line in enumerate(visible):
            is_current = i == len(visible) - 1
            text = line + ("_" if is_current and cursor_on else "")
            draw.text((0, y - ly0), text, font=self.font, fill=TEXT_COLOR)
            y += line_height

        return img
