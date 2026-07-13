#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026
#
# SPDX-License-Identifier: MIT
"""
Fetch the current weather and display it on the matrix as a small icon
(sun, cloud, rain, snow, storm, fog) next to the temperature in Fahrenheit.

This is a variant of weather_fetcher.py for boards other than the Pi 5, such
as the Pi Zero 2 W. The `piomatter` driver used elsewhere in this repo only
works on a Pi 5 (it drives the panel through the RP1 chip's PIO block, which
other boards don't have). Here the panel is driven instead with Henner
Zeller's rpi-rgb-led-matrix library, the standard choice for a Zero/3/4 with
an Adafruit RGB Matrix Bonnet or HAT.

The `rgbmatrix` Python bindings aren't on PyPI; install them with Adafruit's
installer script (choose the "Python" option when prompted):

$ curl https://raw.githubusercontent.com/adafruit/Raspberry-Pi-Installer-Scripts/main/rgb-matrix.sh > rgb-matrix.sh
$ sudo bash rgb-matrix.sh

Also requires the `requests` and `click` libraries.

A Pi Zero 2 W is not fast enough to drive the panel and do other work at the
same time without flicker, so run this with `sudo` and nothing else demanding
running in the background.

Run like this:

$ sudo python weather_fetcher_pizero2w.py

$ sudo python weather_fetcher_pizero2w.py --latitude 40.71 --longitude -74.01 --refresh-minutes 5

----------------------------------------------------------------------------
TESTING IN A BROWSER (no panel / no Pi hardware needed)
----------------------------------------------------------------------------
Pass --simulate to render the exact same frames to a browser over WebSocket
instead of the physical panel. This uses matrix_sim.py (keep it next to this
script) and needs the 'websockets' package:

$ pip install websockets
$ python weather_fetcher_pizero2w.py --simulate --refresh-minutes 1

Then open led-matrix-simulator.html, go to the "Live" tab, and connect to
ws://localhost:8888 (same machine) or ws://<pi-ip>:8888 (from another device).
No sudo needed in simulate mode. Drop --simulate to drive the real panel.
"""

import http.server
import math
import signal
import sys
import termios
import threading
import time
import tty

import click
import requests
from PIL import Image, ImageDraw, ImageFont

width = 64
height = 32

font = ImageFont.truetype("LindenHill-webfont.ttf", 16)

SUN_COLOR = (255, 190, 0)
CLOUD_COLOR = (190, 190, 200)
DARK_CLOUD_COLOR = (110, 110, 125)
RAIN_COLOR = (60, 140, 255)
SNOW_COLOR = (255, 255, 255)
BOLT_COLOR = (255, 225, 0)
FOG_COLOR = (150, 150, 160)
TEXT_COLOR = (255, 255, 255)

# WMO weather codes: https://open-meteo.com/en/docs
_CODE_TO_ICON = {
    0: "sun",
    1: "partly_cloudy", 2: "partly_cloudy",
    3: "cloudy",
    45: "fog", 48: "fog",
    51: "rain", 53: "rain", 55: "rain", 56: "rain", 57: "rain",
    61: "rain", 63: "rain", 65: "rain", 66: "rain", 67: "rain",
    80: "rain", 81: "rain", 82: "rain",
    71: "snow", 73: "snow", 75: "snow", 77: "snow", 85: "snow", 86: "snow",
    95: "storm", 96: "storm", 99: "storm",
}


def icon_for_code(code):
    return _CODE_TO_ICON.get(code, "cloudy")


def get_location():
    try:
        resp = requests.get("http://ip-api.com/json/", timeout=5).json()
        return resp["lat"], resp["lon"], resp.get("city", "")
    except Exception:
        # Fallback if geolocation fails: New York City
        return 40.7128, -74.0060, "New York"


def get_weather(lat, lon):
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code",
            "temperature_unit": "fahrenheit",
        },
        timeout=10,
    ).json()
    current = resp["current"]
    return current["temperature_2m"], icon_for_code(current["weather_code"])


def draw_sun(draw, cx, cy, r):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=SUN_COLOR)
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        x1 = cx + (r + 2) * math.cos(rad)
        y1 = cy + (r + 2) * math.sin(rad)
        x2 = cx + (r + 5) * math.cos(rad)
        y2 = cy + (r + 5) * math.sin(rad)
        draw.line((x1, y1, x2, y2), fill=SUN_COLOR, width=1)


def draw_cloud(draw, x0, y0, x1, y1, color):
    w = x1 - x0
    h = y1 - y0
    draw.rectangle((x0, y0 + h * 0.45, x1, y1), fill=color)
    draw.ellipse((x0, y0 + h * 0.10, x0 + w * 0.55, y0 + h * 0.70), fill=color)
    draw.ellipse((x0 + w * 0.35, y0, x0 + w * 0.95, y0 + h * 0.60), fill=color)
    draw.ellipse((x0 + w * 0.10, y0 + h * 0.25, x0 + w * 0.70, y0 + h * 0.80), fill=color)


def draw_icon(draw, kind, x0, y0, x1, y1):
    w = x1 - x0
    h = y1 - y0
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2

    if kind == "sun":
        draw_sun(draw, cx, cy, min(w, h) / 2 - 5)
    elif kind == "partly_cloudy":
        draw_sun(draw, x0 + w * 0.35, y0 + h * 0.30, min(w, h) / 6)
        draw_cloud(draw, x0 + w * 0.05, y0 + h * 0.35, x1, y1, CLOUD_COLOR)
    elif kind == "cloudy":
        draw_cloud(draw, x0, y0 + h * 0.10, x1, y1, DARK_CLOUD_COLOR)
    elif kind == "fog":
        step = max(2, int(h // 5))
        for yy in range(int(y0 + h * 0.15), int(y1), step):
            draw.line((x0, yy, x1, yy), fill=FOG_COLOR, width=2)
    elif kind == "rain":
        draw_cloud(draw, x0, y0, x1, y0 + h * 0.65, DARK_CLOUD_COLOR)
        for i in range(3):
            dx = x0 + w * (0.2 + 0.3 * i)
            draw.line((dx, y0 + h * 0.75, dx - 2, y1), fill=RAIN_COLOR, width=2)
    elif kind == "snow":
        draw_cloud(draw, x0, y0, x1, y0 + h * 0.60, DARK_CLOUD_COLOR)
        for i in range(3):
            dx = x0 + w * (0.2 + 0.3 * i)
            dy = y0 + h * 0.85
            draw.line((dx - 2, dy, dx + 2, dy), fill=SNOW_COLOR, width=1)
            draw.line((dx, dy - 2, dx, dy + 2), fill=SNOW_COLOR, width=1)
    elif kind == "storm":
        draw_cloud(draw, x0, y0, x1, y0 + h * 0.60, DARK_CLOUD_COLOR)
        draw.polygon(
            [(cx + 2, y0 + h * 0.55), (cx - 4, y0 + h * 0.82),
             (cx, y0 + h * 0.82), (cx - 3, y1)],
            fill=BOLT_COLOR,
        )


def build_frame(temp_f, icon_kind):
    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    icon_size = height
    draw_icon(draw, icon_kind, 1, 0, icon_size - 1, icon_size)

    text = f"{round(temp_f)}F"
    x0, y0, x1, y1 = font.getbbox(text)
    tw, th = x1 - x0, y1 - y0
    tx = icon_size + max(0, (width - icon_size - tw) // 2)
    ty = (height - th) // 2 - y0
    draw.text((tx, ty), text, font=font, fill=TEXT_COLOR)

    return img


stocks_title_font = ImageFont.truetype("LindenHill-webfont.ttf", 13)


def build_stocks_frame():
    """Stub for the stocks screen — replace with a real quote fetch later."""
    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    title = "STOCKS"
    x0, y0, x1, y1 = stocks_title_font.getbbox(title)
    tw, th = x1 - x0, y1 - y0
    draw.text(((width - tw) // 2, height // 2 - th - 2 - y0), title, font=stocks_title_font, fill=TEXT_COLOR)

    subtitle = "SOON"
    small_font = ImageFont.load_default()
    sx0, sy0, sx1, sy1 = small_font.getbbox(subtitle)
    sw = sx1 - sx0
    draw.text(((width - sw) // 2, height // 2 + 4), subtitle, font=small_font, fill=DARK_CLOUD_COLOR)

    return img


SCREENS = ["weather", "stocks"]


class ScreenManager:
    """Tracks which screen is active and whether it needs a redraw."""
    def __init__(self):
        self._lock = threading.Lock()
        self._index = 0
        self.dirty = threading.Event()
        self.dirty.set()

    @property
    def current(self):
        with self._lock:
            return SCREENS[self._index]

    def next_screen(self):
        with self._lock:
            self._index = (self._index + 1) % len(SCREENS)
        self.dirty.set()


def keyboard_listener(screens, stop_event):
    """Reads single keypresses from stdin; spacebar advances to the next screen.

    Assumes stdin has already been put into cbreak mode by the caller. Only
    useful when running directly in a terminal — a process manager like pm2
    detaches stdin, so use the HTTP control server (below) in that case.
    """
    while not stop_event.is_set():
        ch = sys.stdin.read(1)
        if ch == " ":
            screens.next_screen()
            print(f"[display] switched to {screens.current} screen")


def make_control_server(screens, port):
    """A tiny HTTP server for switching screens without a terminal — the
    mechanism a pm2-managed (or otherwise headless) process should use.

        curl -X POST http://<host>:<port>/next-screen
        curl http://<host>:<port>/screen
    """
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # keep stdout limited to display-related logging

        def _reply(self, body):
            data = (body + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path == "/next-screen":
                screens.next_screen()
                print(f"[display] switched to {screens.current} screen")
                self._reply(f"switched to {screens.current}")
            else:
                self.send_response(404)
                self.end_headers()

        def do_GET(self):
            if self.path == "/screen":
                self._reply(screens.current)
            else:
                self.send_response(404)
                self.end_headers()

    return http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)


@click.command
@click.option("--latitude", type=float, default=None, help="Latitude to fetch weather for (auto-detected from IP if omitted)")
@click.option("--longitude", type=float, default=None, help="Longitude to fetch weather for (auto-detected from IP if omitted)")
@click.option("--refresh-minutes", type=int, default=10, help="How often to re-fetch the weather")
@click.option("--brightness", type=click.IntRange(min=1, max=100), default=100, help="The brightness of the matrix, from 1 to 100")
@click.option("--rows", type=int, default=32, help="Number of rows in the matrix (panel height)")
@click.option("--cols", type=int, default=64, help="Number of columns in the matrix (panel width)")
@click.option("--chain-length", type=int, default=1, help="Number of daisy-chained panels")
@click.option("--parallel", type=int, default=1, help="Number of parallel chains (needs a multi-panel adapter)")
@click.option("--hardware-mapping", default="adafruit-hat", help="Hardware mapping, e.g. adafruit-hat, adafruit-hat-pwm, regular")
@click.option("--gpio-slowdown", type=int, default=2, help="GPIO slowdown factor; increase if you see flickering/glitching")
@click.option("--simulate", is_flag=True, default=False, help="Render to a browser via WebSocket instead of the physical panel (needs matrix_sim.py + `pip install websockets`)")
@click.option("--sim-port", type=int, default=8888, help="WebSocket port for --simulate mode")
@click.option("--control-port", type=int, default=8787, help="HTTP port for screen-switching control (POST /next-screen, GET /screen) — the mechanism to use under pm2, where stdin is detached")
def main(latitude, longitude, refresh_minutes, brightness, rows, cols, chain_length, parallel, hardware_mapping, gpio_slowdown, simulate, sim_port, control_port):
    # Choose the real hardware driver or the browser simulator based on the flag.
    # Both expose the same RGBMatrix / RGBMatrixOptions API, so nothing below
    # this point needs to change.
    if simulate:
        from matrix_sim import RGBMatrix, RGBMatrixOptions
    else:
        from rgbmatrix import RGBMatrix, RGBMatrixOptions

    if latitude is None or longitude is None:
        latitude, longitude, city = get_location()
    else:
        city = f"{latitude:.2f}, {longitude:.2f}"
    print(f"Location: {city} ({latitude:.4f}, {longitude:.4f})")

    options = RGBMatrixOptions()
    options.rows = rows
    options.cols = cols
    options.chain_length = chain_length
    options.parallel = parallel
    options.hardware_mapping = hardware_mapping
    options.gpio_slowdown = gpio_slowdown
    options.brightness = brightness
    # sim_port is only meaningful to matrix_sim. The real (Cython) options
    # struct may reject unknown attributes, so only set it when simulating.
    if simulate:
        options.sim_port = sim_port

    matrix = RGBMatrix(options=options)
    canvas = matrix.CreateFrameCanvas()

    screens = ScreenManager()
    stop_event = threading.Event()
    weather_lock = threading.Lock()
    weather_state = {"temp_f": None, "icon": None}

    def weather_updater():
        while not stop_event.is_set():
            try:
                temp_f, icon_kind = get_weather(latitude, longitude)
                print(f"{city}: {temp_f:.0f}F, {icon_kind}")
                with weather_lock:
                    weather_state["temp_f"] = temp_f
                    weather_state["icon"] = icon_kind
                if screens.current == "weather":
                    screens.dirty.set()
            except Exception as e:
                print(f"Weather fetch failed: {e}")
            stop_event.wait(max(1, refresh_minutes) * 60)

    threading.Thread(target=weather_updater, daemon=True).start()

    control_server = make_control_server(screens, control_port)
    threading.Thread(target=control_server.serve_forever, daemon=True).start()
    print(f"Control server on http://0.0.0.0:{control_port} - POST /next-screen to switch screens")

    # Put stdin into cbreak mode so the keyboard listener can read single
    # keypresses (spacebar) without waiting for Enter. Only possible when
    # stdin is an actual terminal (not piped input, and not a process manager
    # like pm2, which detaches stdin) — use the control server above instead
    # when this isn't available.
    stdin_is_tty = sys.stdin.isatty()
    if stdin_is_tty:
        stdin_fd = sys.stdin.fileno()
        old_term_settings = termios.tcgetattr(stdin_fd)
        tty.setcbreak(stdin_fd)
        threading.Thread(target=keyboard_listener, args=(screens, stop_event), daemon=True).start()
        print("SPACE to switch screens, Ctrl-C to exit")
    else:
        print("stdin is not a terminal; use the control server to switch screens. Ctrl-C to exit")

    # pm2 (and most process managers) stop a process with SIGTERM, not
    # Ctrl-C, so a shutdown must be handled the same way as KeyboardInterrupt.
    signal.signal(signal.SIGTERM, lambda signum, frame: stop_event.set())
    signal.signal(signal.SIGINT, lambda signum, frame: stop_event.set())

    try:
        while not stop_event.is_set():
            if screens.dirty.is_set():
                screens.dirty.clear()
                current = screens.current
                if current == "stocks":
                    img = build_stocks_frame()
                else:
                    with weather_lock:
                        temp_f = weather_state["temp_f"]
                        icon_kind = weather_state["icon"]
                    img = build_frame(temp_f, icon_kind) if temp_f is not None else None
                if img is not None:
                    canvas.SetImage(img.convert("RGB"))
                    canvas = matrix.SwapOnVSync(canvas)
            time.sleep(0.05)
    finally:
        stop_event.set()
        control_server.shutdown()
        if stdin_is_tty:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_term_settings)


if __name__ == "__main__":
    main()
