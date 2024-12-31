import board
import neopixel
import asyncio

import adafruit_led_animation.color as color
from adafruit_led_animation.animation.rainbow import Rainbow

from effects.rainbow_cycle import RainbowCycle
from effects.sweep import Sweep

class Position:
  LEFT = 0
  CENTER = 1
  RIGHT = 2

class Tree:
  EFFECTS = ["rainbow_cycle", "sweep"]

  def __init__(self):
    self.string = neopixel.NeoPixel(board.A1, 100, brightness=0.2, auto_write=False, pixel_order=neopixel.RGB)
    self.coordinates = self.read_coordinates()
    self.animation = None
    self.on()

  def press(self, button):
    if button == Position.LEFT:
      self.next_animation()

  def turn(self, encoder, diff):
    print(f"Encoder {encoder} turned {diff} steps")

  def on(self):
    self.pause()
    self.string.fill(color.WHITE)
    self.string.show()

  def off(self):
    self.pause()
    self.string.fill(color.BLACK)
    self.string.show()

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
    self.string.brightness = brightness * 0.25
    self.string.show()

  def next_animation(self):
    if not self.animation:
      self.set_animation(self.EFFECTS[0])
    else:
      current = self.EFFECTS.index(self.animation.name)
      next = (current + 1) % len(self.EFFECTS)
      self.set_animation(self.EFFECTS[next])

  def set_animation(self, effect):
    self.pause()
    self.animation = self.load_effect(effect)
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

  def load_effect(self, effect_name: str):
      if effect_name == 'rainbow_cycle':
          # Start with medium speed (frequency = 1.0)
          return RainbowCycle(self.string, self.coordinates, speed=0.01, frequency=1.0, name='rainbow_cycle')
      elif effect_name == "sweep":
          # Start with medium speed (step = 5, lag = 80)
          return Sweep(self.string, coordinates=self.coordinates, color=color.BLUE, speed=0.01, lead=20, lag=80, step=5, name='sweep')
      else:
          raise ValueError(f"Unknown effect: {effect_name}")

  async def animate(self):
    while True:
      if self.animation:
        self.animation.animate()
        await asyncio.sleep(0)
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
    """Return the current state of the tree as a dictionary."""
    pixels = [tuple(p) for p in self.string if any(p)]  # Get all non-black pixels
    current_color = self.calculate_perceived_color(pixels)

    # Convert animation-specific parameters back to 0-1 range
    speed = 0.5  # Default to middle speed
    if self.animation:
      if isinstance(self.animation, RainbowCycle):
        speed = (self.animation.frequency - 0.1) / 1.9
      elif isinstance(self.animation, Sweep):
        speed = (self.animation.step - 1) / 9.0

    return {
      "on": any(pixels),
      "brightness": int((self.string.brightness / 0.25) * 100),  # Convert back to 0-100 range
      "color": {
        "red": current_color[0],
        "green": current_color[1],
        "blue": current_color[2]
      },
      "effect": self.animation.name if self.animation else None,
      "speed": speed,
      "available_effects": self.EFFECTS
    }