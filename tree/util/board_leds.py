"""Onboard status LEDs on the microcontroller itself.

These are the LEDs physically on the board (the CircuitPython status NeoPixel/
DotStar and a plain `board.LED`), distinct from the tree strand (`board.A1`) and
the seesaw dial encoders. The app never uses them to display anything, but the
CircuitPython runtime can leave the status pixel lit with a leftover color, which
reads as "the board is glowing" even when the tree is off.

`BoardLeds` acquires whatever onboard LEDs the board exposes and keeps them dark:
once at startup and again whenever the tree powers off (via a power listener).

Deliberately NOT touched: `NEOPIXEL_POWER` / `NEOPIXEL_I2C_POWER` gate pins. On
several of these boards that same rail powers the STEMMA-QT I2C bus the dials run
on, so toggling it to reach the onboard pixel would kill the encoders. We only
drive the LED data pins, which is safe.
"""

import board


class BoardLeds:
    def __init__(self):
        self._pixels = []   # addressable onboard LEDs (NeoPixel/DotStar)
        self._digital = []  # simple on/off onboard LEDs
        self._acquire()
        self.off()

    def _acquire(self):
        # Addressable onboard RGB indicator (name varies by board).
        pin = getattr(board, "NEOPIXEL", None)
        if pin is not None:
            try:
                import neopixel
                self._pixels.append(neopixel.NeoPixel(pin, 1, brightness=0.0, auto_write=False))
                print("BoardLeds: onboard NEOPIXEL acquired")
            except Exception as e:
                print(f"BoardLeds: NEOPIXEL unavailable: {e}")

        pin = getattr(board, "DOTSTAR_CLOCK", None) or getattr(board, "APA102_SCK", None)
        if pin is not None:
            try:
                import adafruit_dotstar
                data = getattr(board, "DOTSTAR_DATA", None) or getattr(board, "APA102_MOSI", None)
                self._pixels.append(adafruit_dotstar.DotStar(pin, data, 1, brightness=0.0, auto_write=False))
                print("BoardLeds: onboard DotStar acquired")
            except Exception as e:
                print(f"BoardLeds: DotStar unavailable: {e}")

        # Plain single-color status LED, if present.
        pin = getattr(board, "LED", None)
        if pin is not None:
            try:
                import digitalio
                led = digitalio.DigitalInOut(pin)
                led.direction = digitalio.Direction.OUTPUT
                self._digital.append(led)
                print("BoardLeds: onboard LED acquired")
            except Exception as e:
                print(f"BoardLeds: LED unavailable: {e}")

    def off(self):
        """Force every acquired onboard LED dark. Best-effort per LED."""
        for px in self._pixels:
            try:
                px.fill((0, 0, 0))
                px.show()
            except Exception as e:
                print(f"BoardLeds: pixel off failed: {e}")
        for led in self._digital:
            try:
                led.value = False
            except Exception as e:
                print(f"BoardLeds: LED off failed: {e}")

    def set_power(self, on):
        """Power listener. Onboard indicators are status-only, so there is nothing
        to light on power-on; on power-off we re-assert dark in case the runtime
        relit the status pixel."""
        if not on:
            self.off()
