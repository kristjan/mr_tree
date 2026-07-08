import time
import math
import random

from util.tree_animation import TreeAnimation

TWO_PI = 2 * math.pi

# Section split and palette (raw RGB; the strand's brightness scaling dims these).
TRUNK_FRACTION = 0.18           # bottom share of tree height treated as trunk
TRUNK_COLOR = (90, 45, 18)      # warm brown
BRANCH_COLOR = (170, 195, 225)  # cool white
PINK = (255, 120, 170)          # cherry-blossom pink


def _lerp(a, b, f):
    return (
        int(a[0] + (b[0] - a[0]) * f),
        int(a[1] + (b[1] - a[1]) * f),
        int(a[2] + (b[2] - a[2]) * f),
    )


class CherryBlossom(TreeAnimation):
    """Trunk in brown, branches in cool white, with a fraction of branch LEDs
    gently twinkling pink (fading white<->pink, staggered out of phase)."""

    def __init__(self, pixel_object, coordinates, speed, name, twinkle_speed=0.5, pink_fraction=0.4):
        super().__init__(pixel_object=pixel_object, coordinates=coordinates, speed=speed, color=PINK, name=name)
        self.twinkle_speed = twinkle_speed    # 0-1 (maps to fade frequency)
        self.pink_fraction = pink_fraction     # 0-1 of branch LEDs that twinkle
        self.start_time = time.monotonic()

        # Per-LED random rank (which branch LEDs turn pink as the fraction grows)
        # and a phase offset so the twinkles are staggered, not synchronized.
        n = len(self._coordinates)
        self._rank = [random.random() for _ in range(n)]
        self._phase = [random.uniform(0, TWO_PI) for _ in range(n)]

        z_min, z_max = self._bounds[2]
        span = (z_max - z_min) or 1
        self._trunk_z = z_min + TRUNK_FRACTION * span

    def draw(self):
        elapsed = time.monotonic() - self.start_time
        freq = 0.1 + self.twinkle_speed * 0.5  # Hz: gentle
        wt = elapsed * freq * TWO_PI
        for i, (x, y, z) in enumerate(self._coordinates):
            if z <= self._trunk_z:
                self.pixel_object[i] = TRUNK_COLOR
            elif self._rank[i] < self.pink_fraction:
                osc = (math.sin(wt + self._phase[i]) + 1) * 0.5
                self.pixel_object[i] = _lerp(BRANCH_COLOR, PINK, osc)
            else:
                self.pixel_object[i] = BRANCH_COLOR
