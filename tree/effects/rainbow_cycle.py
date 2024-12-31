import time
import adafruit_led_animation.color as color

from colorsys import hsv_to_rgb

from util.tree_animation import TreeAnimation

class RainbowCycle(TreeAnimation):
    def __init__(self, pixel_object, coordinates, speed, frequency, name):
        super().__init__(pixel_object=pixel_object, coordinates=coordinates, speed=speed, color=color.RAINBOW, name=name)
        self.frequency = frequency
        self.start_time = time.monotonic()

    def draw(self):
        elapsed = time.monotonic() - self.start_time
        z_min, z_max = self._bounds[2]
        for i, coord in enumerate(self._coordinates):
            z = (coord[2] - z_min) / (z_max - z_min)
            hue = (z - elapsed * self.frequency) % 1.0
            self.pixel_object[i] = [c * 255 for c in hsv_to_rgb(hue, 1.0, 1.0)]
