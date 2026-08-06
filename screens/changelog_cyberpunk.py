"""Cyberpunk-themed Slackware changelog screen: pulls the slackware-current
changelog once a day and slowly scrolls through the most recent entries,
a pixel at a time, only while it's the active screen — so it advances a
little each time the rotation comes around, and starts over from the top
once it has scrolled through everything.

Same palette/scanlines/VT323 font as the other cyberpunk screens."""

import html
import re
import threading

import requests
from PIL import Image, ImageDraw, ImageFont

from .base import HEIGHT, Screen, WIDTH
from .cyberpunk_theme import BG_COLOR, NEON_CYAN, RETRO_FONT_PATH, draw_scanlines

CHANGELOG_URL = "http://www.slackware.com/changelog/current.php?cpu=x86_64"
MAX_LINES = 300          # newest source lines to keep (newest are at the top)
SCROLL_SECONDS = 0.15    # ticker interval; each redraw scrolls one pixel
REFETCH_SECONDS = 24 * 60 * 60
RETRY_SECONDS = 60       # wait this long before retrying a failed fetch

_DATE_RE = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \w{3}\s+\d+ \d\d:\d\d:\d\d UTC \d{4}")
_TAG_RE = re.compile(r"<[^>]*>")
_SEPARATOR = "+--------------------------+"


def _extract_lines(page):
    """Pull the changelog entries out of the slackware.com changelog page:
    strip the HTML chrome, keep the newest MAX_LINES lines of entry text."""
    lines = []
    started = False
    for raw in page.splitlines():
        line = _TAG_RE.sub("", raw)          # <br /> and any stray markup
        line = html.unescape(line).rstrip()  # &nbsp; -> space, &gt; -> >, ...
        if not started:
            if not _DATE_RE.match(line):
                continue
            started = True
        lines.append(line)
    # Drop the page footer that follows the oldest entry's separator.
    ends = [i for i, line in enumerate(lines) if line.startswith(_SEPARATOR)]
    if ends:
        lines = lines[: ends[-1] + 1]
    return lines[:MAX_LINES]


def _wrap_lines(lines, font, max_width):
    """Greedy word wrap measured in pixels; hard-splits words (package
    names, URLs) too long to fit on their own line."""
    wrapped = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        current = ""
        for word in line.split(" "):
            candidate = f"{current} {word}" if current else word
            if font.getlength(candidate) <= max_width:
                current = candidate
                continue
            if current:
                wrapped.append(current)
            while font.getlength(word) > max_width:
                cut = len(word)
                while cut > 1 and font.getlength(word[:cut]) > max_width:
                    cut -= 1
                wrapped.append(word[:cut])
                word = word[cut:]
            current = word
        wrapped.append(current)
    return wrapped


class ChangelogCyberpunkScreen(Screen):
    name = "changelog-cyberpunk"

    def __init__(self, refresh_hours=24):
        self.font = ImageFont.truetype(RETRO_FONT_PATH, 11)
        ascent, descent = self.font.getmetrics()
        self._line_height = ascent + descent
        self._lock = threading.Lock()
        self._lines = []
        self._offset = 0

    def start(self, stop_event, notify_update):
        def updater():
            while not stop_event.is_set():
                fetched = False
                try:
                    page = requests.get(CHANGELOG_URL, timeout=15).text
                    lines = _wrap_lines(_extract_lines(page), self.font, WIDTH - 2)
                    if lines:
                        with self._lock:
                            self._lines = lines
                        fetched = True
                    notify_update()
                except Exception as e:
                    print(f"[changelog-cyberpunk] fetch failed: {e}")
                stop_event.wait(REFETCH_SECONDS if fetched else RETRY_SECONDS)

        threading.Thread(target=updater, daemon=True).start()

        # Scroll ticker: notify_update only marks the display dirty when this
        # screen is current, so the scroll advances only while it's on screen.
        def ticker():
            while not stop_event.is_set():
                notify_update()
                stop_event.wait(SCROLL_SECONDS)

        threading.Thread(target=ticker, daemon=True).start()

    def render(self):
        with self._lock:
            lines = self._lines
        if not lines:
            return None

        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_scanlines(draw)

        max_offset = max(0, len(lines) * self._line_height - HEIGHT)
        self._offset = 0 if self._offset >= max_offset else self._offset + 1

        first = self._offset // self._line_height
        y = -(self._offset % self._line_height)
        for line in lines[first : first + HEIGHT // self._line_height + 1]:
            draw.text((1, y), line, font=self.font, fill=NEON_CYAN)
            y += self._line_height

        return img
