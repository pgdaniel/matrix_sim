import threading


class ScreenManager:
    """Holds a list of Screen instances, tracks which one is active, and
    whether the active screen needs a redraw."""

    def __init__(self, screens):
        self.screens = screens
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

    @property
    def current(self):
        with self._lock:
            return self.screens[self._index]

    def next_screen(self):
        with self._lock:
            self._index = (self._index + 1) % len(self.screens)
        self.transition_pending.set()
        self.dirty.set()

    def start_all(self, stop_event):
        for screen in self.screens:
            screen.start(stop_event, self._notify_for(screen))

    def _notify_for(self, screen):
        def notify_update():
            if self.current is screen:
                self.dirty.set()
        return notify_update
