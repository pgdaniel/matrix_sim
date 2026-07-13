module.exports = {
  apps: [
    {
      name: "matrix-display",
      script: "weather_fetcher_pizero2w.py",
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
      // of opening the file locally.
      name: "matrix-view",
      script: "python3",
      args: "-m http.server 8080",
      cwd: __dirname,
      autorestart: true,
      watch: false,
    },
  ],
};
