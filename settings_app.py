#!/usr/bin/python3
"""Tiny Flask app for controlling the matrix display: a settings form
(enabled screens, auto-advance, seconds each, MQTT control settings), a
controls-free kiosk view for mirroring it on a second screen, and a
POST /message endpoint for setting the "message" screen's text.

None of these touch ScreenManager directly — all are thin clients of
matrix_server.py's control server (GET/POST /config, POST /message, and for
the kiosk view, matrix_sim.py's WebSocket frame broadcaster), the same one
led-matrix-simulator.html's "Next screen" button talks to. That means this
can run as its own process (even its own host) alongside matrix_server.py,
same as matrix-view does for the simulator page.

    python3 settings_app.py                              # UI on :8789, control server on :8787
    CONTROL_URL=http://<host>:8787 python3 settings_app.py --port 8789
"""

import json
import os
from urllib.parse import urlparse

import click
import requests
from flask import Flask, Response, redirect, render_template_string, request, url_for

app = Flask(__name__)
CONTROL_URL = os.environ.get("CONTROL_URL", "http://localhost:8787")

PAGE = """
<!doctype html>
<title>Matrix screen settings</title>
<style>
  body { font-family: sans-serif; max-width: 32rem; margin: 2rem auto; padding: 0 1rem; }
  table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
  td, th { padding: .4rem; text-align: left; border-bottom: 1px solid #ddd; }
  td.seconds { width: 5rem; }
  input[type=number] { width: 3.5rem; }
  .error { color: #b00020; }
  .current { color: #666; font-style: italic; }
</style>
<h1>Matrix screen settings</h1>
{% if error %}
  <p class="error">Couldn't reach the display at {{ control_url }}: {{ error }}</p>
{% else %}
<form method="post" action="{{ url_for('save') }}">
  <table>
    <tr><th>Enabled</th><th>Screen</th><th>Seconds</th></tr>
    {% for s in config.screens %}
    <tr>
      <td><input type="checkbox" name="enabled" value="{{ s.name }}" {{ 'checked' if s.enabled else '' }}></td>
      <td>{{ s.name }}{% if s.name == config.current %}<span class="current"> (current)</span>{% endif %}</td>
      <td class="seconds"><input type="number" min="1" name="seconds_{{ s.name }}" value="{{ s.seconds }}"></td>
    </tr>
    {% endfor %}
  </table>
  <label><input type="checkbox" name="auto_advance" {{ 'checked' if config.auto_advance else '' }}> Auto-advance</label>
  <h2>MQTT control</h2>
  <p>Publish to <code>&lt;device&gt;/&lt;screen&gt;</code> (e.g. <code>display1/weather</code>) to switch screens,
     <code>&lt;device&gt;/next</code> to advance, or <code>&lt;device&gt;/message</code> with text in the payload
     to set and show the message screen. No TLS; the password is stored in the display's
     <code>screen_config.json</code>.</p>
  <table>
    <tr><td>Enabled</td><td><input type="checkbox" name="mqtt_enabled" {{ 'checked' if config.mqtt.enabled else '' }}></td></tr>
    <tr><td>Broker host</td><td><input type="text" name="mqtt_host" value="{{ config.mqtt.host }}" placeholder="192.168.1.10"></td></tr>
    <tr><td>Port</td><td><input type="number" min="1" max="65535" name="mqtt_port" value="{{ config.mqtt.port }}"></td></tr>
    <tr><td>Device</td><td><input type="text" name="mqtt_device" value="{{ config.mqtt.device }}"></td></tr>
    <tr><td>Username</td><td><input type="text" name="mqtt_username" value="{{ config.mqtt.username }}"></td></tr>
    <tr><td>Password</td><td><input type="password" name="mqtt_password" value="{{ config.mqtt.password }}"></td></tr>
  </table>
  <p><button type="submit">Save</button></p>
</form>
<p><a href="{{ url_for('kiosk') }}">Kiosk view &#8594;</a> (controls-free, landscape, for mirroring on a second screen)</p>
{% endif %}
"""

KIOSK_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, user-scalable=no">
<title>Matrix Display</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%;overflow:hidden;background:#000}
  /* Forces a landscape layout even if the device (e.g. a phone propped up
     next to the panel) is held in portrait: in portrait, rotate the whole
     wrapper 90deg and swap its box to the viewport's height x width. */
  #wrap{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;}
  @media (orientation:portrait){
    #wrap{
      top:50%;left:50%;right:auto;bottom:auto;
      width:100vh;height:100vw;
      transform:translate(-50%,-50%) rotate(90deg);
      transform-origin:center center;
    }
  }
  canvas{display:block;image-rendering:pixelated}
  #status{
    position:fixed;top:10px;left:10px;
    font:11px ui-monospace,"SF Mono",Menlo,monospace;letter-spacing:.08em;
    text-transform:uppercase;color:#5f6b7e;pointer-events:none;
  }
  #status.err{color:#ff5c5c}
</style>
</head>
<body>
<div id="wrap"><canvas id="matrix"></canvas></div>
<div id="status"></div>
<script>
// Controls-free mirror of the live matrix stream — same WebSocket protocol
// as led-matrix-simulator.html's Live tab, but with none of the
// simulator's debug controls and no standalone demo mode, so what's on
// screen here is always exactly what's being broadcast, never
// independently-fetched stand-in data. Meant to run full-screen/unattended
// (e.g. an old phone or tablet mounted as a companion display).
//
// Only receives frames when the display driver is running in --simulate
// mode (matrix_sim.py's WebSocket broadcaster) — the real hardware path
// (rgbmatrix, no --simulate) doesn't broadcast frames anywhere.
//
// Defaults to matrix-display's WebSocket broadcaster, which normally lives
// on the same host as its control server (this page's CONTROL_URL). If
// that's localhost — settings_app.py and matrix_server.py on the same
// machine, the common case — use the browser's own location.hostname
// instead of the literal string "localhost", since that would otherwise
// resolve to whatever device is viewing this page, not the Pi. Override
// with ?ws=ws://host:port or just ?port=NNNN.

const params = new URLSearchParams(location.search);
const defaultWsHost = __WS_DEFAULT_HOST_EXPR__;
const WS_URL = params.get('ws') || 'ws://' + defaultWsHost + ':' + (params.get('port') || '8888');

let COLS = 64, ROWS = 32, SCALE = 10;
const wrap = document.getElementById('wrap');
const canvas = document.getElementById('matrix');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('status');
let fb = [];

function clearFB(){ fb = Array.from({length: ROWS}, () => Array.from({length: COLS}, () => [0, 0, 0])); }
clearFB();

function resize(){
  SCALE = Math.max(2, Math.floor(Math.min(wrap.clientWidth / COLS, wrap.clientHeight / ROWS)));
  canvas.width = COLS * SCALE;
  canvas.height = ROWS * SCALE;
  render();
}

function render(){
  ctx.fillStyle = '#050506';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  const r = SCALE * 0.38;
  for (let y = 0; y < ROWS; y++) {
    for (let x = 0; x < COLS; x++) {
      const p = fb[y][x], pr = p[0], pg = p[1], pb = p[2];
      if (!pr && !pg && !pb) continue;
      const cx = x * SCALE + SCALE / 2, cy = y * SCALE + SCALE / 2;
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, SCALE * 0.9);
      glow.addColorStop(0, 'rgba(' + pr + ',' + pg + ',' + pb + ',0.55)');
      glow.addColorStop(1, 'rgba(' + pr + ',' + pg + ',' + pb + ',0)');
      ctx.fillStyle = glow;
      ctx.fillRect(cx - SCALE, cy - SCALE, SCALE * 2, SCALE * 2);
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgb(' + pr + ',' + pg + ',' + pb + ')';
      ctx.fill();
    }
  }
}

function loadFrame(bytes, w, h){
  if (w !== COLS || h !== ROWS) { COLS = w; ROWS = h; clearFB(); resize(); }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 3;
      fb[y][x] = [bytes[i], bytes[i + 1], bytes[i + 2]];
    }
  }
  render();
}

function b64ToBytes(b64){
  const bin = atob(b64), out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function setStatus(text, isError){
  statusEl.textContent = text;
  statusEl.classList.toggle('err', !!isError);
}

let ws = null, reconnectTimer = null;
function connect(){
  clearTimeout(reconnectTimer);
  setStatus('connecting to ' + WS_URL + ' ...');
  try { ws = new WebSocket(WS_URL); }
  catch (e) { scheduleReconnect(); return; }
  ws.onclose = scheduleReconnect;
  ws.onerror = () => setStatus('connection error', true);
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    if (msg.type === 'hello') {
      COLS = msg.w; ROWS = msg.h; clearFB(); resize();
    } else if (msg.type === 'frame') {
      loadFrame(b64ToBytes(msg.data), msg.w, msg.h);
      setStatus('');
    }
  };
}
function scheduleReconnect(){
  setStatus('disconnected - retrying...', true);
  reconnectTimer = setTimeout(connect, 2000);
}

window.addEventListener('resize', resize);
window.addEventListener('orientationchange', resize);
resize();
connect();
</script>
</body>
</html>
"""


def fetch_config():
    resp = requests.get(f"{CONTROL_URL}/config", timeout=3)
    resp.raise_for_status()
    return resp.json()


@app.route("/")
def index():
    try:
        config = fetch_config()
    except requests.RequestException as e:
        return render_template_string(PAGE, config=None, error=str(e), control_url=CONTROL_URL)
    return render_template_string(PAGE, config=config, error=None, control_url=CONTROL_URL)


@app.route("/message", methods=["POST"])
def message():
    """Forwards {"msg": "..."} to matrix_server.py's control server, which
    keeps it in memory only (see screens/message.py) — nothing here or on
    the display side writes it to disk."""
    body = request.get_json(silent=True) or {}
    resp = requests.post(f"{CONTROL_URL}/message", json={"msg": body.get("msg", "")}, timeout=3)
    return Response(resp.content, status=resp.status_code, mimetype="application/json")


@app.route("/kiosk")
def kiosk():
    control_host = urlparse(CONTROL_URL).hostname or "localhost"
    # If the control server is on localhost, that's this machine, not
    # necessarily the viewer's — resolve it client-side from the URL they
    # actually used to load the page instead of baking in "localhost".
    if control_host in ("localhost", "127.0.0.1", "0.0.0.0"):
        host_expr = "location.hostname"
    else:
        host_expr = json.dumps(control_host)
    page = KIOSK_PAGE.replace("__WS_DEFAULT_HOST_EXPR__", host_expr)
    return Response(page, mimetype="text/html")


@app.route("/save", methods=["POST"])
def save():
    config = fetch_config()
    enabled = request.form.getlist("enabled")
    durations = {}
    for s in config["screens"]:
        raw = request.form.get(f"seconds_{s['name']}", "")
        if raw.strip():
            try:
                durations[s["name"]] = max(1, int(raw))
            except ValueError:
                pass
    requests.post(
        f"{CONTROL_URL}/config",
        json={
            "enabled": enabled,
            "durations": durations,
            "auto_advance": "auto_advance" in request.form,
            "mqtt": mqtt_from_form(request.form),
        },
        timeout=3,
    )
    return redirect(url_for("index"))


def mqtt_from_form(form):
    """MQTT control settings from the settings form — merged into the
    "mqtt" section of the display's screen_config.json (see mqtt_control.py
    for what the fields mean)."""
    try:
        port = int(form.get("mqtt_port", "") or 1883)
        if not 1 <= port <= 65535:
            port = 1883
    except ValueError:
        port = 1883
    return {
        "enabled": "mqtt_enabled" in form,
        "host": form.get("mqtt_host", "").strip(),
        "port": port,
        "device": form.get("mqtt_device", "").strip() or "display1",
        "username": form.get("mqtt_username", ""),
        "password": form.get("mqtt_password", ""),
    }


@click.command
@click.option("--port", type=int, default=8789, help="Port to serve the settings UI on")
@click.option("--control-url", default=None, help="matrix_server.py control server URL (default: $CONTROL_URL or http://localhost:8787)")
def main(port, control_url):
    global CONTROL_URL
    if control_url:
        CONTROL_URL = control_url
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
