#!/usr/bin/python3
"""Static file server for led-matrix-simulator.html — like `python -m
http.server`, but skips HTTPServer.server_bind()'s socket.getfqdn(host) call.

That reverse-DNS lookup can take several seconds depending on the machine's
DNS setup, and if a shutdown signal (pm2's default stop signal is SIGINT)
arrives while it's blocked there, it logs a spurious KeyboardInterrupt
traceback instead of exiting cleanly. Nothing here needs the FQDN, so skip it.
"""

import signal
import socketserver
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class FastBindHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name = self.server_address[0]
        self.server_port = self.server_address[1]


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = FastBindHTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)

    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    signal.signal(signal.SIGINT, lambda signum, frame: sys.exit(0))

    print(f"Serving HTTP on 0.0.0.0 port {port} (http://0.0.0.0:{port}/) ...")
    server.serve_forever()


if __name__ == "__main__":
    main()
