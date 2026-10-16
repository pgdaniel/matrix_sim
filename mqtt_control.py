"""MQTT control bus for the matrix display — mirrors the HTTP control
server's screen switching over MQTT, so anything on the LAN that can publish
(a shell script, Home Assistant, mosquitto_pub) can drive the display.

Topics are <device>/<action> (device defaults to "display1"):

    display1/weather    switch to the named screen (same as POST /screen/weather)
    display1/next       advance to the next enabled screen (same as POST /next-screen)
    display1/message    set the message screen's text from the payload, then show it
    display1/auto       auto-advance: payload "on", "off" or "toggle" (default)

Payloads are ignored except for "message" and "auto". Unknown actions are
logged and ignored. Retained messages re-fire on (re)connect, so the display
resumes whatever was last commanded after a restart.

The display also reports its state, retained, under <device>/state/ so
controllers (e.g. deckd) can show it:

    display1/state/screen   name of the screen currently showing
    display1/state/auto     "on" or "off" (auto-advance)
    display1/state/screens  JSON list of screen names, in panel order

Config (enabled, broker host/port, device name, optional username/password)
lives in the "mqtt" section of screen_config.json, read/written through the
control server's /config endpoint like everything else — see README.md. If
paho-mqtt isn't installed this module still imports fine; the controller
just logs once and stays off.
"""

import json
import threading

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

DEFAULT_PORT = 1883
DEFAULT_DEVICE = "display1"


class MqttController:
    """Subscribes to <device>/# on a LAN broker and translates messages into
    ScreenManager calls. paho runs its network loop on its own thread; all
    the ScreenManager/MessageScreen methods called from it are thread-safe.
    """

    def __init__(self, screens, config=None):
        self.screens = screens
        self._lock = threading.Lock()
        self._client = None
        self._state_stop = None
        self._last_state = {}
        self._config = {}
        self.update_config(config or {})

    def update_config(self, config):
        """Apply a new config dict (from POST /config or screen_config.json),
        reconnecting only if something actually changed. Unknown keys are
        ignored."""
        if not isinstance(config, dict):
            config = {}
        try:
            port = int(config.get("port", DEFAULT_PORT))
            if not 1 <= port <= 65535:
                port = DEFAULT_PORT
        except (TypeError, ValueError):
            port = DEFAULT_PORT
        new = {
            "enabled": bool(config.get("enabled", False)),
            "host": str(config.get("host") or "").strip(),
            "port": port,
            "device": str(config.get("device") or "").strip().strip("/") or DEFAULT_DEVICE,
            "username": str(config.get("username") or ""),
            "password": str(config.get("password") or ""),
        }
        with self._lock:
            changed = new != self._config
            self._config = new
        if changed:
            self._restart()

    def stop(self):
        """Disconnect and stop paho's network loop, if running."""
        with self._lock:
            client, self._client = self._client, None
            state_stop, self._state_stop = self._state_stop, None
        if state_stop is not None:
            state_stop.set()
        if client is not None:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass

    def _restart(self):
        self.stop()
        with self._lock:
            cfg = dict(self._config)
        if not (cfg["enabled"] and cfg["host"]):
            return
        if mqtt is None:
            print("[mqtt] paho-mqtt is not installed; MQTT control disabled (pip install paho-mqtt)")
            return
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        if cfg["username"]:
            client.username_pw_set(cfg["username"], cfg["password"] or None)
        # connect_async + loop_start: paho keeps retrying in the background
        # if the broker is down, and re-subscribes via on_connect each time.
        client.connect_async(cfg["host"], cfg["port"])
        client.loop_start()
        state_stop = threading.Event()
        with self._lock:
            self._client = client
            self._state_stop = state_stop
        threading.Thread(target=self._state_loop, args=(client, cfg["device"], state_stop), daemon=True).start()
        print(f"[mqtt] connecting to {cfg['host']}:{cfg['port']}, device {cfg['device']!r}")

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties):
        if reason_code.is_failure:
            print(f"[mqtt] connection failed: {reason_code}")
            return
        with self._lock:
            device = self._config["device"]
        client.subscribe(f"{device}/#")
        # Anything published before the (re)connect was lost; send it all again.
        self._last_state = {}
        print(f"[mqtt] connected; subscribed to {device}/#")

    def _state_loop(self, client, device, stop, tick=0.5):
        """Publish screen/auto-advance state, retained, whenever it changes.
        Polling covers every way the state can change (MQTT, HTTP, keyboard,
        auto-advance) without hooking each one."""
        while not stop.wait(tick):
            if not client.is_connected():
                continue
            cfg = self.screens.get_config()
            state = {
                "screen": cfg["current"],
                "auto": "on" if cfg["auto_advance"] else "off",
                "screens": json.dumps([s["name"] for s in cfg["screens"]]),
            }
            for key, value in state.items():
                if self._last_state.get(key) != value:
                    client.publish(f"{device}/state/{key}", value, retain=True)
                    self._last_state[key] = value

    def _on_message(self, _client, _userdata, msg):
        with self._lock:
            device = self._config["device"]
        if msg.topic.startswith(f"{device}/state/"):
            return  # our own retained state coming back, not a command
        action = msg.topic.split("/")[-1]
        payload = msg.payload.decode("utf-8", "replace").strip()
        if action == "auto":
            on = payload.lower() not in ("off", "0", "false") if payload.lower() != "toggle" and payload else not self.screens.auto_advance
            self.screens.set_config(auto_advance=on)
            print(f"[mqtt] {msg.topic} -> auto-advance {'on' if on else 'off'}")
            return
        if action == "next":
            self.screens.next_screen()
            print(f"[mqtt] {msg.topic} -> switched to {self.screens.current.name}")
            return
        if action == "message":
            screen = self.screens.get_screen("message")
            if screen is not None and hasattr(screen, "set_message"):
                screen.set_message(payload)
        if self.screens.show_screen(action):
            print(f"[mqtt] {msg.topic} -> switched to {action}")
        else:
            print(f"[mqtt] ignoring unknown action {action!r} on {msg.topic}")
