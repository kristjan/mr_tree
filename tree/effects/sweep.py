from util.axis import Axis
from util.tree_animation import TreeAnimation
from adafruit_led_animation.color import BLACK

Infinity = float('inf')

class Sweep(TreeAnimation):

  def __init__(self, pixel_object, coordinates, color, speed, lead, lag, name, step=2, axes=[Axis.X, Axis.Y, Axis.Z]):
    super().__init__(pixel_object=pixel_object, coordinates=coordinates, speed=speed, color=color, name=name)

    self.axes = axes
    self.step = max(step, 1)
    self.lead = self._clamp(lead, 1, Infinity)
    self.lag = self._clamp(lag, 1, Infinity)
    self._bounds = [[x - self.lead, y + self.lag] for x, y in self._bounds]
    self._colors = [BLACK for _ in self._coordinates]

    self.reset()

  def draw(self):
    coordinates = self._coordinates
    axis = self._axis
    location = self._location
    lead = self.lead
    lag = self.lag
    base_color = self._color
    pixels = self.pixel_object

    for i in range(len(coordinates)):
        diff = coordinates[i][axis] - location

        # Scale cleanup window with step size to ensure we catch all pixels
        cleanup_window = max(5, self.step + 2)
        if -lag <= diff < -lag + cleanup_window:
            self._colors[i] = (0, 0, 0)
            pixels[i] = (0, 0, 0)
            continue

        if diff < -lag or diff > lead:
            continue

        pct = abs(diff) / (lead if diff >= 0 else lag)
        brightness = 1 - min(max(pct, 0), 1)
        if brightness == 0:
            self._colors[i] = (0, 0, 0)
            pixels[i] = (0, 0, 0)
            continue

        this_color = tuple(int(c * brightness) for c in base_color)
        self._colors[i] = this_color

        r, g, b = this_color
        for peer in self.peers + [self]:
            peer_color = peer._colors[i]
            r = max(r, peer_color[0])
            g = max(g, peer_color[1])
            b = max(b, peer_color[2])

        pixels[i] = (r, g, b)


  def after_draw(self):
    self._location += self.step
    if self._location > self._bounds[self._axis][1]:
      next_axis = (self.axes.index(self._axis) + 1) % len(self.axes)
      self._init_axis(self.axes[next_axis])

  def reset(self):
    self._init_axis(self.axes[0])

  def _clamp(self, value, min_value, max_value):
    return max(min(value, max_value), min_value)

  def _init_axis(self, axis):
    self._axis = axis
    self._location = self._bounds[self._axis][0]