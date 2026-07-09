import time
import random
from colorsys import hsv_to_rgb

from util.tree_animation import TreeAnimation
from util.dither import put_dithered

MAX_BANDS = 5
_GOLDEN = 0.6180339887498949  # low-discrepancy per-pixel dither offset


class HueShift(TreeAnimation):
    """Fade the whole tree through colors.

    `bands` sets how many colors are on the tree at once. With 1 band the whole
    tree is a single color that drifts through the hue wheel. With more, each band
    is a color anchor at a fixed height and the tree shows a smooth vertical
    gradient blended between the anchors — the colors fade into each other rather
    than sitting in hard stripes. Each anchor's hue crossfades to a new hue on its
    own staggered timer; the colors never travel up or down the tree.

    The next hue for an anchor is the current one plus a random signed offset
    (never a tiny nudge, never more than a third of the wheel), so there's no
    coherent direction and thus no illusion of motion. Output is dithered so the
    slow fades don't band at low brightness.

    `shift_speed` (0-1) sets how fast the colors change.
    """

    def __init__(self, pixel_object, coordinates, speed, name, bands=1, shift_speed=0.5):
        super().__init__(pixel_object=pixel_object, coordinates=coordinates, speed=speed, color=(255, 0, 0), name=name)
        self.shift_speed = shift_speed  # 0-1, sampled when each anchor picks a new target

        n = len(self._coordinates)
        # Normalized height (0 at the bottom, 1 at the top) per LED, by rank so the
        # gradient is even across LEDs regardless of their vertical spacing.
        order = sorted(range(n), key=lambda i: self._coordinates[i][2])
        self._h = [0.0] * n
        for rank, idx in enumerate(order):
            self._h[idx] = rank / (n - 1) if n > 1 else 0.0
        self._dither = [(i * _GOLDEN) % 1.0 for i in range(n)]

        self._bands = 0
        self._set_bands(bands, seed=True)

    # ---- band setup ---------------------------------------------------

    def _assign_blend(self):
        """For each LED, the two anchors bracketing its height and the blend between
        them (anchor b sits at height (b+0.5)/bands)."""
        n = len(self._h)
        b = self._bands
        self._lo = [0] * n
        self._hi = [0] * n
        self._t = [0.0] * n
        last = b - 1
        for i in range(n):
            pos = self._h[i] * b - 0.5  # fractional anchor index at this height
            if pos <= 0.0:
                self._lo[i] = 0; self._hi[i] = 0; self._t[i] = 0.0
            elif pos >= last:
                self._lo[i] = last; self._hi[i] = last; self._t[i] = 0.0
            else:
                lo = int(pos)
                self._lo[i] = lo; self._hi[i] = lo + 1; self._t[i] = pos - lo

    def _new_dur(self):
        # shift_speed 0 -> ~9s per change, 1 -> ~1.5s, jittered so anchors desync.
        base = 9.0 - self.shift_speed * 7.5
        return base * random.uniform(0.7, 1.3)

    def _next_hue(self, hue):
        # Noticeable but bounded step (|offset| < 0.5 so the shortest path is the
        # intended direction), random sign so anchors don't drift together.
        offset = random.uniform(0.12, 0.5)
        if random.random() < 0.5:
            offset = -offset
        return (hue + offset) % 1.0

    def _set_bands(self, bands, seed=False):
        bands = max(1, min(int(bands), MAX_BANDS))
        if bands == self._bands:
            return
        now = time.monotonic()

        if seed or self._bands == 0:
            frm = [random.random() for _ in range(bands)]
        else:
            # Keep continuity across a count change: seed each new anchor from the
            # color currently shown at its height so the tree doesn't flash-reshuffle.
            old = self._disp
            old_last = self._bands - 1
            frm = []
            for j in range(bands):
                center = (j + 0.5) / bands
                oi = min(old_last, int(center * self._bands))
                frm.append(old[oi])

        self._bands = bands
        self._assign_blend()
        self._disp = list(frm)
        self._frm = list(frm)
        self._to = [self._next_hue(h) for h in frm]
        # Stagger start times so the anchors don't all change at once.
        self._t0 = [now - random.uniform(0.0, 1.0) for _ in range(bands)]
        self._dur = [self._new_dur() for _ in range(bands)]

    def set_bands(self, bands):
        self._set_bands(bands)

    # ---- render -------------------------------------------------------

    def _blend_hue(self, lo, hi, t):
        if lo == hi:
            return self._disp[lo]
        h0 = self._disp[lo]
        d = self._disp[hi] - h0
        if d > 0.5:
            d -= 1.0
        elif d < -0.5:
            d += 1.0
        return (h0 + d * t) % 1.0

    def draw(self):
        now = time.monotonic()

        for b in range(self._bands):
            dur = self._dur[b]
            p = (now - self._t0[b]) / dur if dur > 0 else 1.0
            if p >= 1.0:
                # Arrived: adopt the target and pick the next one.
                self._frm[b] = self._to[b]
                self._to[b] = self._next_hue(self._frm[b])
                self._t0[b] = now
                self._dur[b] = self._new_dur()
                self._disp[b] = self._frm[b]
            else:
                e = p * p * (3.0 - 2.0 * p)
                frm = self._frm[b]
                d = self._to[b] - frm
                if d > 0.5:
                    d -= 1.0
                elif d < -0.5:
                    d += 1.0
                self._disp[b] = (frm + d * e) % 1.0

        px = self.pixel_object
        lo, hi, tt, dither = self._lo, self._hi, self._t, self._dither
        for i in range(len(self._h)):
            hue = self._blend_hue(lo[i], hi[i], tt[i])
            r, g, b = hsv_to_rgb(hue, 1.0, 1.0)
            put_dithered(px, i, (int(r * 255), int(g * 255), int(b * 255)), dither[i])
