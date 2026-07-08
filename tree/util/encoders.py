"""Rotary encoder (dial) input layer.

Wraps the three Adafruit I2C QT seesaw rotary encoders behind a small, robust API.
A missing or failed dial is skipped so the tree still runs (over MQTT) without it.
See project/dials.md for the interaction model.
"""

import time

from adafruit_seesaw.seesaw import Seesaw
from adafruit_seesaw.rotaryio import IncrementalEncoder
from adafruit_seesaw.digitalio import DigitalIO
from adafruit_seesaw.neopixel import NeoPixel as SeesawNeoPixel

# Physical positions.
LEFT = 0
CENTER = 1
RIGHT = 2

# Physical left -> center -> right, by I2C address. Reorder after boot calibration
# if the physical dials don't match (see Dials.calibrate).
DIAL_ADDRESSES = [0x36, 0x37, 0x38]

_BUTTON_PIN = 24  # onboard push-button
_PIXEL_PIN = 6    # onboard NeoPixel


class Dial:
    """One rotary encoder: relative turn delta, debounced button edges, onboard LED."""

    def __init__(self, i2c, address):
        self.address = address
        self._seesaw = Seesaw(i2c, address)
        self._seesaw.pin_mode(_BUTTON_PIN, self._seesaw.INPUT_PULLUP)
        self._encoder = IncrementalEncoder(self._seesaw)
        self._button = DigitalIO(self._seesaw, _BUTTON_PIN)
        self.pixel = SeesawNeoPixel(self._seesaw, _PIXEL_PIN, 1)
        self.pixel.brightness = 0.4

        # CW = increase (the raw position counts the other way).
        self._last_position = -self._encoder.position
        self._pressed = self._is_down()
        self._raw_last = self._pressed
        self._last_change = time.monotonic()

    def _is_down(self):
        return not self._button.value  # pressed == value False (INPUT_PULLUP)

    def read_delta(self):
        """Detents turned since the last call (CW positive)."""
        position = -self._encoder.position
        delta = position - self._last_position
        self._last_position = position
        return delta

    def poll_button(self, debounce=0.02):
        """Return 'press', 'release', or None (debounced edge since last call)."""
        raw = self._is_down()
        now = time.monotonic()
        if raw != self._raw_last:
            self._raw_last = raw
            self._last_change = now
            return None
        if (now - self._last_change) >= debounce and raw != self._pressed:
            self._pressed = raw
            return "press" if raw else "release"
        return None

    @property
    def pressed(self):
        return self._pressed

    def set_led(self, color):
        try:
            self.pixel.fill(color)
        except Exception:
            pass  # LED feedback is best-effort; never let it break control


class Dials:
    """The set of dials, indexed by physical position. Missing dials are None."""

    def __init__(self, i2c, addresses=DIAL_ADDRESSES):
        self.dials = []
        for pos, addr in enumerate(addresses):
            try:
                self.dials.append(Dial(i2c, addr))
                print(f"Dial {pos} initialized at {hex(addr)}")
            except Exception as e:
                self.dials.append(None)
                print(f"Dial {pos} at {hex(addr)} not available: {e}")

    @property
    def any_present(self):
        return any(d is not None for d in self.dials)

    def get(self, position):
        return self.dials[position] if 0 <= position < len(self.dials) else None

    def calibrate(self, duration=1.5):
        """Light each present dial L=red, C=green, R=blue and log position->address.

        Watch the physical dials once: leftmost should be red. If not, reorder
        DIAL_ADDRESSES to match.
        """
        colors = [(60, 0, 0), (0, 60, 0), (0, 0, 60)]
        names = ["LEFT (red)", "CENTER (green)", "RIGHT (blue)"]
        for pos, dial in enumerate(self.dials):
            if dial:
                dial.set_led(colors[pos])
                print(f"Calibration: {names[pos]} -> {hex(dial.address)}")
        time.sleep(duration)
        for dial in self.dials:
            if dial:
                dial.set_led((0, 0, 0))
