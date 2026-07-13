"""
matrix_sim.py — a drop-in stand-in for the `rgbmatrix` library that streams
the framebuffer to a browser over WebSocket instead of a physical HUB75 panel.

Goal: run the EXACT same display code against a browser first, then flip a flag
to drive the real panel. Your script keeps calling SetImage() / SwapOnVSync()
as usual.

--------------------------------------------------------------------------
USAGE — minimal change to your script
--------------------------------------------------------------------------

At the top of matrix_server.py, swap the import based on a flag:

    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulate", action="store_true",
                    help="Render to a browser via WebSocket instead of the panel")
    ap.add_argument("--sim-port", type=int, default=8888)
    # ... your other args (--refresh-minutes etc.) ...
    args = ap.parse_args()

    if args.simulate:
        from matrix_sim import RGBMatrix, RGBMatrixOptions
    else:
        from rgbmatrix import RGBMatrix, RGBMatrixOptions

Everything else stays the same:

    options = RGBMatrixOptions()
    options.rows = 32
    options.cols = 64
    options.chain_length = 1
    matrix = RGBMatrix(options=options)
    ...
    matrix.SetImage(image)                    # works
    # or:
    canvas = matrix.CreateFrameCanvas()
    canvas.SetImage(image)
    canvas = matrix.SwapOnVSync(canvas)       # works

Then test:
    python matrix_server.py --simulate --refresh-minutes=1
Open led-matrix-simulator.html in a browser, point it at ws://<pi-ip>:8888
(or ws://localhost:8888 if testing on a desktop).

Deploy for real: drop --simulate. No other change.

--------------------------------------------------------------------------
Dependency (only needed in simulate mode):
    pip install websockets pillow
--------------------------------------------------------------------------
"""

import asyncio
import base64
import json
import threading
import time

try:
    import websockets
except ImportError:
    raise SystemExit(
        "matrix_sim needs the 'websockets' package for --simulate mode:\n"
        "    pip install websockets pillow"
    )


class RGBMatrixOptions:
    """Mimics rgbmatrix.RGBMatrixOptions — accepts the same attributes, ignores
    the hardware-only ones."""
    def __init__(self):
        self.rows = 32
        self.cols = 64
        self.chain_length = 1
        self.parallel = 1
        self.brightness = 100
        self.pwm_bits = 11
        self.pwm_lsb_nanoseconds = 130
        self.gpio_slowdown = 1
        self.hardware_mapping = "regular"
        self.led_rgb_sequence = "RGB"
        self.multiplexing = 0
        self.row_address_type = 0
        self.disable_hardware_pulsing = False
        self.show_refresh_rate = False
        self.pixel_mapper_config = ""
        self.panel_type = ""
        self.limit_refresh_rate_hz = 0

    # tolerate any other attribute the real options struct has
    def __setattr__(self, k, v):
        object.__setattr__(self, k, v)


class _FrameBroadcaster:
    """Runs a WebSocket server in a background thread and pushes the latest
    frame to all connected browsers."""
    def __init__(self, width, height, port, brightness):
        self.width = width
        self.height = height
        self.port = port
        self.brightness = max(1, min(100, brightness)) / 100.0
        self._clients = set()
        self._latest = None          # last frame as base64 RGB bytes
        self._loop = None
        self._lock = threading.Lock()
        self._frame_count = 0
        self._t0 = time.time()

        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        # give the server a beat to come up
        time.sleep(0.3)
        print(f"[matrix_sim] WebSocket server on ws://0.0.0.0:{self.port}")
        print(f"[matrix_sim] Open led-matrix-simulator.html and connect to it.")

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def handler(ws):
            self._clients.add(ws)
            # send geometry + any frame we already have
            await ws.send(json.dumps({
                "type": "hello", "w": self.width, "h": self.height
            }))
            if self._latest is not None:
                await ws.send(self._latest)
            try:
                async for _ in ws:      # ignore inbound msgs
                    pass
            finally:
                self._clients.discard(ws)

        async def main():
            async with websockets.serve(handler, "0.0.0.0", self.port,
                                        max_size=None):
                await asyncio.Future()   # run forever

        try:
            self._loop.run_until_complete(main())
        except Exception as e:
            print(f"[matrix_sim] server error: {e}")

    def push(self, rgb_bytes):
        """rgb_bytes: raw R,G,B,R,G,B... length = w*h*3."""
        # apply brightness scaling so sim roughly matches --led-brightness
        if self.brightness < 1.0:
            b = self.brightness
            rgb_bytes = bytes(int(v * b) for v in rgb_bytes)

        msg = json.dumps({
            "type": "frame",
            "w": self.width,
            "h": self.height,
            "data": base64.b64encode(rgb_bytes).decode("ascii"),
        })
        self._latest = msg
        self._frame_count += 1

        if self._loop is None:
            return

        async def _send():
            dead = []
            for ws in list(self._clients):
                try:
                    await ws.send(msg)
                except Exception:
                    dead.append(ws)
            for d in dead:
                self._clients.discard(d)

        try:
            asyncio.run_coroutine_threadsafe(_send(), self._loop)
        except Exception:
            pass


def _image_to_rgb_bytes(image, w, h):
    """Convert a PIL image into a flat RGB byte string sized w*h*3,
    cropping/padding from the top-left as the real library does."""
    from PIL import Image as _PILImage
    img = image.convert("RGB")
    # rgbmatrix draws the image at its native size from top-left; match that
    if img.size != (w, h):
        base = _PILImage.new("RGB", (w, h), (0, 0, 0))
        base.paste(img, (0, 0))   # crops if larger, pads if smaller
        img = base
    return img.tobytes()


class _Canvas:
    """Off-screen canvas returned by CreateFrameCanvas(). Buffers an image
    until SwapOnVSync makes it live."""
    def __init__(self, matrix):
        self._matrix = matrix
        self._pending = None

    def SetImage(self, image, offset_x=0, offset_y=0, *args, **kwargs):
        self._pending = image

    def SetPixel(self, x, y, r, g, b):
        self._matrix._set_pixel_on(self, x, y, r, g, b)

    def Clear(self):
        self._pending = None
        self._matrix._clear_canvas(self)

    def Fill(self, r, g, b):
        self._matrix._fill_canvas(self, r, g, b)


class RGBMatrix:
    """Drop-in for rgbmatrix.RGBMatrix, rendering to a browser."""
    def __init__(self, options=None, **kwargs):
        opts = options or RGBMatrixOptions()
        self.width = opts.cols * getattr(opts, "chain_length", 1)
        self.height = opts.rows * getattr(opts, "parallel", 1)
        port = kwargs.get("sim_port", getattr(opts, "sim_port", 8888))
        self._bcast = _FrameBroadcaster(
            self.width, self.height, port, getattr(opts, "brightness", 100)
        )
        # direct-draw framebuffer for SetPixel usage
        self._fb = bytearray(self.width * self.height * 3)
        # per-canvas scratch buffers for SetPixel-on-canvas
        self._canvas_fb = {}

    # ---- direct API (matrix.SetImage / SetPixel) ----
    def SetImage(self, image, offset_x=0, offset_y=0, *args, **kwargs):
        self._bcast.push(_image_to_rgb_bytes(image, self.width, self.height))

    def SetPixel(self, x, y, r, g, b):
        if 0 <= x < self.width and 0 <= y < self.height:
            i = (y * self.width + x) * 3
            self._fb[i:i+3] = bytes((r & 255, g & 255, b & 255))
            self._bcast.push(bytes(self._fb))

    def Clear(self):
        self._fb = bytearray(self.width * self.height * 3)
        self._bcast.push(bytes(self._fb))

    def Fill(self, r, g, b):
        px = bytes((r & 255, g & 255, b & 255))
        self._fb = bytearray(px * (self.width * self.height))
        self._bcast.push(bytes(self._fb))

    @property
    def brightness(self):
        return int(self._bcast.brightness * 100)

    @brightness.setter
    def brightness(self, v):
        self._bcast.brightness = max(1, min(100, v)) / 100.0

    # ---- double-buffered API (CreateFrameCanvas / SwapOnVSync) ----
    def CreateFrameCanvas(self):
        return _Canvas(self)

    def SwapOnVSync(self, canvas):
        if canvas._pending is not None:
            self._bcast.push(
                _image_to_rgb_bytes(canvas._pending, self.width, self.height)
            )
        elif id(canvas) in self._canvas_fb:
            self._bcast.push(bytes(self._canvas_fb[id(canvas)]))
        # real lib returns a fresh canvas to draw the next frame into
        return _Canvas(self)

    # helpers for SetPixel-on-canvas
    def _buf_for(self, canvas):
        return self._canvas_fb.setdefault(
            id(canvas), bytearray(self.width * self.height * 3)
        )

    def _set_pixel_on(self, canvas, x, y, r, g, b):
        if 0 <= x < self.width and 0 <= y < self.height:
            buf = self._buf_for(canvas)
            i = (y * self.width + x) * 3
            buf[i:i+3] = bytes((r & 255, g & 255, b & 255))

    def _clear_canvas(self, canvas):
        self._canvas_fb[id(canvas)] = bytearray(self.width * self.height * 3)

    def _fill_canvas(self, canvas, r, g, b):
        px = bytes((r & 255, g & 255, b & 255))
        self._canvas_fb[id(canvas)] = bytearray(px * (self.width * self.height))


# Convenience so `from matrix_sim import graphics` won't explode if the script
# imports it; provide no-op-ish stand-ins only if you actually use them.
class graphics:  # noqa: N801  (match rgbmatrix.graphics casing)
    @staticmethod
    def DrawText(*a, **k):
        raise NotImplementedError(
            "matrix_sim only mirrors SetImage/SwapOnVSync. Draw text into a "
            "PIL image with ImageDraw and use SetImage instead."
        )
