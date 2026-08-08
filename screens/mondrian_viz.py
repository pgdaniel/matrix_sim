"""Audio-reactive Mondrian screen: a Piet Mondrian composition — black grid
lines dividing the canvas into white panes plus a red, a blue, and a yellow
block — whose divider positions and pane brightness track real bass/mid/
treble energy from desktop audio. Same source and wire format as
screens/spectrum.py and screens/oscope.py, and same layout algorithm as the
`mondrian` pattern in ~/soma-zig's visualizer.zig, ported from its terminal
grid to this panel's 64x32 pixels (one soma-zig grid cell == one pixel here,
so the port is 1:1 with no rescaling).

This is a different screen from screens/mondrian.py, which is generative
(random compositions, no audio) rather than audio-driven — that one keeps
its `mondrian` name; this one is `mondrian-viz`.

Each audio_sender.py process feeds exactly one TCP listener, so this screen
runs its own (default port 8791). See README.md.
"""

import socket
import threading
import time

from PIL import Image, ImageDraw, ImageFont

from .base import FONT_PATH, HEIGHT, Screen, WIDTH

# numpy does the FFT. It's a hard dependency of this screen but not of the
# display as a whole, and screens/__init__ imports this module — so a
# missing numpy must not take down every other screen; degrade to an
# on-panel error message instead.
try:
    import numpy as np
except ImportError:
    np = None

SAMPLE_RATE = 48000          # must match audio_sender.py's parec arguments
CHUNK = 2048                 # frames per FFT (~43 ms of audio at 48 kHz)
BYTES_PER_CHUNK = CHUNK * 2  # s16le mono

LOW_HZ = 50.0
HIGH_HZ = 16000.0
NUM_BANDS = 3                 # bass / mid / treble — one per soma-zig's thirds

GAIN_FLOOR = 1e-4              # ceiling never drops below this, so silence isn't boosted into noise
GAIN_DECAY = 0.97              # rolling-ceiling falloff per analysis update when the peak drops
SMOOTH_SPEED = 0.3             # per-update band-energy smoothing (soma-zig's smoothValues speed)
BRIGHT_THRESHOLD = 0.75        # a band above this energy gets its pane brightened
COLOR_ROTATE_FRAMES = 24       # analysis updates per color rotation (~1s at ~43ms/update)
IDLE_AFTER = 2.0                # seconds without audio data -> "NO SIGNAL"

# Same Mondrian palette as screens/mondrian.py.
WHITE = (245, 245, 240)
BLACK = (10, 10, 10)
RED = (221, 1, 0)
BLUE = (20, 30, 190)
YELLOW = (250, 201, 1)
_PRIMARIES = [RED, BLUE, YELLOW]


def _brighten(color, t=0.35):
    return tuple(int(c + (255 - c) * t) for c in color)


def _clamp(x, lo, hi):
    return max(lo, min(x, hi))


class MondrianVizScreen(Screen):
    name = "mondrian-viz"

    def __init__(self, port=8791):
        self.port = port
        self._lock = threading.Lock()
        self._last_data = 0.0  # monotonic time the last chunk was analyzed
        self._font = ImageFont.truetype(FONT_PATH, 10)

        if np is not None:
            self._values = np.zeros(NUM_BANDS)  # smoothed band energy, 0..1
            self._gain = 0.02                    # rolling ceiling for auto-gain
            self._frame_count = 0
            self._window = np.hanning(CHUNK).astype(np.float32)
            # Divide rfft magnitudes by this so a full-scale sine peaks at ~1.0.
            self._mag_scale = self._window.sum() / 2.0
            freqs = np.fft.rfftfreq(CHUNK, 1.0 / SAMPLE_RATE)
            edges = np.geomspace(LOW_HZ, HIGH_HZ, NUM_BANDS + 1)
            bins = np.searchsorted(freqs, edges)
            self._bands = [
                (int(bins[i]), int(max(bins[i + 1], bins[i] + 1)))  # >= 1 bin each
                for i in range(NUM_BANDS)
            ]

    def start(self, stop_event, notify_update):
        if np is None:
            print("[mondrian-viz] numpy is not installed; screen will show an error message")
            print("[mondrian-viz] install it with: pip install numpy  (in the venv matrix_server runs from)")
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
                print(f"[mondrian-viz] cannot listen on port {self.port}: {e}")
                srv.close()
                return
            srv.settimeout(0.5)  # so the accept loop notices stop_event
            print(f"[mondrian-viz] listening for audio on tcp://0.0.0.0:{self.port}")
            while not stop_event.is_set():
                try:
                    conn, addr = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                print(f"[mondrian-viz] audio sender connected: {addr[0]}")
                self._read_loop(conn, stop_event, notify_update)
                conn.close()
                print("[mondrian-viz] audio sender disconnected")
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
        band_mags = np.array([mag[lo:hi].mean() for lo, hi in self._bands])

        with self._lock:
            self._last_data = time.monotonic()
            peak = float(band_mags.max())
            # Auto-gain: track a ceiling that snaps up fast on louder peaks
            # and decays slowly, so quiet and loud sources both fill the
            # composition's range of motion.
            self._gain = peak if peak > self._gain else self._gain * GAIN_DECAY + peak * (1 - GAIN_DECAY)
            ceiling = max(self._gain, GAIN_FLOOR)
            # sqrt gives a perceptual boost to low-level detail.
            targets = np.clip(np.sqrt(band_mags / ceiling), 0.0, 1.0)
            self._values += (targets - self._values) * SMOOTH_SPEED
            self._frame_count += 1

    def _draw_message(self, draw, text):
        x0, y0, x1, y1 = self._font.getbbox(text)
        tx = (WIDTH - (x1 - x0)) // 2
        ty = (HEIGHT - (y1 - y0)) // 2 - y0
        draw.text((tx, ty), text, font=self._font, fill=BLACK)

    def _composition(self, a0, a1, a2, rot):
        """Port of soma-zig visualizer.zig's renderMondrian: two full-height
        vertical dividers and three horizontal dividers (one per band, two
        in the middle band) positioned by band energy, panes filled
        red/blue/yellow (rotating with `rot`) and brightened above
        BRIGHT_THRESHOLD, rest left white."""
        w, h = WIDTH, HEIGHT
        img = Image.new("RGB", (w, h), WHITE)
        draw = ImageDraw.Draw(img)

        v1 = _clamp(int(w * (0.22 + 0.12 * a0)), 2, w - 5)
        v2 = _clamp(int(w * (0.58 + 0.14 * a2)), v1 + 2, w - 3)
        hA = _clamp(int(h * (0.55 + 0.25 * a0)), 1, h - 2)
        hB1 = _clamp(int(h * (0.30 + 0.15 * a1)), 1, h - 3)
        hB2 = _clamp(int(h * (0.68 + 0.15 * a1)), hB1 + 1, h - 2)
        hC = _clamp(int(h * (0.75 - 0.25 * a2)), 1, h - 2)

        def primary(base, energy):
            color = _PRIMARIES[(base + rot) % 3]
            return _brighten(color) if energy > BRIGHT_THRESHOLD else color

        # Composition II homage: big block bottom-left, small block in the
        # middle band, big block top-right, rest white.
        draw.rectangle((0, hA + 1, v1 - 1, h - 1), fill=primary(1, a0))
        draw.rectangle((v1 + 1, hB1 + 1, v2 - 1, hB2 - 1), fill=primary(2, a1))
        draw.rectangle((v2 + 1, 0, w - 1, hC - 1), fill=primary(0, a2))

        draw.line((v1, 0, v1, h - 1), fill=BLACK)
        draw.line((v2, 0, v2, h - 1), fill=BLACK)
        draw.line((0, hA, v1 - 1, hA), fill=BLACK)
        draw.line((v1 + 1, hB1, v2 - 1, hB1), fill=BLACK)
        draw.line((v1 + 1, hB2, v2 - 1, hB2), fill=BLACK)
        draw.line((v2 + 1, hC, w - 1, hC), fill=BLACK)

        return img

    def render(self):
        if np is None:
            img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
            self._draw_message(ImageDraw.Draw(img), "NO NUMPY")
            return img

        with self._lock:
            values = self._values.copy()
            rot = (self._frame_count // COLOR_ROTATE_FRAMES) % 3
            idle = (time.monotonic() - self._last_data) > IDLE_AFTER

        if idle:
            img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=BLACK)
            self._draw_message(draw, "NO SIGNAL")
            return img

        return self._composition(values[0], values[1], values[2], int(rot))
