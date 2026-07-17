#!/usr/bin/python3
"""Tiny Flask UI for picking which screens are enabled, whether the display
auto-advances between them, and how many seconds each screen gets before it
does.

This doesn't touch ScreenManager directly — it's a thin form in front of
matrix_server.py's control server (GET/POST /config), the same one
led-matrix-simulator.html's "Next screen" button talks to. That means this
can run as its own process (even its own host) alongside matrix_server.py,
same as matrix-view does for the simulator page.

    python3 settings_app.py                              # UI on :8789, control server on :8787
    CONTROL_URL=http://<host>:8787 python3 settings_app.py --port 8789
"""

import os

import click
import requests
from flask import Flask, redirect, render_template_string, request, url_for

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
  <p><button type="submit">Save</button></p>
</form>
{% endif %}
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
        },
        timeout=3,
    )
    return redirect(url_for("index"))


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
