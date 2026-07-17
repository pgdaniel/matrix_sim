import json
import threading
from pathlib import Path

DEFAULT_DURATION = 10  # seconds a screen gets before auto-advance moves on


class ScreenManager:
    """Holds a list of Screen instances, tracks which one is active, and
    whether the active screen needs a redraw.

    Also tracks which screens are enabled, a per-screen auto-advance
    duration, and whether auto-advance is on at all — settings.py (via
    matrix_server.py's control server) reads/writes these through
    get_config()/set_config(), and they're persisted to `config_path` so
    they survive a restart.
    """

    def __init__(self, screens, config_path=None):
        self.screens = screens
        self._by_name = {s.name: s for s in screens}
        self._lock = threading.Lock()
        self._index = 0
        self.dirty = threading.Event()
        self.dirty.set()
        # Set by next_screen(), cleared by the display loop once it has
        # played the transition animation into the newly-current screen.
        self.transition_pending = threading.Event()
        # Last frame actually pushed to the matrix, used as the "from" frame
        # for the transition animation.
        self.last_image = None

        self.config_path = Path(config_path) if config_path else None
        self.enabled = set(self._by_name)
        self.durations = {name: DEFAULT_DURATION for name in self._by_name}
        self.auto_advance = False
        self._load_config()

    @property
    def current(self):
        with self._lock:
            return self.screens[self._index]

    def _enabled_in_order(self):
        """self.screens filtered down to enabled ones, falling back to all
        of them if enabled somehow ends up empty."""
        ordered = [s for s in self.screens if s.name in self.enabled]
        return ordered or self.screens

    def next_screen(self):
        with self._lock:
            ordered = self._enabled_in_order()
            names = [s.name for s in ordered]
            current_name = self.screens[self._index].name
            pos = names.index(current_name) + 1 if current_name in names else 0
            next_name = names[pos % len(names)]
            self._index = self.screens.index(self._by_name[next_name])
        self.transition_pending.set()
        self.dirty.set()

    def get_config(self):
        with self._lock:
            return {
                "screens": [
                    {
                        "name": s.name,
                        "enabled": s.name in self.enabled,
                        "seconds": self.durations.get(s.name, DEFAULT_DURATION),
                    }
                    for s in self.screens
                ],
                "auto_advance": self.auto_advance,
                "current": self.screens[self._index].name,
            }

    def set_config(self, enabled=None, durations=None, auto_advance=None):
        """Update any subset of: which screens are enabled (iterable of
        names), per-screen durations (dict of name -> seconds), and whether
        auto-advance is on. Unknown screen names are ignored."""
        with self._lock:
            if enabled is not None:
                new_enabled = {n for n in enabled if n in self._by_name}
                self.enabled = new_enabled or set(self._by_name)
                if self.screens[self._index].name not in self.enabled:
                    first = next(s for s in self.screens if s.name in self.enabled)
                    self._index = self.screens.index(first)
            if durations is not None:
                for name, seconds in durations.items():
                    if name in self._by_name and isinstance(seconds, (int, float)) and seconds > 0:
                        self.durations[name] = seconds
            if auto_advance is not None:
                self.auto_advance = bool(auto_advance)
        self.transition_pending.set()
        self.dirty.set()
        self._save_config()

    def start_all(self, stop_event):
        for screen in self.screens:
            screen.start(stop_event, self._notify_for(screen))
        threading.Thread(target=self._auto_advance_loop, args=(stop_event,), daemon=True).start()

    def _auto_advance_loop(self, stop_event, tick=0.5):
        """Polls rather than sleeping for the full duration, so a config
        change (new duration, auto-advance toggled off, screen switched
        manually) takes effect within `tick` seconds instead of waiting out
        whatever duration was in effect when the sleep started."""
        elapsed = 0.0
        last_name = None
        while not stop_event.is_set():
            stop_event.wait(tick)
            if stop_event.is_set():
                break
            name = self.current.name
            if name != last_name:
                last_name = name
                elapsed = 0.0
            if not self.auto_advance:
                elapsed = 0.0
                continue
            elapsed += tick
            if elapsed >= self.durations.get(name, DEFAULT_DURATION):
                elapsed = 0.0
                self.next_screen()

    def _notify_for(self, screen):
        def notify_update():
            if self.current is screen:
                self.dirty.set()
        return notify_update

    def _load_config(self):
        if not self.config_path or not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text())
        except (OSError, ValueError) as e:
            print(f"[screens] ignoring unreadable config at {self.config_path}: {e}")
            return
        enabled = {n for n in data.get("enabled", []) if n in self._by_name}
        if enabled:
            self.enabled = enabled
        for name, seconds in data.get("durations", {}).items():
            if name in self._by_name and isinstance(seconds, (int, float)) and seconds > 0:
                self.durations[name] = seconds
        self.auto_advance = bool(data.get("auto_advance", self.auto_advance))

    def _save_config(self):
        if not self.config_path:
            return
        data = {
            "enabled": sorted(self.enabled),
            "durations": self.durations,
            "auto_advance": self.auto_advance,
        }
        try:
            self.config_path.write_text(json.dumps(data, indent=2))
        except OSError as e:
            print(f"[screens] failed to save config to {self.config_path}: {e}")
