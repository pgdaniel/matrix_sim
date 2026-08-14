// IP/hostname of the Pi running matrix_server.py, for the apps that talk to
// it (the audio senders). Override without editing this file:
//
//   MATRIX_HOST=192.168.1.200 pm2 start ecosystem.config.js
//
// Note pm2 evaluates this file at `pm2 start` time — `pm2 restart` does NOT
// re-read it, so after changing MATRIX_HOST re-create the senders:
// pm2 delete audio-spectrum audio-oscope audio-mondrian && MATRIX_HOST=... pm2 start ecosystem.config.js --only audio-spectrum,audio-oscope,audio-mondrian
// (audio_sender.py also reads MATRIX_HOST itself when launched without a
// host argument, e.g. under other process managers.)
const MATRIX_HOST = process.env.MATRIX_HOST || "192.168.1.109";

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
    {
      // Web UI for picking enabled screens, auto-advance, and per-screen
      // seconds. Talks to matrix-display's control server (port 8787), so
      // needs flask + requests from the venv, same as matrix-display.
      name: "matrix-settings",
      script: "settings_app.py",
      interpreter: __dirname + "/.venv/bin/python3",
      args: "--port 8789",
      cwd: __dirname,
      autorestart: true,
      watch: false,
    },
    // Desktop-audio senders for the three audio-reactive screens. These run
    // HERE (the machine playing the sound) and stream raw PCM to the real
    // panel on the Pi — they ignore matrix-display's --simulate mode. Each
    // screen has its own listener port, so one sender per screen. The
    // senders need no third-party Python packages (system python3), and
    // reconnect on their own when the Pi or network drops. Start just these
    // with: pm2 start ecosystem.config.js --only audio-spectrum,audio-oscope,audio-mondrian
    {
      name: "audio-spectrum",
      script: "audio_sender.py",
      interpreter: "python3",
      args: MATRIX_HOST, // spectrum listener, port 8788
      cwd: __dirname,
      autorestart: true,
      watch: false,
    },
    {
      name: "audio-oscope",
      script: "audio_sender.py",
      interpreter: "python3",
      args: `${MATRIX_HOST} --port 8790`,
      cwd: __dirname,
      autorestart: true,
      watch: false,
    },
    {
      name: "audio-mondrian",
      script: "audio_sender.py",
      interpreter: "python3",
      args: `${MATRIX_HOST} --port 8791`,
      cwd: __dirname,
      autorestart: true,
      watch: false,
    },
  ],
};
