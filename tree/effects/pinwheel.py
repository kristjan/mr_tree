import time
import math
import adafruit_led_animation.color as color
from colorsys import hsv_to_rgb

from util.tree_animation import TreeAnimation

TWO_PI = 2 * math.pi


class Pinwheel(TreeAnimation):
    """A color wheel spun around the tree's vertical axis (the 'pin' down the trunk).

    Each LED's hue is set by its angle around the central vertical axis, so every
    horizontal slice shows the full wheel; the whole thing rotates over time.
    `repeats` sets how many color cycles go around the circle (integer, for a
    seamless wrap); `rotation_speed` sets how fast it spins.
    """

    def __init__(self, pixel_object, coordinates, speed, name, rotation_speed=0.5, repeats=1):
        super().__init__(pixel_object=pixel_object, coordinates=coordinates, speed=speed, color=color.RAINBOW, name=name)
        self.rotation_speed = rotation_speed   # 0-1
        self.repeats = repeats                  # color cycles around the circle
        self.start_time = time.monotonic()

        # Central vertical axis = centroid of the LEDs in the x-y plane.
        xs = [c[0] for c in self._coordinates]
        ys = [c[1] for c in self._coordinates]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        # Precompute each LED's normalized angle (0-1) around that axis.
        self._angle = [(math.atan2(c[1] - cy, c[0] - cx) / TWO_PI) % 1.0 for c in self._coordinates]

    def draw(self):
        elapsed = time.monotonic() - self.start_time
        offset = elapsed * (0.05 + self.rotation_speed * 0.45)  # revolutions/sec
        reps = self.repeats
        for i in range(len(self._coordinates)):
            hue = (self._angle[i] * reps + offset) % 1.0
            self.pixel_object[i] = [int(c * 255) for c in hsv_to_rgb(hue, 1.0, 1.0)]
