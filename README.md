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
| `LindenHill-webfont.ttf` | Pixel font used for on-panel text |
| `ecosystem.config.js` | pm2 process definitions (see below) |
| `.venv/` | Project virtualenv with the script's dependencies |

## Setup

Dependencies live in a project-local virtualenv:

```
python3 -m venv .venv
.venv/bin/pip install click requests pillow websockets
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
- **`screens/weather_cyberpunk.py`** — same weather data, neon/scanline
  theme (magenta cloud outlines, cyan accents, pink-cyan glow text).
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

## Viewing the simulator

`led-matrix-simulator.html` can be opened directly as a file, or served over
HTTP (useful for viewing from another device) with `python -m http.server`,
managed by pm2 as the `matrix-view` app (see below) on port `8080`.

## Running under pm2

`ecosystem.config.js` defines two apps:

| app | what | port(s) |
|---|---|---|
| `matrix-display` | the weather/stocks script, `--simulate` mode by default | control `8787`, matrix stream `8888` |
| `matrix-view` | `python3 -m http.server`, serves this directory | `8080` |

```
pm2 start ecosystem.config.js     # start both
pm2 stop matrix-display           # stop one
pm2 restart matrix-display
pm2 logs matrix-display
pm2 delete matrix-display         # remove from pm2's process list
```

Then open `http://<host>:8080/led-matrix-simulator.html` and connect to
`ws://<host>:8888`, and switch screens with:

```
curl -X POST http://<host>:8787/next-screen
```

`matrix-display` handles `SIGTERM`/`SIGINT` cleanly, so `pm2 stop` /
`pm2 restart` shut it down gracefully rather than being force-killed.

### Deploying to real hardware under pm2

Edit `ecosystem.config.js`: drop `--simulate` (and `--sim-port`) from
`matrix-display`'s `args`, and run pm2 as root, since the `rgbmatrix` driver
needs GPIO access:

```
sudo pm2 start ecosystem.config.js --only matrix-display
```

## Ports

| Port | What |
|---|---|
| `8787` | HTTP control server — switch/query the active screen |
| `8888` | WebSocket stream of the matrix framebuffer (`--sim-port`, simulate mode only) |
| `8080` | `matrix-view`'s file server for `led-matrix-simulator.html` |

## Troubleshooting

- **pm2 app crash-looping with `ModuleNotFoundError`**: pm2's `interpreter`
  in `ecosystem.config.js` must point at `.venv/bin/python3`, not system
  `python3` — the system interpreter doesn't have `click`/`requests`/
  `pillow`/`websockets` installed.
- **Spacebar does nothing**: only works when the script's stdin is a real
  terminal. Under pm2 (or any headless launch), use the HTTP control server
  instead.
