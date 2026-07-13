#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026
#
# SPDX-License-Identifier: MIT
"""
Drives the matrix display, cycling between screens (see screens/) — weather
by default, with a stub stocks screen. Each screen is self-contained (see
screens/base.py for the interface); this script just wires up whichever
screens are listed in main() to the matrix and to the screen-switching
controls.

The weather screen is a variant of weather_fetcher.py for boards other than
the Pi 5, such as the Pi Zero 2 W. The `piomatter` driver used elsewhere in
this repo only
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

$ sudo python matrix_server.py

$ sudo python matrix_server.py --latitude 40.71 --longitude -74.01 --refresh-minutes 5

----------------------------------------------------------------------------
TESTING IN A BROWSER (no panel / no Pi hardware needed)
----------------------------------------------------------------------------
Pass --simulate to render the exact same frames to a browser over WebSocket
instead of the physical panel. This uses matrix_sim.py (keep it next to this
script) and needs the 'websockets' package:

$ pip install websockets
$ python matrix_server.py --simulate --refresh-minutes 1

Then open led-matrix-simulator.html, go to the "Live" tab, and connect to
ws://localhost:8888 (same machine) or ws://<pi-ip>:8888 (from another device).
No sudo needed in simulate mode. Drop --simulate to drive the real panel.

----------------------------------------------------------------------------
SWITCHING SCREENS
----------------------------------------------------------------------------
Spacebar switches screens, but only when this script's stdin is a real
terminal — a process manager like pm2 detaches stdin, so it can't be used
there. The HTTP control server always works instead:

$ curl -X POST http://localhost:8787/next-screen
$ curl http://localhost:8787/screen
"""

import http.server
import signal
import sys
import termios
import threading
import time
import tty

import click

from screens import ScreenManager, StocksScreen, WeatherScreen


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
            print(f"[display] switched to {screens.current.name} screen")


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
                print(f"[display] switched to {screens.current.name} screen")
                self._reply(f"switched to {screens.current.name}")
            else:
                self.send_response(404)
                self.end_headers()

        def do_GET(self):
            if self.path == "/screen":
                self._reply(screens.current.name)
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

    stop_event = threading.Event()
    screens = ScreenManager([
        WeatherScreen(latitude, longitude, refresh_minutes),
        StocksScreen(),
    ])
    screens.start_all(stop_event)

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
                img = screens.current.render()
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
