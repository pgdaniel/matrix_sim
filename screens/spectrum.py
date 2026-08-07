"""Cyberpunk spectrum analyzer screen: 16 log-spaced frequency bars driven
by desktop audio from another machine.

The Pi has no audio input of its own, so the PCM stream comes in over the
network: audio_sender.py on another computer captures its desktop audio (the
PipeWire/PulseAudio monitor source) and forwards raw s16le mono PCM at
48 kHz to this screen's TCP listener (default port 8788). See README.md.

Bars are normalized against a global slowly-decaying rolling peak, so the
display adapts to quiet and loud songs alike, with a per-band treble lift so
highs aren't drowned out by bass. A couple of seconds without audio data
(no sender connected, capture died) falls back to a dim "NO SIGNAL".
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
    NEON_YELLOW,
    RETRO_FONT_PATH,
    draw_glow_text,
    draw_scanlines,
)

# numpy does the FFT. It's a hard dependency of this screen but not of the
# display as a whole, and screens/__init__ imports this module — so a
# missing numpy must not take down every other screen; degrade to an
# on-panel error message instead.
try:
    import numpy as np
except ImportError:
    np = None

SAMPLE_RATE = 48000        # must match audio_sender.py's parec arguments
CHUNK = 2048               # frames per FFT (~43 ms of audio at 48 kHz)
BYTES_PER_CHUNK = CHUNK * 2  # s16le mono

NUM_BARS = 16
BAR_WIDTH = 3
BAR_GAP = 1                # NUM_BARS * (BAR_WIDTH + BAR_GAP) == WIDTH
LOW_HZ = 50.0
HIGH_HZ = 16000.0

RANGE_DB = 45.0            # a band this many dB below the rolling peak reads as zero
NORM_DECAY_DB = 1.0        # rolling-peak falloff per analysis update (~23/s)
NORM_FLOOR_DB = -70.0      # ...but never below this, so silence isn't boosted into view
EQ_BOOST_DB = 24.0         # treble lift: top band gets this many extra dB, ramped linearly
LEVEL_DECAY = 0.72         # per-update bar falloff (attack is instant)
CAP_GRAVITY = 0.12         # peak-cap acceleration, px/update^2
IDLE_AFTER = 2.0           # seconds without audio data -> "NO SIGNAL"

DIM_CYAN = (0, 70, 75)
DIM_PINK = (70, 0, 45)


class SpectrumScreen(Screen):
    name = "spectrum"

    def __init__(self, port=8788):
        self.port = port
        self._lock = threading.Lock()
        self._last_data = 0.0  # monotonic time the last chunk was analyzed
        self._font = ImageFont.truetype(RETRO_FONT_PATH, 13)

        if np is not None:
            self._levels = np.zeros(NUM_BARS)    # smoothed bar heights, 0..1
            self._caps = np.zeros(NUM_BARS)      # peak-cap positions, in pixels
            self._cap_vel = np.zeros(NUM_BARS)
            self._norm_db = NORM_FLOOR_DB
            self._window = np.hanning(CHUNK).astype(np.float32)
            # Divide rfft magnitudes by this so a full-scale sine peaks at 0 dB.
            self._mag_scale = self._window.sum() / 2.0
            self._eq_boost = np.linspace(0.0, EQ_BOOST_DB, NUM_BARS)
            # Precompute which rfft bins make up each log-spaced band.
            freqs = np.fft.rfftfreq(CHUNK, 1.0 / SAMPLE_RATE)
            edges = np.geomspace(LOW_HZ, HIGH_HZ, NUM_BARS + 1)
            bins = np.searchsorted(freqs, edges)
            self._bands = [
                (int(bins[i]), int(max(bins[i + 1], bins[i] + 1)))  # >= 1 bin each
                for i in range(NUM_BARS)
            ]

        # Bar gradient, cyan at the bottom -> pink at the top; render() pastes
        # the bottom h rows of it for a bar h pixels tall.
        self._bar_grad = Image.new("RGB", (BAR_WIDTH, HEIGHT))
        grad_draw = ImageDraw.Draw(self._bar_grad)
        for y in range(HEIGHT):
            t = (HEIGHT - 1 - y) / (HEIGHT - 1)
            color = tuple(
                int(NEON_CYAN[c] + (NEON_PINK[c] - NEON_CYAN[c]) * t)
                for c in range(3)
            )
            grad_draw.line((0, y, BAR_WIDTH - 1, y), fill=color)

    def start(self, stop_event, notify_update):
        if np is None:
            print("[spectrum] numpy is not installed; screen will show an error message")
            print("[spectrum] install it with: pip install numpy  (in the venv matrix_server runs from)")
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
                print(f"[spectrum] cannot listen on port {self.port}: {e}")
                srv.close()
                return
            srv.settimeout(0.5)  # so the accept loop notices stop_event
            print(f"[spectrum] listening for audio on tcp://0.0.0.0:{self.port}")
            while not stop_event.is_set():
                try:
                    conn, addr = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                print(f"[spectrum] audio sender connected: {addr[0]}")
                self._read_loop(conn, stop_event, notify_update)
                conn.close()
                print("[spectrum] audio sender disconnected")
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
            # visualizer should show "now", not half a second ago.
            if len(buf) > BYTES_PER_CHUNK * 4:
                del buf[:-BYTES_PER_CHUNK]
            while len(buf) >= BYTES_PER_CHUNK:
                chunk = bytes(buf[:BYTES_PER_CHUNK])
                del buf[:BYTES_PER_CHUNK]
                self._analyze(chunk)
                notify_update()

    def _analyze(self, chunk):
        samples = np.frombuffer(chunk, dtype="<i2").astype(np.float32) * (1.0 / 32768.0)
        mag = np.abs(np.fft.rfft(samples * self._window)) / self._mag_scale
        db = np.array([
            20.0 * np.log10(mag[lo:hi].mean() + 1e-9)
            for lo, hi in self._bands
        ]) + self._eq_boost
        with self._lock:
            self._last_data = time.monotonic()
            self._norm_db = max(
                float(db.max()),
                max(self._norm_db - NORM_DECAY_DB, NORM_FLOOR_DB),
            )
            levels = np.clip((db - (self._norm_db - RANGE_DB)) / RANGE_DB, 0.0, 1.0)
            self._levels = np.maximum(levels, self._levels * LEVEL_DECAY)

            px = self._levels * (HEIGHT - 1)
            rising = px >= self._caps
            self._caps[rising] = px[rising]
            self._cap_vel[rising] = 0.0
            self._cap_vel[~rising] += CAP_GRAVITY
            self._caps[~rising] = np.maximum(0.0, self._caps[~rising] - self._cap_vel[~rising])

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
            levels = self._levels.copy()
            caps = self._caps.copy()
            idle = (time.monotonic() - self._last_data) > IDLE_AFTER

        if idle:
            draw_scanlines(draw)
            self._draw_message(draw, "NO SIGNAL")
            return img

        for i in range(NUM_BARS):
            x0 = i * (BAR_WIDTH + BAR_GAP)
            h = int(levels[i] * HEIGHT)
            if h > 0:
                img.paste(self._bar_grad.crop((0, HEIGHT - h, BAR_WIDTH, HEIGHT)), (x0, HEIGHT - h))
            cap = int(caps[i])
            if cap > 0:
                y = HEIGHT - 1 - cap
                draw.line((x0, y, x0 + BAR_WIDTH - 1, y), fill=NEON_YELLOW)

        draw_scanlines(draw)
        return img
