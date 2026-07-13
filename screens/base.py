"""Shared display constants and the interface every screen implements."""

WIDTH = 64
HEIGHT = 32
FONT_PATH = "LindenHill-webfont.ttf"


class Screen:
    """Base class for a display screen.

    Subclasses implement `render()`, and optionally `start()` to kick off
    background data refreshes (e.g. polling an API on a timer).
    """
    name = "screen"

    def start(self, stop_event, notify_update):
        """Called once before the display loop begins.

        `stop_event` signals shutdown — background threads should check or
        wait on it. Call `notify_update()` from any thread whenever this
        screen's data changes, to trigger a redraw if it happens to be the
        active screen.
        """
        pass

    def render(self):
        """Return a PIL Image for the current frame, or None if this screen
        has nothing to show yet (the display loop will skip the redraw)."""
        raise NotImplementedError
