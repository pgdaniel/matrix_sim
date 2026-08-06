"""Mondrian-style generative art screen: a fresh random composition every few
seconds — the canvas recursively split into rectangles, separated by thick
black lines, most left white and a few filled with primary red, blue, and
yellow, after Piet Mondrian's De Stijl compositions."""

import random
import threading

from PIL import Image, ImageDraw

from .base import HEIGHT, Screen, WIDTH

WHITE = (245, 245, 240)
BLACK = (10, 10, 10)
RED = (221, 1, 0)
BLUE = (20, 30, 190)
YELLOW = (250, 201, 1)

LINE = 2             # black grid line thickness
MIN_SIZE = 10        # smallest rect side before a split is refused
MAX_DEPTH = 5
REDRAW_SECONDS = 5   # time between new compositions while active

# Cumulative fill odds for a rect; anything past the last one stays white,
# so compositions end up mostly white with a few color blocks, as Mondrian's.
_FILLS = [(RED, 0.10), (BLUE, 0.20), (YELLOW, 0.32)]


def _subdivide(x, y, w, h, rects, depth=0):
    """Recursively split the rect, leaving LINE px between the halves (the
    black background shows through as the grid lines)."""
    can_wide = w >= 2 * MIN_SIZE + LINE
    can_tall = h >= 2 * MIN_SIZE + LINE
    stop = depth >= MAX_DEPTH or (not can_wide and not can_tall) or (depth > 0 and random.random() < 0.2)
    if stop:
        rects.append((x, y, w, h))
        return
    if can_wide and (not can_tall or w > h or (w == h and random.random() < 0.5)):
        cut = random.randint(MIN_SIZE, w - LINE - MIN_SIZE)
        _subdivide(x, y, cut, h, rects, depth + 1)
        _subdivide(x + cut + LINE, y, w - cut - LINE, h, rects, depth + 1)
    else:
        cut = random.randint(MIN_SIZE, h - LINE - MIN_SIZE)
        _subdivide(x, y, w, cut, rects, depth + 1)
        _subdivide(x, y + cut + LINE, w, h - cut - LINE, rects, depth + 1)


def _composition():
    rects = []
    _subdivide(0, 0, WIDTH, HEIGHT, rects)
    fills = []
    for _ in rects:
        fill = WHITE
        r = random.random()
        for color, odds in _FILLS:
            if r < odds:
                fill = color
                break
        fills.append(fill)
    # A composition with no color block at all looks blank; repaint one.
    if all(fill == WHITE for fill in fills):
        fills[random.randrange(len(fills))] = random.choice([RED, BLUE, YELLOW])

    img = Image.new("RGB", (WIDTH, HEIGHT), BLACK)
    draw = ImageDraw.Draw(img)
    for (x, y, w, h), fill in zip(rects, fills):
        draw.rectangle((x, y, x + w - 1, y + h - 1), fill=fill)
    return img


class MondrianScreen(Screen):
    name = "mondrian"

    def start(self, stop_event, notify_update):
        # notify_update only marks the display dirty when this screen is
        # current, so compositions only change while it's on screen.
        def ticker():
            while not stop_event.is_set():
                notify_update()
                stop_event.wait(REDRAW_SECONDS)

        threading.Thread(target=ticker, daemon=True).start()

    def render(self):
        return _composition()
