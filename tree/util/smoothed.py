"""A scalar that eases toward its target instead of snapping.

Animation params (rainbow bandwidth, twinkle rate, ...) are read every frame in
`draw()`. Setting them directly makes the next frame jump to the new value. Wrap a
param in `Smoothed` and the value glides toward the target with an exponential time
constant, so a dial twist (or an HA change) eases in. Because it always chases the
latest target, spinning a dial continuously produces one smooth ramp rather than a
queue of stepped transitions.

Call `get()` exactly once per frame (it advances by the wall-clock time since the
last call). `set(target)` retargets.
"""

import time
import math


class Smoothed:
    def __init__(self, value, tau=0.35):
        self.value = float(value)
        self.target = float(value)
        self.tau = tau          # seconds to cover ~63% of the remaining distance
        self._last = time.monotonic()

    def set(self, target):
        self.target = float(target)

    def get(self):
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        if self.tau <= 0.0 or dt <= 0.0:
            self.value = self.target
            return self.value
        # Exponential approach: fraction of the remaining gap closed this frame.
        # A long gap (e.g. after the animation was paused) closes ~fully, which is
        # the right behavior — snap to target rather than crawl from a stale value.
        self.value += (self.target - self.value) * (1.0 - math.exp(-dt / self.tau))
        return self.value
