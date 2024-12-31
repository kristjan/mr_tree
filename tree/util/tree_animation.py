from adafruit_led_animation.animation import Animation

class TreeAnimation(Animation):
  def __init__(self, pixel_object, coordinates, color, speed, name=None):
    super().__init__(pixel_object, speed, color, name=name)
    self._coordinates = coordinates
    self._bounds = self.bounds()

  def bounds(self):
    x, y, z = [
      [i[0] for i in self._coordinates],
      [i[1] for i in self._coordinates],
      [i[2] for i in self._coordinates]
    ]

    return [
      [min(x), max(x)],
      [min(y), max(y)],
      [min(z), max(z)]
    ]