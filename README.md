# Matrix Display

A 64x32 HUB75 LED matrix display driven by `matrix_server.py`. It cycles
between screens (weather, and a stocks stub), and can render either to real
hardware or to a browser for local development.

## Files

| File | Purpose |
|---|---|
| `matrix_server.py` | Main script — wires screens up to the matrix and to the screen-switching controls |
| `screens/` | Each screen is self-contained here; see below |
| `matrix_sim.py` | Drop-in stand-in for `rgbmatrix` that streams frames to a browser over WebSocket instead of a physical panel |
| `led-matrix-simulator.html` | Browser page that renders the streamed frames as a virtual LED panel |
| `settings_app.py` | Tiny Flask UI for enabled screens / auto-advance / per-screen seconds / MQTT control settings (see below) |
| `mqtt_control.py` | MQTT control bus — subscribes to `<device>/#` on a LAN broker and turns messages into screen switches (see "MQTT control" below) |
| `audio_sender.py` | Runs on the computer playing the audio; captures the desktop output with `parec` and streams it as raw PCM over TCP to the spectrum, oscilloscope, or audio-reactive Mondrian screen (see below) |
| `VT323-Regular.ttf` | Retro terminal font used by the cyberpunk screens (OFL-licensed, see `VT323-OFL.txt`) |
| `MatrixRainKana.ttf` | Katakana/digits/A-Z subset of Noto Sans Mono CJK JP used by `screens/matrix_rain.py` (OFL-licensed, see `MatrixRainKana-OFL.txt`) |
| `systemd-user/*.service` | systemd `--user` unit definitions for running everything on this machine (see below) |
| `matrix_sim.env` | `MATRIX_HOST` for the `systemd-user` audio-sender units (see below) |
| `install-user-services.sh` | Installs/updates the `systemd-user` units for the current user and (re)starts them |
| `systemd/matrix-server.service`, `systemd/matrix-settings.service` | systemd units for running on the Pi itself (see below) |
| `deploy.sh` | rsyncs this project to the Pi (see below) |
| `requirements.txt` | Python dependencies |
| `.venv/` | Project virtualenv with the script's dependencies |

## Setup

Dependencies live in a project-local virtualenv:

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Running directly (no systemd)

Simulate mode (no hardware, no sudo — streams frames to a browser instead):

```
.venv/bin/python3 matrix_server.py --simulate --refresh-minutes 10
```

Then open `led-matrix-simulator.html` in a browser (or serve it, see
"Viewing" below) and connect to `ws://localhost:8888`.

On the real hardware (Pi Zero 2 W + rpi-rgb-led-matrix), drop `--simulate`
and run with `sudo` (needs the `rgbmatrix` bindings installed separately —
see the docstring at the top of `matrix_server.py`):

```
sudo python3 matrix_server.py
```

## Screens

Each screen lives in its own file under `screens/`, implementing the
`Screen` interface from `screens/base.py` (`render()`, and optionally
`start()` to kick off background data refreshes). `ScreenManager`
(`screens/manager.py`) tracks which one is active and cycles between
whichever screens `matrix_server.py`'s `main()` lists — adding a screen is
just adding another file plus one line in `main()`.

- **`screens/weather.py`** — current temperature + condition icon, refetched
  every `--refresh-minutes`.
- **`screens/weather_cyberpunk.py`** — same weather data, retro/synthwave
  theme: a gradient orange-to-magenta sun sliced by horizontal bands, magenta
  cloud outlines, cyan accents, and VT323 (retro terminal font) temperature
  text with a pink/cyan glow.
- **`screens/high_temp_cyberpunk.py`** — today's forecast high temperature
  as a big glowing yellow number with a "HIGH" label below, same
  palette/font/scanlines as the other cyberpunk screens, refetched every
  `--refresh-minutes`.
- **`screens/clock_cyberpunk.py`** — current time (`HH:MM`), same
  palette/font/scanlines as the other cyberpunk screens. Ticks its own
  redraw once a second.
- **`screens/aqi_cyberpunk.py`** — current US AQI, same palette/font/
  scanlines as the other cyberpunk screens. The number glows in a color for
  its severity category (green "GOOD" through maroon "HAZARDOUS"),
  refetched every `--refresh-minutes`.
- **`screens/humidity_cyberpunk.py`** — current relative humidity as a
  glowing percentage with a label below, same palette/font/scanlines as the
  other cyberpunk screens, refetched every `--refresh-minutes`.
- **`screens/changelog_cyberpunk.py`** — the slackware-current changelog,
  fetched once a day, scrolling upward a pixel at a time while it's the
  active screen: it advances a little each time the rotation comes around
  and starts over from the top once it has scrolled through the most recent
  entries. Same cyberpunk palette/font/scanlines.
- **`screens/cyberpunk_theme.py`** — not a screen itself; the shared
  palette, font path, scanline helper, and glow-text helper the cyberpunk
  screens all import, so their look stays in sync.
- **`screens/stocks.py`** — stub screen ("STOCKS" / "SOON"); replace
  `render()` with a real quote fetch later.
- **`screens/mondrian.py`** — generative art: the canvas recursively split
  into random rectangles separated by thick black lines, mostly white with a
  few primary red/blue/yellow fills, Piet Mondrian style. A new composition
  every few seconds while it's the active screen.
- **`screens/message.py`** — a short text message, "Hello" by default,
  word-wrapped and centered. Settable at runtime via `POST /message` on the
  control server (or `settings_app.py`'s matching route) — kept in memory
  only, so it resets to the default on restart:
  ```
  curl -X POST http://localhost:8787/message \
      -H 'Content-Type: application/json' -d '{"msg": "on my way"}'
  ```
- **`screens/spectrum.py`** — audio spectrum analyzer: 16 log-spaced
  frequency bars (bass left, treble right) with falling peak caps, same
  cyberpunk palette/scanlines. The panel has no audio input of its own, so
  the PCM comes in over the network — run `audio_sender.py` on the
  computer whose desktop audio you want to visualize (it captures the
  PipeWire/PulseAudio monitor of the default sink with `parec` and
  forwards raw s16le/48 kHz/mono PCM); the screen listens for it on
  `--audio-port` (default 8788):

  ```
  python3 audio_sender.py 192.168.1.109           # the Pi's address
  python3 audio_sender.py pi.lan --source <name>  # capture something other than desktop output
  ```

  The sender needs `parec` (pipewire-pulse or pulseaudio-utils) but no
  Python packages; the FFT runs on the receiving side and needs `numpy`
  in the venv `matrix_server.py` runs from (it's in requirements.txt) —
  if it's missing, this screen shows "NO NUMPY" instead of taking the
  display down. With no sender connected for a couple of seconds the
  screen shows a dim "NO SIGNAL".
- **`screens/oscope.py`** — cyberpunk oscilloscope: the time-domain
  waveform of the same desktop audio feed, drawn as a glowing cyan/pink
  line over a faint scope grid. Triggers on the first rising zero-crossing
  each analysis chunk so the trace holds roughly still instead of sliding
  with the signal's phase, and normalizes against a rolling peak amplitude
  so quiet and loud sources both stay visible. It's a separate screen with
  its own listener, so it needs its own `audio_sender.py` instance pointed
  at `--oscope-port` (default 8790) — run this alongside the one feeding
  the spectrum screen if you want both live at once:

  ```
  python3 audio_sender.py 192.168.1.109 --port 8790
  ```

  Same `numpy` requirement and "NO NUMPY"/"NO SIGNAL" fallbacks as the
  spectrum screen.
- **`screens/mondrian_viz.py`** — audio-reactive Piet Mondrian composition:
  black grid lines dividing the canvas into white panes plus a red, a blue,
  and a yellow block, same palette as `screens/mondrian.py` but driven by
  real bass/mid/treble energy from desktop audio instead of random —
  divider positions track each band's level, panes rotate through
  red/blue/yellow over time and flash brighter on strong transients. Ported
  from the `mondrian` pattern in the `soma-zig` terminal music player's
  visualizer. A different screen from `screens/mondrian.py` (which stays
  generative, no audio) — this one is `mondrian-viz`. Own listener, own
  `audio_sender.py` instance, `--mondrian-viz-port` (default 8791):

  ```
  python3 audio_sender.py 192.168.1.109 --port 8791
  ```

  Same `numpy` requirement and "NO NUMPY"/"NO SIGNAL" fallbacks as the
  spectrum screen.

Switch screens two ways:

- **Spacebar**, if the script is running directly in a terminal (stdin is a
  TTY). Only works this way when not managed by systemd, since a systemd
  service has no controlling terminal.
- **HTTP control server**, always available, on port `8787` by default
  (`--control-port`):

  ```
  curl -X POST http://localhost:8787/next-screen   # switch screen
  curl http://localhost:8787/screen                # check current screen
  curl -X POST http://localhost:8787/screen/weather  # jump straight to a screen
  ```

  `led-matrix-simulator.html`'s Live tab also has a "Next screen" button
  that does this same `POST` from the browser (set the "Control server"
  field if it's not on the default `http://localhost:8787`).

## Viewing the simulator

`led-matrix-simulator.html` can be opened directly as a file, or served over
HTTP (useful for viewing from another device) with `python -m http.server`,
managed by systemd as the `matrix-view` service (see below) on port `8080`.

## Screen settings (enabled screens, auto-advance, seconds each)

`settings_app.py` is a tiny Flask page for picking which screens are
enabled, turning auto-advance on/off, and setting how many seconds each
screen gets before auto-advance moves to the next one:

```
python3 settings_app.py                    # UI on :8789, talks to control server on :8787
CONTROL_URL=http://<host>:8787 python3 settings_app.py --port 8789
```

It's just a form in front of `matrix_server.py`'s control server
(`GET`/`POST /config`), so it can run as its own process — the same
endpoint works directly too:

```
curl http://localhost:8787/config
curl -X POST http://localhost:8787/config \
    -H 'Content-Type: application/json' \
    -d '{"enabled": ["weather", "stocks"], "durations": {"weather": 15}, "auto_advance": true}'
```

Settings are saved to `screen_config.json` (gitignored) next to
`matrix_server.py`, so they survive a restart.

## MQTT control

`matrix_server.py` can also subscribe to an MQTT broker on your LAN and turn
messages into screen switches — the same things the HTTP control server
does, but reachable from anything that can publish (Home Assistant, a shell
script, `mosquitto_pub`). Topics are `<device>/<action>` (device defaults to
`display1`):

| Topic | Effect |
|---|---|
| `display1/weather` | switch to the named screen (any screen name works, even ones disabled for auto-advance; payload ignored) |
| `display1/next` | advance to the next enabled screen |
| `display1/message` | set the message screen's text from the payload, then show it |
| `display1/auto` | auto-advance: payload `on`, `off` or `toggle` (default) |

The display reports its state back, retained, so a controller such as
[deckd](../deckd-zig) can show it and light the active key:

| Topic | Payload |
|---|---|
| `display1/state/screen` | name of the screen currently showing |
| `display1/state/auto` | `on` / `off` (auto-advance) |
| `display1/state/screens` | JSON list of screen names, in panel order |

```
mosquitto_pub -h 192.168.1.10 -t display1/weather -m x
mosquitto_pub -h 192.168.1.10 -t display1/message -m "on my way"
```

Unknown actions are logged and ignored. A retained message re-fires every
time the display (re)connects, so it resumes whatever was last commanded
after a restart — clear one with `mosquitto_pub -t <topic> -r -n` if that's
not what you want.

Configure it in the settings UI (`http://<host>:8789`) or directly:

```
curl -X POST http://localhost:8787/config \
    -H 'Content-Type: application/json' \
    -d '{"mqtt": {"enabled": true, "host": "192.168.1.10", "port": 1883,
                  "device": "display1", "username": "", "password": ""}}'
```

Settings live in the `"mqtt"` section of `screen_config.json` (gitignored),
take effect immediately (the client reconnects on change), and survive a
restart. Plain TCP only, no TLS — keep it on the LAN. The connection is
outbound from the display to the broker; no new listening port. Needs
`paho-mqtt` in the venv (it's in `requirements.txt`); if it's missing the
display runs fine and just logs that MQTT control is disabled.

## Running under systemd (this machine, user-level)

`systemd-user/` defines six `systemd --user` units — no root, running as
your normal login user:

| unit | what | port(s) |
|---|---|---|
| `matrix-display` | the weather/stocks script, `--simulate` mode by default | control `8787`, matrix stream `8888` |
| `matrix-view` | `serve_view.py`, serves this directory | `8080` |
| `matrix-settings` | `settings_app.py`, the screen-settings UI above | `8789` |
| `audio-spectrum` | `audio_sender.py` → the Pi's spectrum listener | `8788` on the Pi |
| `audio-oscope` | `audio_sender.py --port 8790` → the Pi's oscope listener | `8790` on the Pi |
| `audio-mondrian` | `audio_sender.py --port 8791` → the Pi's Mondrian listener | `8791` on the Pi |

The three `audio-*` units capture this machine's desktop audio and stream it
to the real panel on the Pi (192.168.1.109) — they're for driving the
hardware's audio-reactive screens during local dev, and ignore
matrix-display's `--simulate` mode. The Pi's address comes from
`MATRIX_HOST` in `matrix_sim.env`, which each `audio-*` unit reads via
`EnvironmentFile`. Unlike pm2's old `ecosystem.config.js`, systemd re-reads
that file on every restart, so a change just needs:

```
$EDITOR matrix_sim.env
systemctl --user restart audio-spectrum audio-oscope audio-mondrian
```

Run `audio_sender.py` by hand and it reads `MATRIX_HOST` itself (explicit
host argument beats the env var).

First-time setup, and after pulling changes to any file under
`systemd-user/`:

```
./install-user-services.sh
```

This copies the units to `~/.config/systemd/user/`, then `enable --now`s
all six. From there, manage them individually with plain `systemctl --user`:

```
systemctl --user start matrix-display     # start one
systemctl --user stop matrix-display
systemctl --user restart matrix-display
journalctl --user -u matrix-display -f    # logs
systemctl --user disable --now matrix-display   # stop and remove from boot
```

To start only the senders (when the Pi is the display and you don't need
the local sim units):

```
systemctl --user start audio-spectrum audio-oscope audio-mondrian
```

Then open `http://<host>:8080/led-matrix-simulator.html` and connect to
`ws://<host>:8888`, switch screens with:

```
curl -X POST http://<host>:8787/next-screen
```

and manage enabled screens / auto-advance / seconds at
`http://<host>:8789`.

`matrix-display` handles `SIGTERM`/`SIGINT` cleanly, so `systemctl --user
stop`/`restart` shut it down gracefully rather than force-killing it.

These units only start at login by default; to have them come up at boot
and keep running after you log out, enable lingering once:
`loginctl enable-linger $USER`.

### Driving hardware attached to this machine

`systemd-user/` is unprivileged, but the `rgbmatrix` driver needs root for
GPIO access (see `matrix_server.py`'s docstring), so it can't run
`matrix-display` with `--simulate` dropped. For that, write a root-level
unit instead — `systemd/matrix-server.service` (below) is exactly that
shape, just adjust `User=`, `WorkingDirectory=`, and the paths for this
machine instead of the Pi.

## Running under systemd (Pi hardware, system-level)

On the Pi itself, `systemd/matrix-server.service` runs `matrix_server.py`
directly on the real panel (no `--simulate`) as a boot-time, root-installed
service (`/etc/systemd/system/`, `User=pi`) — this is the deployment path
actually used on hardware. The `systemd-user/` units above are for
dev/simulate workflows on this machine.

Deploy the whole project (not just the script — `matrix_server.py` imports
`screens/` and needs `matrix_sim.py`, `VT323-Regular.ttf` alongside it)
to the Pi's `WorkingDirectory` (`/home/pi` by default in the unit file) with
`deploy.sh`:

```
./deploy.sh                    # rsyncs to pi@192.168.1.109:/home/pi/
PI_HOST=pi@<other-ip> ./deploy.sh   # different host
./deploy.sh --delete           # also remove files on the Pi no longer present locally
```

It excludes `.git/`, `.venv/`, `__pycache__/`, and `.claude/`, and never
touches the Pi's own `venv/` (even with `--delete`). After syncing, it
`ssh`es in and restarts `matrix-server` (and `matrix-settings`, if that
service is installed) to pick up the new code (needs a passwordless SSH key
and passwordless `sudo` for those commands on the Pi).

The first time, set up the services on the Pi — `matrix-server.service` runs
the display driver, `matrix-settings.service` runs the settings UI
(`settings_app.py`) on port `8789`, talking to `matrix-server` over
`localhost:8787`:

```
sudo cp systemd/matrix-server.service systemd/matrix-settings.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now matrix-server.service matrix-settings.service
sudo journalctl -u matrix-server -u matrix-settings -f       # check both came up clean
```

`matrix-settings.service` needs `flask` in the Pi's `venv` (see
`requirements.txt`) — install it there the same way as any other dependency
change. The spectrum, oscilloscope, and audio-reactive Mondrian screens likewise need `numpy` in that venv (also in
`requirements.txt`); prebuilt aarch64/piwheels wheels mean no compilation.
MQTT control likewise needs `paho-mqtt` (pure Python, no compilation).

If replacing an older `weather-matrix.service`:

```
sudo systemctl disable --now weather-matrix.service
sudo rm /etc/systemd/system/weather-matrix.service
```

Screen switching works the same as under the `systemd-user` units above —
the control server (port `8787`) is the mechanism, since systemd services
don't have a TTY either.
`settings_app.py` only needs network access to that port, so it can run
from your dev machine against `CONTROL_URL=http://<pi-ip>:8787` instead of
on the Pi itself.

Even without `--simulate`, `matrix_server.py` also broadcasts every frame it
draws to the physical panel over WebSocket on `--sim-port` (default `8888`),
so `led-matrix-simulator.html` and the settings app's `/kiosk` view mirror
the real hardware, not just simulated runs. This adds a small amount of
per-redraw CPU overhead (JSON+base64 encoding a frame) — worth knowing on a
Pi Zero 2 W, which the top of `matrix_server.py` already flags as tight on
headroom.

The unit runs as `User=pi` (unprivileged). The `rgbmatrix` driver normally
needs root for GPIO access (see `matrix_server.py`'s docstring) — if the
service was already working this way, the Pi's GPIO permissions are
presumably set up for the `pi` user already; if it wasn't, that's a
separate, pre-existing issue this update doesn't address.

## Ports

| Port | What |
|---|---|
| `8787` | HTTP control server — switch/query the active screen, get/set screen settings (`/config`) |
| `8788` | TCP — raw PCM audio from `audio_sender.py` into the spectrum screen (`--audio-port`) |
| `8888` | WebSocket stream of the matrix framebuffer (`--sim-port`, simulate mode only) |
| `8080` | `matrix-view`'s file server for `led-matrix-simulator.html` |
| `8789` | `settings_app.py`'s screen-settings UI |
| `8790` | TCP — raw PCM audio from `audio_sender.py` into the oscilloscope screen (`--oscope-port`) |
| `8791` | TCP — raw PCM audio from `audio_sender.py` into the audio-reactive Mondrian screen (`--mondrian-viz-port`) |

## Troubleshooting

- **`matrix-display`/`matrix-settings` crash-looping with
  `ModuleNotFoundError`**: their unit's `ExecStart` in `systemd-user/` must
  point at `.venv/bin/python3`, not system `python3` — the system
  interpreter doesn't have `click`/`requests`/`pillow`/`websockets`
  installed.
- **Spacebar does nothing**: only works when the script's stdin is a real
  terminal. Under systemd (or any headless launch), use the HTTP control
  server instead.
- **`matrix-view` logs a `KeyboardInterrupt` traceback from `socket.getfqdn`
  on restart**: that was `python -m http.server`'s blocking reverse-DNS
  lookup on bind getting hit by systemd's stop signal mid-call — fixed by
  `serve_view.py`, which skips that lookup. If you see this, `~/.config/
  systemd/user/matrix-view.service` is stale — rerun `./install-user-services.sh`.

## License

MIT, see [LICENSE](LICENSE). The bundled fonts keep their own licenses (see the
`*-OFL.txt` files).
