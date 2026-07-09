import time
import math
import random

from util.tree_animation import TreeAnimation
from util.smoothed import Smoothed

TWO_PI = 2 * math.pi

# Section split and palette (raw RGB; the strand's brightness scaling dims these).
# The trunk is the lowest TRUNK_LED_COUNT LEDs by height (matches the timer's
# one-LED-per-minute fill: the trunk fills at ~36 minutes).
TRUNK_LED_COUNT = 36
TRUNK_COLOR = (90, 45, 18)      # warm brown
BRANCH_COLOR = (255, 197, 143)  # warm white (~3000K)
PINK = (255, 40, 110)           # bright, saturated pink


def _lerp(a, b, f):
    return (
        int(a[0] + (b[0] - a[0]) * f),
        int(a[1] + (b[1] - a[1]) * f),
        int(a[2] + (b[2] - a[2]) * f),
    )


class CherryBlossom(TreeAnimation):
    """Trunk in brown, branches in warm white, with a fraction of branch LEDs
    gently twinkling pink (fading white<->pink, staggered out of phase)."""

    def __init__(self, pixel_object, coordinates, speed, name, twinkle_speed=0.5, pink_fraction=0.4):
        super().__init__(pixel_object=pixel_object, coordinates=coordinates, speed=speed, color=PINK, name=name)
        self._twinkle_speed = Smoothed(twinkle_speed, tau=0.35)   # 0-1 -> fade rate
        self._pink_fraction = Smoothed(pink_fraction, tau=0.35)   # 0-1 of branch LEDs
        # Accumulate the twinkle phase incrementally so a speed change doesn't jump it.
        self._wt = 0.0
        self._last = time.monotonic()

        # Per-LED random rank (which branch LEDs turn pink as the fraction grows)
        # and a phase offset so the twinkles are staggered, not synchronized.
        n = len(self._coordinates)
        self._rank = [random.random() for _ in range(n)]
        self._phase = [random.uniform(0, TWO_PI) for _ in range(n)]

        # Trunk = the lowest TRUNK_LED_COUNT LEDs by height.
        order = sorted(range(n), key=lambda i: self._coordinates[i][2])
        self._is_trunk = [False] * n
        for i in order[:TRUNK_LED_COUNT]:
            self._is_trunk[i] = True

    @property
    def twinkle_speed(self):
        return self._twinkle_speed.target

    @twinkle_speed.setter
    def twinkle_speed(self, value):
        self._twinkle_speed.set(value)

    @property
    def pink_fraction(self):
        return self._pink_fraction.target

    @pink_fraction.setter
    def pink_fraction(self, value):
        self._pink_fraction.set(value)

    def draw(self):
        now = time.monotonic()
        dt = now - self._last
        if dt > 0.1:
            dt = 0.1  # clamp after a pause
        self._last = now

        freq = 0.1 + self._twinkle_speed.get() * 0.5  # Hz: gentle
        self._wt = (self._wt + freq * TWO_PI * dt) % TWO_PI
        pink_fraction = self._pink_fraction.get()

        for i in range(len(self._coordinates)):
            if self._is_trunk[i]:
                self.pixel_object[i] = TRUNK_COLOR
            elif self._rank[i] < pink_fraction:
                osc = (math.sin(self._wt + self._phase[i]) + 1) * 0.5
                self.pixel_object[i] = _lerp(BRANCH_COLOR, PINK, osc)
            else:
                self.pixel_object[i] = BRANCH_COLOR
