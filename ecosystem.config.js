module.exports = {
  apps: [
    {
      name: "matrix-display",
      script: "matrix_server.py",
      interpreter: __dirname + "/.venv/bin/python3",
      // Simulate mode by default (no sudo, renders to the browser simulator
      // instead of a physical panel). Drop --simulate/--sim-port here, and
      // launch pm2 with sudo instead, to drive the real hardware.
      args: "--simulate --refresh-minutes 10",
      cwd: __dirname,
      autorestart: true,
      watch: false,
    },
    {
      // Serves led-matrix-simulator.html (and the font it needs) so it's
      // reachable at http://<host>:8080/led-matrix-simulator.html instead
      // of opening the file locally. Uses serve_view.py rather than plain
      // `python3 -m http.server` — see that file for why.
      name: "matrix-view",
      script: "serve_view.py",
      interpreter: "python3",
      args: "8080",
      cwd: __dirname,
      autorestart: true,
      watch: false,
    },
  ],
};
