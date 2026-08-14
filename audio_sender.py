#!/usr/bin/env python3
"""Stream this machine's desktop audio to the matrix's audio-reactive
screens (spectrum analyzer, oscilloscope, and audio-reactive Mondrian).

Captures the monitor of the default audio sink (everything playing through
the speakers/headphones) with parec, and forwards the raw PCM — s16le mono
at 48 kHz — over TCP to one of those screens' listeners on the machine
running matrix_server.py (the Pi). Reconnects with backoff whenever the
connection or parec drops. Stop with Ctrl-C.

Each screen has its own listener/port (spectrum: 8788, oscilloscope: 8790,
Mondrian: 8791), and each sender process feeds exactly one — run a second
(or third) instance if you want more than one screen live at once:

    python3 audio_sender.py 192.168.1.109                  # spectrum (port 8788)
    python3 audio_sender.py pi.lan --port 8790              # oscilloscope
    python3 audio_sender.py pi.lan --port 8791              # audio-reactive Mondrian
    python3 audio_sender.py pi.lan --source alsa_output.pci-0000_00_1f.3.analog-stereo.monitor

The host argument is optional: if omitted, the MATRIX_HOST environment
variable is used, falling back to DEFAULT_HOST below — so when the Pi's IP
changes you can export MATRIX_HOST instead of editing pm2's
ecosystem.config.js (which honors the same variable).

Requires parec (pipewire-pulse or PulseAudio's pulseaudio-utils) on this
machine. No third-party Python packages needed here — the FFT/waveform
work happens on the receiving end. The PCM format must match
screens/spectrum.py, screens/oscope.py, and screens/mondrian_viz.py
(SAMPLE_RATE / s16le / mono); don't change the parec arguments below
without changing those too.
"""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time

DEFAULT_HOST = "192.168.1.109"  # the Pi; MATRIX_HOST env var overrides


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("host", nargs="?", default=None,
                        help="host running matrix_server.py (e.g. the Pi's IP). "
                             "Optional: falls back to $MATRIX_HOST, then the "
                             "built-in default " + DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=8788,
                        help="target screen's listener port (default 8788, the spectrum "
                             "screen's; use 8790 for the oscilloscope screen, 8791 for "
                             "the audio-reactive Mondrian screen)")
    parser.add_argument("--source", default="@DEFAULT_MONITOR@",
                        help="PulseAudio source to capture (default: @DEFAULT_MONITOR@ — "
                             "the monitor of the default sink, i.e. desktop output. "
                             "See 'pactl list short sources'.)")
    parser.add_argument("--retry-seconds", type=float, default=2.0,
                        help="delay between reconnect attempts (default 2)")
    args = parser.parse_args()
    host = args.host or os.environ.get("MATRIX_HOST") or DEFAULT_HOST

    if shutil.which("parec") is None:
        sys.exit("parec not found — install pipewire-pulse or pulseaudio-utils.")

    parec = None
    try:
        while True:
            try:
                sock = socket.create_connection((host, args.port), timeout=5)
            except OSError as e:
                print(f"connect to {host}:{args.port} failed: {e}; "
                      f"retrying in {args.retry_seconds:g}s")
                time.sleep(args.retry_seconds)
                continue
            print(f"connected to {host}:{args.port}; capturing '{args.source}'")

            parec = subprocess.Popen(
                ["parec", f"--device={args.source}", "--format=s16le",
                 "--rate=48000", "--channels=1", "--latency-msec=50"],
                stdout=subprocess.PIPE,
            )
            try:
                while True:
                    # read1 (not read) returns after a single pipe read, so
                    # audio isn't held back waiting to fill the buffer.
                    data = parec.stdout.read1(65536)
                    if not data:
                        raise BrokenPipeError("parec exited")
                    sock.sendall(data)
            except OSError as e:
                print(f"stream dropped ({e}); reconnecting in {args.retry_seconds:g}s")
            finally:
                parec.kill()
                parec.wait()
                parec = None
                sock.close()
            time.sleep(args.retry_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        if parec is not None and parec.poll() is None:
            parec.kill()
    print("stopped")


if __name__ == "__main__":
    main()
