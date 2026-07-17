"""Animated interstitials played when the display switches screens, instead
of cutting straight to the new frame."""

import time

from PIL import Image


def slide_transition(matrix, canvas, old_image, new_image, steps=16, delay=0.02):
    """Slide old_image out to the left while new_image slides in from the
    right, pushing each intermediate frame to the matrix as it goes.

    Returns the fresh canvas to keep rendering into, same contract as
    matrix.SwapOnVSync(). If there's no old_image (e.g. first frame), skips
    straight to new_image.
    """
    if old_image is None:
        canvas.SetImage(new_image)
        return matrix.SwapOnVSync(canvas)

    w, h = new_image.size
    for step in range(1, steps + 1):
        offset = w * step // steps
        frame = Image.new("RGB", (w, h))
        frame.paste(old_image, (-offset, 0))
        frame.paste(new_image, (w - offset, 0))
        canvas.SetImage(frame)
        canvas = matrix.SwapOnVSync(canvas)
        time.sleep(delay)
    return canvas
