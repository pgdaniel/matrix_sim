"""Matrix rain screen: green code cascading down the panel, movie-style."""

import random
import threading

from PIL import Image, ImageDraw, ImageFont

from .base import HEIGHT, Screen, WIDTH

CHARS = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Subset of Noto Sans Mono CJK JP (Katakana + digits + A-Z only) so the
# glyphs actually render instead of falling back to tofu boxes — see
# MatrixRainKana-OFL.txt for the font's license.
FONT_PATH = "MatrixRainKana.ttf"
FONT_SIZE = 6

COL_WIDTH = 6
CHAR_HEIGHT = 6
NUM_COLS = WIDTH // COL_WIDTH
NUM_ROWS = HEIGHT // CHAR_HEIGHT

# The falling glyph itself is near-white, like the movie's leading character;
# the rest of the streak decays exponentially from a saturated green down to
# the same dim green the resting background "wash" sits at.
HEAD_COLOR = (215, 255, 220)
BRIGHT_COLOR = (110, 255, 120)
DIM_FLOOR = (0, 40, 10)
TRAIL_DECAY = 0.72


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class MatrixRainScreen(Screen):
    name = "matrix-rain"

    def __init__(self):
        self.font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        self.columns = []
        # A dim, mostly-static wash of resting characters behind the bright
        # streaks, so the whole panel reads as "full of code" rather than
        # mostly black — the movie effect never shows bare background.
        self.background = [
            [random.choice(CHARS) for _ in range(NUM_COLS)] for _ in range(NUM_ROWS)
        ]
        self._lock = threading.Lock()

    def _new_column(self, i):
        return {
            "x": i * COL_WIDTH,
            "y": random.uniform(-NUM_ROWS, -1),
            "speed": random.uniform(0.15, 0.6),
            "chars": [random.choice(CHARS) for _ in range(NUM_ROWS + 20)],
            "length": random.randint(8, 20),
        }

    def start(self, stop_event, notify_update):
        self.columns = [self._new_column(i) for i in range(NUM_COLS)]
        # Stagger initial positions across the full height so the first
        # frame doesn't look like every column just spawned at once.
        for col in self.columns:
            col["y"] = random.uniform(-2, NUM_ROWS)

        def animator():
            while not stop_event.is_set():
                with self._lock:
                    for _ in range(2):
                        r = random.randrange(NUM_ROWS)
                        c = random.randrange(NUM_COLS)
                        self.background[r][c] = random.choice(CHARS)

                    for i, col in enumerate(self.columns):
                        col["y"] += col["speed"]
                        if col["y"] - col["length"] > NUM_ROWS:
                            self.columns[i] = self._new_column(i)
                            continue
                        head_row = int(col["y"])
                        if 0 <= head_row < NUM_ROWS and random.random() < 0.5:
                            idx = head_row % len(col["chars"])
                            col["chars"][idx] = random.choice(CHARS)
                        if random.random() < 0.05:
                            idx = random.randrange(len(col["chars"]))
                            col["chars"][idx] = random.choice(CHARS)
                notify_update()
                stop_event.wait(0.1)

        threading.Thread(target=animator, daemon=True).start()

    def render(self):
        img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        with self._lock:
            for row in range(NUM_ROWS):
                for c in range(NUM_COLS):
                    draw.text(
                        (c * COL_WIDTH, row * CHAR_HEIGHT - 2),
                        self.background[row][c],
                        fill=DIM_FLOOR,
                        font=self.font,
                    )

            for col in self.columns:
                head_row = int(col["y"])
                for offset in range(col["length"]):
                    row = head_row - offset
                    if row < 0 or row >= NUM_ROWS:
                        continue
                    char = col["chars"][row % len(col["chars"])]
                    px = col["x"]
                    py = row * CHAR_HEIGHT - 2

                    if offset == 0:
                        color = HEAD_COLOR
                    else:
                        scale = TRAIL_DECAY ** (offset - 1)
                        color = _lerp(DIM_FLOOR, BRIGHT_COLOR, scale)

                    draw.text((px, py), char, fill=color, font=self.font)

        return img
