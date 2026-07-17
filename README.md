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
| `settings_app.py` | Tiny Flask UI for enabled screens / auto-advance / per-screen seconds (see below) |
| `LindenHill-webfont.ttf` | Pixel font used by `screens/weather.py`/`screens/stocks.py` |
| `VT323-Regular.ttf` | Retro terminal font used by the cyberpunk screens (OFL-licensed, see `VT323-OFL.txt`) |
| `ecosystem.config.js` | pm2 process definitions (see below) |
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

## Running directly (no pm2)

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
- **`screens/clock_cyberpunk.py`** — current time (`HH:MM`) with the current
  temperature (far left) and AQI (far right) underneath, same
  palette/font/scanlines as the cyberpunk weather screen. Ticks its own
  redraw once a second for the clock, on top of the usual weather/AQI
  refetch on `--refresh-minutes`.
- **`screens/cyberpunk_theme.py`** — not a screen itself; the shared
  palette, font path, scanline helper, and glow-text helper the two
  cyberpunk screens both import, so their look stays in sync.
- **`screens/stocks.py`** — stub screen ("STOCKS" / "SOON"); replace
  `render()` with a real quote fetch later.

Switch screens two ways:

- **Spacebar**, if the script is running directly in a terminal (stdin is a
  TTY). Only works this way when not managed by pm2, since pm2 detaches
  stdin.
- **HTTP control server**, always available, on port `8787` by default
  (`--control-port`):

  ```
  curl -X POST http://localhost:8787/next-screen   # switch screen
  curl http://localhost:8787/screen                # check current screen
  ```

  `led-matrix-simulator.html`'s Live tab also has a "Next screen" button
  that does this same `POST` from the browser (set the "Control server"
  field if it's not on the default `http://localhost:8787`).

## Viewing the simulator

`led-matrix-simulator.html` can be opened directly as a file, or served over
HTTP (useful for viewing from another device) with `python -m http.server`,
managed by pm2 as the `matrix-view` app (see below) on port `8080`.

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

## Running under pm2

`ecosystem.config.js` defines three apps:

| app | what | port(s) |
|---|---|---|
| `matrix-display` | the weather/stocks script, `--simulate` mode by default | control `8787`, matrix stream `8888` |
| `matrix-view` | `python3 -m http.server`, serves this directory | `8080` |
| `matrix-settings` | `settings_app.py`, the screen-settings UI above | `8789` |

```
pm2 start ecosystem.config.js     # start all three
pm2 stop matrix-display           # stop one
pm2 restart matrix-display
pm2 logs matrix-display
pm2 delete matrix-display         # remove from pm2's process list
```

Then open `http://<host>:8080/led-matrix-simulator.html` and connect to
`ws://<host>:8888`, switch screens with:

```
curl -X POST http://<host>:8787/next-screen
```

and manage enabled screens / auto-advance / seconds at
`http://<host>:8789`.

`matrix-display` handles `SIGTERM`/`SIGINT` cleanly, so `pm2 stop` /
`pm2 restart` shut it down gracefully rather than being force-killed.

### Deploying to real hardware under pm2

Edit `ecosystem.config.js`: drop `--simulate` (and `--sim-port`) from
`matrix-display`'s `args`, and run pm2 as root, since the `rgbmatrix` driver
needs GPIO access:

```
sudo pm2 start ecosystem.config.js --only matrix-display
```

## Running under systemd (Pi hardware)

On the Pi itself, `systemd/matrix-server.service` runs `matrix_server.py`
directly on the real panel (no `--simulate`) as a boot-time service — this
is the deployment path actually used on hardware; pm2 above is for
dev/simulate workflows.

Deploy the whole project (not just the script — `matrix_server.py` imports
`screens/` and needs `matrix_sim.py`, `LindenHill-webfont.ttf` alongside it)
to the Pi's `WorkingDirectory` (`/home/pi` by default in the unit file) with
`deploy.sh`:

```
./deploy.sh                    # rsyncs to pi@192.168.1.160:/home/pi/
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
change.

If replacing an older `weather-matrix.service`:

```
sudo systemctl disable --now weather-matrix.service
sudo rm /etc/systemd/system/weather-matrix.service
```

Screen switching works the same as under pm2 — the control server (port
`8787`) is the mechanism, since systemd services don't have a TTY either.
`settings_app.py` only needs network access to that port, so it can run
from your dev machine against `CONTROL_URL=http://<pi-ip>:8787` instead of
on the Pi itself.

The unit runs as `User=pi` (unprivileged). The `rgbmatrix` driver normally
needs root for GPIO access (see `matrix_server.py`'s docstring) — if the
service was already working this way, the Pi's GPIO permissions are
presumably set up for the `pi` user already; if it wasn't, that's a
separate, pre-existing issue this update doesn't address.

## Ports

| Port | What |
|---|---|
| `8787` | HTTP control server — switch/query the active screen, get/set screen settings (`/config`) |
| `8888` | WebSocket stream of the matrix framebuffer (`--sim-port`, simulate mode only) |
| `8080` | `matrix-view`'s file server for `led-matrix-simulator.html` |
| `8789` | `settings_app.py`'s screen-settings UI |

## Troubleshooting

- **pm2 app crash-looping with `ModuleNotFoundError`**: pm2's `interpreter`
  in `ecosystem.config.js` must point at `.venv/bin/python3`, not system
  `python3` — the system interpreter doesn't have `click`/`requests`/
  `pillow`/`websockets` installed.
- **Spacebar does nothing**: only works when the script's stdin is a real
  terminal. Under pm2 (or any headless launch), use the HTTP control server
  instead.
- **`matrix-view` logs a `KeyboardInterrupt` traceback from `socket.getfqdn`
  on restart**: that was `python -m http.server`'s blocking reverse-DNS
  lookup on bind getting hit by pm2's stop signal mid-call — fixed by
  `serve_view.py`, which skips that lookup. If you see this, `matrix-view`
  isn't running the current `ecosystem.config.js`.
  instead.
