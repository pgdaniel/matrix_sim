"""Cyberpunk oscilloscope screen: draws the time-domain waveform of desktop
audio from another machine, same source and wire format as
screens/spectrum.py.

Each audio_sender.py process feeds exactly one TCP listener, so this screen
runs its own (default port 8790, separate from spectrum's 8788) — run a
second `audio_sender.py --port 8790` alongside the one already pointed at
the spectrum screen if you want both running at once. See README.md.

Every analysis chunk, the trace is triggered on the first rising
zero-crossing so the waveform holds roughly still frame to frame instead of
sliding sideways with the signal's phase (like a real scope's trigger),
then downsampled to one point per column and drawn as a glowing line. A
rolling peak-amplitude normalization (decaying, floored) keeps quiet and
loud sources both visible, similar in spirit to the spectrum screen's
rolling dB normalization. A couple of seconds without audio data falls back
to a dim "NO SIGNAL".
"""

import socket
import threading
import time

from PIL import Image, ImageDraw, ImageFont

from .base import HEIGHT, Screen, WIDTH
from .cyberpunk_theme import (
    BG_COLOR,
    NEON_CYAN,
    NEON_PINK,
    RETRO_FONT_PATH,
    draw_glow_text,
    draw_scanlines,
)

# numpy does the trigger search / downsampling. It's a hard dependency of
# this screen but not of the display as a whole, and screens/__init__
# imports this module — so a missing numpy must not take down every other
# screen; degrade to an on-panel error message instead.
try:
    import numpy as np
except ImportError:
    np = None

SAMPLE_RATE = 48000          # must match audio_sender.py's parec arguments
CHUNK = 2048                 # frames read per analysis pass (~43 ms at 48 kHz)
BYTES_PER_CHUNK = CHUNK * 2  # s16le mono

SWEEP_SAMPLES = 896          # WIDTH * 14, ~18.7 ms of audio drawn per frame
IDLE_AFTER = 2.0             # seconds without audio data -> "NO SIGNAL"

NORM_DECAY = 0.995           # rolling peak-amplitude falloff per analysis update
NORM_FLOOR = 0.02            # ...but never below this, so silence isn't boosted into noise
GAIN_HEADROOM = 0.85         # fraction of the half-height a full-scale peak reaches

GRID_COLOR = (20, 40, 55)
DIM_CYAN = (0, 70, 75)
DIM_PINK = (70, 0, 45)


class OscopeScreen(Screen):
    name = "oscope"

    def __init__(self, port=8790):
        self.port = port
        self._lock = threading.Lock()
        self._last_data = 0.0  # monotonic time the last chunk was analyzed
        self._font = ImageFont.truetype(RETRO_FONT_PATH, 13)

        if np is not None:
            self._trace = np.full(WIDTH, HEIGHT / 2.0)  # smoothed y per column
            self._norm = NORM_FLOOR

    def start(self, stop_event, notify_update):
        if np is None:
            print("[oscope] numpy is not installed; screen will show an error message")
            print("[oscope] install it with: pip install numpy  (in the venv matrix_server runs from)")
            return

        def watchdog():
            # No audio chunks arriving means no notify_update() calls — so
            # without this, the panel would freeze on the last audio frame
            # forever when the sender goes away. Poke one redraw the moment
            # the idle threshold passes, so "NO SIGNAL" actually appears.
            was_idle = False
            while not stop_event.is_set():
                idle = (time.monotonic() - self._last_data) > IDLE_AFTER
                if idle and not was_idle:
                    notify_update()
                was_idle = idle
                stop_event.wait(0.25)

        threading.Thread(target=watchdog, daemon=True).start()

        def run():
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                srv.bind(("0.0.0.0", self.port))
                srv.listen(1)
            except OSError as e:
                print(f"[oscope] cannot listen on port {self.port}: {e}")
                srv.close()
                return
            srv.settimeout(0.5)  # so the accept loop notices stop_event
            print(f"[oscope] listening for audio on tcp://0.0.0.0:{self.port}")
            while not stop_event.is_set():
                try:
                    conn, addr = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                print(f"[oscope] audio sender connected: {addr[0]}")
                self._read_loop(conn, stop_event, notify_update)
                conn.close()
                print("[oscope] audio sender disconnected")
            srv.close()

        threading.Thread(target=run, daemon=True).start()

    def _read_loop(self, conn, stop_event, notify_update):
        conn.settimeout(1.0)  # so a silent sender doesn't stop us noticing stop_event
        buf = bytearray()
        while not stop_event.is_set():
            try:
                data = conn.recv(16384)
            except socket.timeout:
                continue
            except OSError:
                return
            if not data:
                return
            buf.extend(data)
            # If a backlog somehow builds up, drop the oldest audio: a
            # scope should show "now", not half a second ago.
            if len(buf) > BYTES_PER_CHUNK * 4:
                del buf[:-BYTES_PER_CHUNK]
            while len(buf) >= BYTES_PER_CHUNK:
                chunk = bytes(buf[:BYTES_PER_CHUNK])
                del buf[:BYTES_PER_CHUNK]
                self._analyze(chunk)
                notify_update()

    def _find_trigger(self, samples):
        """Index of the first rising zero-crossing early enough that
        SWEEP_SAMPLES still fit after it, or 0 if there isn't one (e.g.
        near-silence) so the sweep still has something to draw."""
        search_end = len(samples) - SWEEP_SAMPLES
        if search_end <= 0:
            return 0
        window = samples[:search_end]
        crossings = np.nonzero((window[:-1] <= 0) & (window[1:] > 0))[0]
        return int(crossings[0]) + 1 if crossings.size else 0

    def _analyze(self, chunk):
        samples = np.frombuffer(chunk, dtype="<i2").astype(np.float32) * (1.0 / 32768.0)
        start = self._find_trigger(samples)
        sweep = samples[start:start + SWEEP_SAMPLES]

        with self._lock:
            self._last_data = time.monotonic()
            self._norm = max(NORM_FLOOR, max(
                float(np.abs(sweep).max()),
                self._norm * NORM_DECAY,
            ))
            gain = (HEIGHT / 2.0 - 1) * GAIN_HEADROOM / self._norm
            columns = sweep.reshape(WIDTH, SWEEP_SAMPLES // WIDTH).mean(axis=1)
            self._trace = np.clip(HEIGHT / 2.0 - columns * gain, 0, HEIGHT - 1)

    def _draw_message(self, draw, text):
        x0, y0, x1, y1 = self._font.getbbox(text)
        tx = (WIDTH - (x1 - x0)) // 2
        ty = (HEIGHT - (y1 - y0)) // 2 - y0
        draw_glow_text(draw, (tx, ty), text, self._font, fill=DIM_CYAN, shadow=DIM_PINK)

    def render(self):
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)

        if np is None:
            draw_scanlines(draw)
            self._draw_message(draw, "NO NUMPY")
            return img

        with self._lock:
            trace = self._trace.copy()
            idle = (time.monotonic() - self._last_data) > IDLE_AFTER

        if idle:
            draw_scanlines(draw)
            self._draw_message(draw, "NO SIGNAL")
            return img

        draw.line((0, HEIGHT // 2, WIDTH, HEIGHT // 2), fill=GRID_COLOR)
        for x in (WIDTH // 4, WIDTH // 2, 3 * WIDTH // 4):
            draw.line((x, 0, x, HEIGHT), fill=GRID_COLOR)

        points = [(x, float(trace[x])) for x in range(WIDTH)]
        shadow = [(x, min(HEIGHT - 1, y + 1)) for x, y in points]
        draw.line(shadow, fill=NEON_PINK, width=1, joint="curve")
        draw.line(points, fill=NEON_CYAN, width=1, joint="curve")

        draw_scanlines(draw)
        return img
