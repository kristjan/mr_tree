import board
import neopixel
import asyncio
from colorsys import hsv_to_rgb

import adafruit_led_animation.color as color

from effects.rainbow_cycle import RainbowCycle
from effects.sweep import Sweep
from effects.timer import Timer
from effects.cherry_blossom import CherryBlossom
from effects.pinwheel import Pinwheel
from effects.hue_shift import HueShift
from util.transition import Transition

# Default transition durations (seconds). None passed to a setter uses these;
# pass 0 for an instant, snap change (used by the high-frequency dial handlers so
# per-detent edits stay responsive).
FADE_S = 0.6      # crossfade brightness / color
SPROUT_S = 1.2    # turning on: light sprouts from the bottom up
DRAIN_S = 1.0     # turning off: light drains from the branches down the trunk
SPREAD = 0.75     # fraction of a sprout/drain that is spatially staggered

# The 0-255 HA/API brightness maps onto 0..MAX_BRIGHTNESS of the NeoPixel hardware
# range. The cap bounds current draw (and limits the color distortion/voltage droop
# a 100-LED strand shows at full drive); a higher cap also means more distinct output
# levels, so fades band less.
#
# Power budget (shared 5V / 2.4A = 12W supply — strand, board, and dials together):
#   100 LEDs at full white draw ~6.0A at multiplier 1.0 (~60mA each, conservative),
#   scaling ~linearly with the multiplier. Non-strand overhead (ESP32-S3 + WiFi
#   bursts + dials) is ~0.3A. So worst case (full white) at the cap is:
#     0.25 -> 1.8A (75% of supply)      0.30 -> 2.1A (87%)      0.35 -> 2.4A (100%)
#   0.30 keeps ~0.3A of headroom even on the pessimistic 60mA/LED figure (real
#   WS2812Bs draw less), so it is the safe way to reclaim range. See
#   scratch/power_budget.py. Lower this if the strand ever browns out the board.
MAX_BRIGHTNESS = 0.30

class Position:
  LEFT = 0
  CENTER = 1
  RIGHT = 2

class Tree:
  EFFECTS = ["hue_shift", "rainbow_cycle", "cherry_blossom", "pinwheel", "timer"]

  def __init__(self):
    self.string = neopixel.NeoPixel(board.A1, 100, brightness=0.2, auto_write=False, pixel_order=neopixel.RGB)
    self.coordinates = self.read_coordinates()
    self._z_order = None  # pixel indices sorted bottom-to-top, computed on demand
    self._sprout_delays = None  # per-pixel wavefront delays (bottom-up), computed on demand
    self._drain_delays = None   # per-pixel wavefront delays (top-down), computed on demand
    self.animation = None
    self._transition = None     # active Transition, stepped by animate()
    self._power_listeners = []  # fn(on) called when the tree powers on/off
    self._is_on = True          # logical power state (independent of mid-fade brightness)
    self._on_brightness = 0.2   # hardware brightness (0..MAX_BRIGHTNESS) to restore when on
    self._target_brightness = 0.2  # hardware brightness state() reports (the intended value)
    self.previous_brightness = 0.2  # Store initial brightness
    self.on()

  def add_power_listener(self, fn):
    """Register fn(on: bool), invoked whenever the tree powers on or off.

    Used so secondary indicators — the dial encoder LEDs and any onboard status
    LEDs — follow the main strand instead of glowing while the tree is 'off'.
    """
    self._power_listeners.append(fn)

  def _notify_power(self, on):
    for fn in self._power_listeners:
      try:
        fn(on)
      except Exception as e:
        print(f"Power listener error: {e}")

  def press(self, button):
    if button == Position.LEFT:
      self.next_animation()

  def turn(self, encoder, diff):
    print(f"Encoder {encoder} turned {diff} steps")

  def on(self, duration=None):
    """Turn the tree on, sprouting light from the bottom up.

    Restores the previously shown colors (or a default 20% white if the buffer is
    blank) at the on-brightness, revealing them low-to-high along the z axis. Pass
    duration=0 to snap on instantly.
    """
    self._is_on = True
    self._notify_power(True)
    if self.animation:
      self.pause()

    target = self._on_brightness
    self._target_brightness = target
    dur = SPROUT_S if duration is None else duration

    # Snapshot the colors to reveal before we blank the buffer for the sprout.
    if all(self.string[i] == (0, 0, 0) for i in range(len(self.string))):
      target_pixels = (51, 51, 51)  # blank buffer -> default 20% white
      report = (51, 51, 51)
    else:
      target_pixels = [tuple(self.string[i]) for i in range(len(self.string))]
      report = None

    if dur <= 0:
      self._transition = None
      if isinstance(target_pixels, tuple):
        self.string.fill(target_pixels)
      else:
        for i, c in enumerate(target_pixels):
          self.string[i] = c
      self.string.brightness = target
      self.string.show()
      return

    # Start dark at the on-brightness, then ease each pixel up as the wavefront
    # reaches its height. Brightness is held (not ramped) so the reveal is spatial.
    self.string.fill((0, 0, 0))
    self.string.brightness = target
    self.string.show()
    self._transition = Transition(
      self.string, start_pixels=(0, 0, 0), target_pixels=target_pixels,
      start_brightness=target, target_brightness=target, duration=dur,
      spread=SPREAD, delays=self._reveal_delays(reverse=False), owns_pixels=True,
      report_color=report, report_brightness=int(target / MAX_BRIGHTNESS * 255))

  def rainbow_fill(self, duration=None):
    """Sprout a static rainbow gradient from the bottom up.

    The lowest LED is red and the hue climbs to purple at the top, fixed by height
    — the colors don't move, the tree just fills in bottom-to-top like the normal
    sprout. Used as the power-on boot effect before the remembered setting fades in.
    """
    self._is_on = True
    if self.animation:
      self.pause()
    target = self._on_brightness
    self._target_brightness = target
    dur = SPROUT_S if duration is None else duration

    # Target color per pixel: hue 0.0 (red) at the lowest LED climbing to 0.83
    # (purple) at the top, ranked by height so the gradient is even across LEDs.
    order = self._height_order()
    n = len(order)
    target_pixels = [(0, 0, 0)] * n
    for rank, idx in enumerate(order):
      hue = (rank / (n - 1) if n > 1 else 0.0) * 0.83
      r, g, b = hsv_to_rgb(hue, 1.0, 1.0)
      target_pixels[idx] = (int(r * 255), int(g * 255), int(b * 255))

    self.string.fill((0, 0, 0))
    self.string.brightness = target
    self.string.show()
    self._transition = Transition(
      self.string, start_pixels=(0, 0, 0), target_pixels=target_pixels,
      start_brightness=target, target_brightness=target, duration=dur,
      spread=SPREAD, delays=self._reveal_delays(reverse=False), owns_pixels=True)

  def off(self, duration=None):
    """Turn the tree off, draining light out of the branches and down the trunk.

    Preserves the current colors in the buffer (invisible at brightness 0) so the
    next on() re-reveals them. Pass duration=0 to snap off instantly.
    """
    self._is_on = False
    self._notify_power(False)
    if self.animation:
      self.pause()
    self._on_brightness = self._target_brightness
    self.previous_brightness = self._target_brightness
    dur = DRAIN_S if duration is None else duration

    snapshot = [tuple(self.string[i]) for i in range(len(self.string))]

    if dur <= 0:
      self._transition = None
      self.string.brightness = 0
      self.string.show()
      return

    held = self.string.brightness
    self._transition = Transition(
      self.string, start_pixels=snapshot, target_pixels=(0, 0, 0),
      start_brightness=held, target_brightness=held, duration=dur,
      spread=SPREAD, delays=self._reveal_delays(reverse=True), owns_pixels=True,
      on_done=lambda: self._finish_off(snapshot))

  def _finish_off(self, snapshot):
    """Drain complete: restore the buffer colors (for the next on) and go dark."""
    for i, c in enumerate(snapshot):
      self.string[i] = c
    self.string.brightness = 0
    # No show(): the last drained frame is already black on the wire; the restored
    # buffer stays invisible at brightness 0 until on() reveals it.

  def is_on(self):
    """Check whether the tree is logically on (independent of a mid-fade brightness)."""
    return self._is_on

  def set_color(self, color, duration=None):
    """Crossfade the whole strand to a uniform color. Pass duration=0 to snap."""
    self.pause()
    dur = FADE_S if duration is None else duration

    if dur <= 0 or not self._is_on:
      self._transition = None
      self.string.fill(color)
      self.string.show()
      return

    snapshot = [tuple(self.string[i]) for i in range(len(self.string))]
    held = self.string.brightness
    self._transition = Transition(
      self.string, start_pixels=snapshot, target_pixels=color,
      start_brightness=held, target_brightness=held, duration=dur,
      spread=0.0, owns_pixels=True, report_color=color)

  def fill_count(self, n, color):
    """Light exactly the lowest `n` LEDs by height, from the bottom up.

    Used by the dial timer setup so one LED == one minute regardless of the
    tree's non-uniform vertical LED spacing (ranking by z, not a z threshold).
    Stops any running animation so the fill stays put until the timer starts.
    """
    self.pause()
    self._transition = None
    order = self._height_order()
    n = max(0, min(int(n), len(order)))
    self.string.fill((0, 0, 0))
    for idx in order[:n]:
      self.string[idx] = color
    self.string.show()

  def _height_order(self):
    """Pixel indices sorted bottom-to-top by z height; computed once."""
    if self._z_order is None:
      self._z_order = sorted(range(len(self.coordinates)), key=lambda i: self.coordinates[i][2])
    return self._z_order

  def _reveal_delays(self, reverse):
    """Per-pixel wavefront delays (0..1) for a sprout/drain, keyed by z height.

    Bottom-up (reverse=False) lights the lowest LEDs first; top-down (reverse=True)
    drains the branches first. Computed once per direction and cached.
    """
    if reverse and self._drain_delays is not None:
      return self._drain_delays
    if not reverse and self._sprout_delays is not None:
      return self._sprout_delays

    order = self._height_order()
    n = len(order)
    delays = [0.0] * n
    for rank, idx in enumerate(order):
      u = rank / (n - 1) if n > 1 else 0.0
      delays[idx] = (1.0 - u) if reverse else u

    if reverse:
      self._drain_delays = delays
    else:
      self._sprout_delays = delays
    return delays

  def set_brightness(self, brightness, duration=None):
    """Fade the string to a new brightness.

    Args:
        brightness: Value from 0-255 (HA/API range), scaled to the LED string's
            0..MAX_BRIGHTNESS hardware range to bound current draw and distortion.
        duration: seconds to ramp over; None uses FADE_S, 0 snaps instantly.

    A brightness-only fade does not touch the pixel buffer, so it runs alongside a
    live animation. If a pixel transition is already in flight (e.g. a color fade
    from the same HA message), the new brightness target is merged into it.
    """
    hw = brightness / 255 * MAX_BRIGHTNESS
    if hw < 0:
      hw = 0.0
    elif hw > MAX_BRIGHTNESS:
      hw = MAX_BRIGHTNESS
    self._target_brightness = hw
    if self._is_on:
      self._on_brightness = hw

    dur = FADE_S if duration is None else duration

    if not self._is_on or dur <= 0:
      # Off, or an explicit snap: apply immediately. Fold into any live transition
      # so it doesn't overwrite this on its next frame.
      if self._transition and not self._transition.done:
        self._transition.set_brightness_target(hw)
      self.string.brightness = hw
      self.string.show()
      return

    if self._transition and not self._transition.done:
      self._transition.set_brightness_target(hw)
      return

    self._transition = Transition(
      self.string, start_pixels=None, target_pixels=None,
      start_brightness=self.string.brightness, target_brightness=hw,
      duration=dur, owns_pixels=False, report_brightness=brightness)

  def next_animation(self):
    if not self.animation:
      self.set_animation(self.EFFECTS[0])
    else:
      current = self.EFFECTS.index(self.animation.name)
      next = (current + 1) % len(self.EFFECTS)
      self.set_animation(self.EFFECTS[next])

  def set_animation(self, effect, params=None):
    self.pause()
    self._transition = None  # an animation owns the buffer; drop any color fade
    self.animation = self.load_effect(effect, params or {})
    self.resume()

  def pause(self):
    if self.animation:
      self.animation.freeze()

  def cancel_transition(self):
    """Drop any in-flight fade so a caller can take over the buffer immediately."""
    self._transition = None

  def is_transitioning(self):
    """Whether a fade/sprout/drain is currently rendering.

    asyncio is cooperative and single-threaded, so any task that blocks (notably
    the MQTT socket read) stalls the render loop mid-fade and makes the fade step.
    The MQTT task uses this to stand aside for the ~1s a transition takes.
    """
    return self._transition is not None

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
        # Map speed 0-1 to a frequency range, but cap the top: past ~0.6 the scroll
        # looks chaotic, so clamp 8 dial clicks (8 x 0.05 = 0.4) below max speed.
        s = 0.6 if speed > 0.6 else speed
        self.animation.frequency = 0.1 + (s * 1.9)
      elif isinstance(self.animation, Sweep):
        # For Sweep, adjust both step and lag parameters
        # Map 0-1 to step range 1-10
        self.animation.step = 1 + int(speed * 9)
        # Increase lag window size with speed to ensure cleanup
        # At slowest speed (step=1): lag=40
        # At fastest speed (step=10): lag=120
        self.animation.lag = 40 + int(speed * 80)
      elif isinstance(self.animation, CherryBlossom):
        # Twinkle fade rate.
        self.animation.twinkle_speed = speed
      elif isinstance(self.animation, Pinwheel):
        # Rotation rate.
        self.animation.rotation_speed = speed
      elif isinstance(self.animation, HueShift):
        # How fast the bands change color.
        self.animation.shift_speed = speed

      # Keep update speed constant and fast for smooth animation
      self.animation.speed = 0.01

  def set_param(self, value: float):
    """Set the current animation's secondary parameter from a normalized 0..1 value.

    Each effect maps it to its own second control — the same knob the dial's RIGHT
    encoder drives (see Controller._adjust_param): hue_shift color count, rainbow
    color spread, cherry blossom mix, pinwheel arm count. Effects without a second
    parameter ignore it.
    """
    if not self.animation:
      return
    value = 0.0 if value < 0 else 1.0 if value > 1 else value
    if isinstance(self.animation, HueShift):
      self.animation.set_bands(1 + int(round(value * 4)))    # 1..5 colors
    elif isinstance(self.animation, RainbowCycle):
      self.animation.bandwidth = 0.1 + value * 1.9           # 0.1..2.0 cycles/height
    elif isinstance(self.animation, CherryBlossom):
      self.animation.pink_fraction = 0.1 + value * 0.8       # 0.1..0.9 of branches
    elif isinstance(self.animation, Pinwheel):
      self.animation.repeats = 1 + int(round(value * 3))     # 1..4 arms

  def _param_value(self):
    """The current secondary parameter normalized to 0..1 (0.5 if the effect has none)."""
    a = self.animation
    if isinstance(a, HueShift):
      return (a._bands - 1) / 4
    elif isinstance(a, RainbowCycle):
      return (a.bandwidth - 0.1) / 1.9
    elif isinstance(a, CherryBlossom):
      return (a.pink_fraction - 0.1) / 0.8
    elif isinstance(a, Pinwheel):
      return (a.repeats - 1) / 3
    return 0.5

  def load_effect(self, effect_name: str, params=None):
      params = params or {}
      if effect_name == 'hue_shift':
          return HueShift(self.string, self.coordinates, speed=0.01, name='hue_shift', bands=1, shift_speed=0.5)
      elif effect_name == 'rainbow_cycle':
          # Start with medium speed (frequency = 1.0)
          return RainbowCycle(self.string, self.coordinates, speed=0.01, frequency=1.0, name='rainbow_cycle')
      elif effect_name == "sweep":
          # Start with medium speed (step = 5, lag = 80)
          return Sweep(self.string, coordinates=self.coordinates, color=color.BLUE, speed=0.01, lead=20, lag=80, step=5, name='sweep')
      elif effect_name == "cherry_blossom":
          return CherryBlossom(self.string, self.coordinates, speed=0.01, name='cherry_blossom', twinkle_speed=0.5, pink_fraction=0.4)
      elif effect_name == "pinwheel":
          return Pinwheel(self.string, self.coordinates, speed=0.01, name='pinwheel', rotation_speed=0.5, repeats=1)
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
      transitioning = False

      if self._transition is not None:
        transitioning = True
        if self._transition.update():
          on_done = self._transition.on_done
          self._transition = None
          if on_done:
            on_done()

      # A pixel-owning transition freezes the animation (they share the buffer); a
      # brightness-only transition can run concurrently with a live animation.
      animating = self.animation and not self.animation.frozen
      if animating:
        self.animation.animate()

      if transitioning:
        # Fades are subtle, so run them fast: at ~30fps a sprout only gets a
        # handful of frames per pixel and the steps are visible. Position is
        # time-based, so a higher rate just means finer, smoother steps.
        await asyncio.sleep(0.012)  # ~50-60fps
      elif animating:
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
    # While a color transition is mid-fade the buffer holds intermediate values, so
    # report its target; otherwise sample the strand for the perceived color.
    if self._transition is not None and self._transition.report_color is not None:
      perceived_color = self._transition.report_color
    else:
      # Get current color from pixels - avoid creating new list to prevent memory fragmentation
      # Sample a few pixels instead of all 100 to reduce memory usage
      sample_pixels = []
      for i in range(0, len(self.string), max(1, len(self.string) // 10)):  # Sample every 10th pixel
          sample_pixels.append(self.string[i])
      perceived_color = self.calculate_perceived_color(sample_pixels)

    return {
      "state": "ON" if self._is_on else "OFF",
      "brightness": int(self._target_brightness / MAX_BRIGHTNESS * 255),  # hw -> 0-255
      "color": {
        "r": perceived_color[0],
        "g": perceived_color[1],
        "b": perceived_color[2]
      },
      "color_mode": "rgb",
      "effect": self.animation.name if self.animation else None,
      "speed": int(self.animation.speed * 100) if self.animation else 50,
      "param": int(round(self._param_value() * 100)) if self.animation else 50,
      "available_effects": self.EFFECTS,
      "animation_state": "paused" if self.animation and self.animation.frozen else "running"
    }