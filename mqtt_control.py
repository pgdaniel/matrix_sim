"""MQTT control bus for the matrix display — mirrors the HTTP control
server's screen switching over MQTT, so anything on the LAN that can publish
(a shell script, Home Assistant, mosquitto_pub) can drive the display.

Topics are <device>/<action> (device defaults to "display1"):

    display1/weather    switch to the named screen (same as POST /screen/weather)
    display1/next       advance to the next enabled screen (same as POST /next-screen)
    display1/message    set the message screen's text from the payload, then show it

Payloads are ignored except for "message". Unknown actions are logged and
ignored. Retained messages re-fire on (re)connect, so the display resumes
whatever was last commanded after a restart.

Config (enabled, broker host/port, device name, optional username/password)
lives in the "mqtt" section of screen_config.json, read/written through the
control server's /config endpoint like everything else — see README.md. If
paho-mqtt isn't installed this module still imports fine; the controller
just logs once and stays off.
"""

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
        with self._lock:
            self._client = client
        print(f"[mqtt] connecting to {cfg['host']}:{cfg['port']}, device {cfg['device']!r}")

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties):
        if reason_code.is_failure:
            print(f"[mqtt] connection failed: {reason_code}")
            return
        with self._lock:
            device = self._config["device"]
        client.subscribe(f"{device}/#")
        print(f"[mqtt] connected; subscribed to {device}/#")

    def _on_message(self, _client, _userdata, msg):
        action = msg.topic.split("/")[-1]
        payload = msg.payload.decode("utf-8", "replace").strip()
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
