import board
import neopixel
import asyncio

import adafruit_led_animation.color as color

from effects.rainbow_cycle import RainbowCycle
from effects.sweep import Sweep
from effects.timer import Timer

class Position:
  LEFT = 0
  CENTER = 1
  RIGHT = 2

class Tree:
  EFFECTS = ["rainbow_cycle", "sweep", "timer"]

  def __init__(self):
    self.string = neopixel.NeoPixel(board.A1, 100, brightness=0.2, auto_write=False, pixel_order=neopixel.RGB)
    self.coordinates = self.read_coordinates()
    self.animation = None
    self.previous_brightness = 0.2  # Store initial brightness
    self.on()

  def press(self, button):
    if button == Position.LEFT:
      self.next_animation()

  def turn(self, encoder, diff):
    print(f"Encoder {encoder} turned {diff} steps")

  def on(self):
    """Turn the tree on by restoring previous brightness."""
    # If all pixels are black, set a default color so HA ON command works
    if all(pixel == (0, 0, 0) for pixel in self.string):
      self.string.fill((51, 51, 51))  # 20% white

    self.string.brightness = self.previous_brightness
    self.string.show()
    # Don't automatically resume animations - let them be controlled explicitly

  def off(self):
    """Turn the tree off by setting brightness to 0 while preserving state."""
    if self.animation:
      self.pause()
    self.previous_brightness = self.string.brightness
    self.string.brightness = 0
    self.string.show()

  def is_on(self):
    """Check if the tree is currently on (brightness > 0)."""
    return self.string.brightness > 0

  def set_color(self, color):
    self.pause()
    self.string.fill(color)
    self.string.show()

  def set_brightness(self, brightness):
    """Set the brightness of the LED string.

    Args:
        brightness: Value from 0-1, which will be scaled to 0-0.25 for the LED string
    """
    print(brightness)
    # Scale 0-1 to 0-0.25 to prevent color distortion at high brightness
    self.string.brightness = brightness / 255 * 0.25
    self.string.show()

  def next_animation(self):
    if not self.animation:
      self.set_animation(self.EFFECTS[0])
    else:
      current = self.EFFECTS.index(self.animation.name)
      next = (current + 1) % len(self.EFFECTS)
      self.set_animation(self.EFFECTS[next])

  def set_animation(self, effect, params=None):
    self.pause()
    self.animation = self.load_effect(effect, params or {})
    self.resume()

  def pause(self):
    if self.animation:
      self.animation.freeze()

  def resume(self):
    if self.animation:
      self.animation.resume()

  def set_speed(self, speed: float):
    """Set the speed of the current animation.

    Args:
        speed: Speed value between 0 and 1 (0 = slowest, 1 = fastest)
    """
    if self.animation:
      if isinstance(self.animation, RainbowCycle):
        # For RainbowCycle, adjust the frequency parameter
        # Map 0-1 to frequency range 0.1-2.0
        self.animation.frequency = 0.1 + (speed * 1.9)
      elif isinstance(self.animation, Sweep):
        # For Sweep, adjust both step and lag parameters
        # Map 0-1 to step range 1-10
        self.animation.step = 1 + int(speed * 9)
        # Increase lag window size with speed to ensure cleanup
        # At slowest speed (step=1): lag=40
        # At fastest speed (step=10): lag=120
        self.animation.lag = 40 + int(speed * 80)

      # Keep update speed constant and fast for smooth animation
      self.animation.speed = 0.01

  def load_effect(self, effect_name: str, params=None):
      params = params or {}
      if effect_name == 'rainbow_cycle':
          # Start with medium speed (frequency = 1.0)
          return RainbowCycle(self.string, self.coordinates, speed=0.01, frequency=1.0, name='rainbow_cycle')
      elif effect_name == "sweep":
          # Start with medium speed (step = 5, lag = 80)
          return Sweep(self.string, coordinates=self.coordinates, color=color.BLUE, speed=0.01, lead=20, lag=80, step=5, name='sweep')
      elif effect_name == "timer":
          # Default 5 minute timer if not specified
          duration = int(params.get('duration', 300))
          timer = Timer(self.string, self.coordinates, speed=0.01, duration=duration, name='timer')
          # Don't auto-start the timer - let it be started explicitly
          return timer
      else:
          raise ValueError(f"Unknown effect: {effect_name}")

  async def animate(self):
    while True:
      if self.animation and not self.animation.frozen:
        self.animation.animate()
        await asyncio.sleep(0.033)  # ~30fps is plenty smooth for LED animations
      else:
        await asyncio.sleep(0.3)

  def read_coordinates(self):
      coordinates = []
      with open('coordinates.csv', 'r') as file:
          for line in file:
              values = line.split(',')
              coordinates.append((int(values[0]), int(values[1]), int(values[2])))
      return coordinates

  def calculate_perceived_color(self, pixels):
    """Calculate the perceived dominant color using brightness-weighted average of top 25% brightest pixels.

    Args:
        pixels: List of RGB tuples, each containing (red, green, blue) values

    Returns:
        Tuple of (red, green, blue) representing the perceived color
    """
    if not pixels:
      return (0, 0, 0)

    # Calculate brightness for all pixels
    pixel_brightness = []
    for pixel in pixels:
      brightness = 0.299 * pixel[0] + 0.587 * pixel[1] + 0.114 * pixel[2]
      pixel_brightness.append((brightness, pixel))

    # Sort by brightness and find the threshold (75th percentile)
    pixel_brightness.sort(key=lambda x: x[0])
    threshold_idx = max(0, int(len(pixel_brightness) * 0.75))

    # Calculate weighted average using only pixels above threshold
    total_r, total_g, total_b = 0, 0, 0
    total_weight = 0

    for brightness, pixel in pixel_brightness[threshold_idx:]:
      total_r += pixel[0] * brightness
      total_g += pixel[1] * brightness
      total_b += pixel[2] * brightness
      total_weight += brightness

    if total_weight > 0:
      return (
        int(total_r / total_weight),
        int(total_g / total_weight),
        int(total_b / total_weight)
      )

    return (0, 0, 0)

  def state(self):
    """Get the current state of the tree.

    Returns:
        dict: The current state with the following keys:
            - state: "ON" or "OFF"
            - brightness: 0-255
            - color: dict with r, g, b keys (0-255)
            - effect: current effect name or None
            - speed: current animation speed (0-100)
            - available_effects: list of available effects
            - animation_state: "paused" or "running"
    """
    # Get current color from pixels - avoid creating new list to prevent memory fragmentation
    # Sample a few pixels instead of all 100 to reduce memory usage
    sample_pixels = []
    for i in range(0, len(self.string), max(1, len(self.string) // 10)):  # Sample every 10th pixel
        sample_pixels.append(self.string[i])
    perceived_color = self.calculate_perceived_color(sample_pixels)

    return {
      "state": "ON" if self.string.brightness > 0 else "OFF",
      "brightness": int(self.string.brightness / 0.25 * 255),  # Convert 0-0.25 to 0-255
      "color": {
        "r": perceived_color[0],
        "g": perceived_color[1],
        "b": perceived_color[2]
      },
      "color_mode": "rgb",
      "effect": self.animation.name if self.animation else None,
      "speed": int(self.animation.speed * 100) if self.animation else 50,
      "available_effects": self.EFFECTS,
      "animation_state": "paused" if self.animation and self.animation.frozen else "running"
    }