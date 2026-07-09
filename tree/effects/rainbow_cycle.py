import time
import adafruit_led_animation.color as color

from colorsys import hsv_to_rgb

from util.tree_animation import TreeAnimation
from util.smoothed import Smoothed

class RainbowCycle(TreeAnimation):
    def __init__(self, pixel_object, coordinates, speed, frequency, name, bandwidth=1.0):
        super().__init__(pixel_object=pixel_object, coordinates=coordinates, speed=speed, color=color.RAINBOW, name=name)
        # Scroll rate (cycles/sec) and how many color cycles span the tree height.
        # Both are smoothed so dial/HA changes glide instead of snapping.
        self._frequency = Smoothed(frequency, tau=0.35)
        self._bandwidth = Smoothed(bandwidth, tau=0.35)
        # Accumulate scroll phase incrementally rather than phase = elapsed * freq,
        # so a rate change only alters the future slope — it can't jump the phase.
        self._phase = 0.0
        self._last = time.monotonic()

    @property
    def frequency(self):
        return self._frequency.target

    @frequency.setter
    def frequency(self, value):
        self._frequency.set(value)

    @property
    def bandwidth(self):
        return self._bandwidth.target

    @bandwidth.setter
    def bandwidth(self, value):
        self._bandwidth.set(value)

    def draw(self):
        now = time.monotonic()
        dt = now - self._last
        if dt > 0.1:
            dt = 0.1  # clamp after a pause so the phase doesn't lurch
        self._last = now

        freq = self._frequency.get()
        bw = self._bandwidth.get()
        self._phase = (self._phase + freq * dt) % 1.0

        z_min, z_max = self._bounds[2]
        span = (z_max - z_min) or 1
        for i, coord in enumerate(self._coordinates):
            z = (coord[2] - z_min) / span
            hue = (z * bw - self._phase) % 1.0
            self.pixel_object[i] = [int(c * 255) for c in hsv_to_rgb(hue, 1.0, 1.0)]
