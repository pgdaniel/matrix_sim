#!/usr/bin/env python3
"""Stream this machine's desktop audio to the matrix "spectrum" screen.

Captures the monitor of the default audio sink (everything playing through
the speakers/headphones) with parec, and forwards the raw PCM — s16le mono
at 48 kHz — over TCP to the spectrum screen's listener on the machine
running matrix_server.py (the Pi). Reconnects with backoff whenever the
connection or parec drops. Stop with Ctrl-C.

    python3 audio_sender.py 192.168.1.160
    python3 audio_sender.py pi.lan --port 8788
    python3 audio_sender.py pi.lan --source alsa_output.pci-0000_00_1f.3.analog-stereo.monitor

Requires parec (pipewire-pulse or PulseAudio's pulseaudio-utils) on this
machine. No third-party Python packages needed here — the FFT happens on
the receiving end. The PCM format must match screens/spectrum.py
(SAMPLE_RATE / s16le / mono); don't change the parec arguments below
without changing it there too.
"""

import argparse
import shutil
import socket
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("host", help="host running matrix_server.py (e.g. the Pi's IP)")
    parser.add_argument("--port", type=int, default=8788,
                        help="spectrum screen's listener port (default 8788)")
    parser.add_argument("--source", default="@DEFAULT_MONITOR@",
                        help="PulseAudio source to capture (default: @DEFAULT_MONITOR@ — "
                             "the monitor of the default sink, i.e. desktop output. "
                             "See 'pactl list short sources'.)")
    parser.add_argument("--retry-seconds", type=float, default=2.0,
                        help="delay between reconnect attempts (default 2)")
    args = parser.parse_args()

    if shutil.which("parec") is None:
        sys.exit("parec not found — install pipewire-pulse or pulseaudio-utils.")

    parec = None
    try:
        while True:
            try:
                sock = socket.create_connection((args.host, args.port), timeout=5)
            except OSError as e:
                print(f"connect to {args.host}:{args.port} failed: {e}; "
                      f"retrying in {args.retry_seconds:g}s")
                time.sleep(args.retry_seconds)
                continue
            print(f"connected to {args.host}:{args.port}; capturing '{args.source}'")

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
