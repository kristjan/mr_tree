import time
import math
import random
from colorsys import hsv_to_rgb

from util.tree_animation import TreeAnimation
from util.dither import put_dithered

MAX_MODES = 5
_GOLDEN = 0.6180339887498949  # low-discrepancy per-pixel dither offset
_FOLLOW_TAU = 0.35            # seconds for a segment to ease onto its group's color


class HueShift(TreeAnimation):
    """Fade the tree's structural segments through colors.

    The tree is partitioned into a trunk and four branches (see tree/segments.csv).
    `mode` (1-5) picks how those segments are grouped, and each group carries one
    color that slowly melts to a new random hue on its own staggered clock:

      1  the whole tree is one color
      2  trunk one color, all four branches a second color
      3  trunk one color, plus a color on each opposite branch pair (N+S, E+W)
      4  trunk one color, one opposite pair shares a color, the other two branches
         each get their own
      5  trunk and each of the four branches get their own color

    Colors never travel across the tree; each group melts in place. Every color
    change is eased, and switching modes re-groups without snapping — each segment
    keeps its current on-screen color and eases toward its new group's, so the
    tree always transitions smoothly. Output is dithered so slow fades don't band
    at low brightness.

    `shift_speed` (0-1) sets how fast the colors change.
    """

    def __init__(self, pixel_object, coordinates, segments, speed, name, mode=1, shift_speed=0.5):
        super().__init__(pixel_object=pixel_object, coordinates=coordinates, speed=speed, color=(255, 0, 0), name=name)
        self.shift_speed = shift_speed  # 0-1, sampled when each group picks a new target

        n = len(self._coordinates)
        # Per-LED segment id: 0 = trunk, 1..4 = branches (parallel to coordinates).
        self._seg = [int(segments[i]) if i < len(segments) else 0 for i in range(n)]
        self._dither = [(i * _GOLDEN) % 1.0 for i in range(n)]

        # Order the branch segment ids by their angle around the trunk axis so we
        # can talk about "opposite" pairs (index i and i+2) regardless of how the
        # segmentation happened to number them.
        self._branch_order = self._order_branches()

        # Per-segment currently-shown hue (index by segment id 0..4). This is the
        # continuity layer: it always eases toward its group's color, so nothing
        # snaps when a group's hue changes or when the mode re-groups segments.
        self._seg_disp = [0.0] * 5
        self._last = time.monotonic()

        self._mode = 0
        self._set_mode(mode, seed=True)

    # ---- geometry -----------------------------------------------------

    def _order_branches(self):
        """Branch segment ids sorted by angle around the trunk's x-y centroid."""
        n = len(self._coordinates)
        trunk = [i for i in range(n) if self._seg[i] == 0]
        ref = trunk if trunk else list(range(n))
        tx = sum(self._coordinates[i][0] for i in ref) / len(ref)
        ty = sum(self._coordinates[i][1] for i in ref) / len(ref)

        branches = sorted({self._seg[i] for i in range(n) if self._seg[i] > 0})
        angle = {}
        for b in branches:
            members = [i for i in range(n) if self._seg[i] == b]
            cx = sum(self._coordinates[i][0] for i in members) / len(members)
            cy = sum(self._coordinates[i][1] for i in members) / len(members)
            angle[b] = math.atan2(cy - ty, cx - tx)
        return sorted(branches, key=lambda b: angle[b])

    def _grouping_for(self, mode):
        """Map each segment id (0..4) to a group index for the given mode.

        Group indices are contiguous starting at 0; the number of groups equals
        the number of colors the mode shows.
        """
        g = [0, 0, 0, 0, 0]  # by segment id; trunk (0) stays group 0 in every mode
        o = self._branch_order

        if mode == 1 or not o:
            return [0, 0, 0, 0, 0]
        if mode == 2 or len(o) < 4:
            for b in o:
                g[b] = 1
            return g
        if mode == 3:
            g[o[0]] = g[o[2]] = 1   # one opposite pair
            g[o[1]] = g[o[3]] = 2   # the other opposite pair
        elif mode == 4:
            g[o[0]] = g[o[2]] = 1   # shared opposite pair
            g[o[1]] = 2             # solo branch
            g[o[3]] = 3             # solo branch
        else:  # mode == 5
            g[o[0]] = 1; g[o[1]] = 2; g[o[2]] = 3; g[o[3]] = 4
        return g

    # ---- mode / group setup -------------------------------------------

    def _new_dur(self):
        # shift_speed 0 -> ~9s per change, 1 -> ~1.5s, jittered so groups desync.
        base = 9.0 - self.shift_speed * 7.5
        return base * random.uniform(0.7, 1.3)

    def _next_hue(self, hue):
        # Noticeable but bounded step (|offset| < 0.5 so the shortest path is the
        # intended direction), random sign so groups don't drift together.
        offset = random.uniform(0.12, 0.5)
        if random.random() < 0.5:
            offset = -offset
        return (hue + offset) % 1.0

    def _set_mode(self, mode, seed=False):
        mode = max(1, min(int(mode), MAX_MODES))
        if mode == self._mode and not seed:
            return
        now = time.monotonic()

        group_of = self._grouping_for(mode)
        ngroups = max(group_of) + 1

        if seed:
            # First run: pick random anchors and start every segment on its color
            # so the tree lights up immediately rather than fading in from black.
            anchor = [random.random() for _ in range(ngroups)]
            for s in range(5):
                self._seg_disp[s] = anchor[group_of[s]]
        else:
            # Re-group without a flash: seed each new group from the color one of
            # its segments is currently showing. _seg_disp is left untouched and
            # eases onto the new group colors over the next frames.
            anchor = [None] * ngroups
            for s in range(5):
                gi = group_of[s]
                if anchor[gi] is None:
                    anchor[gi] = self._seg_disp[s]
            anchor = [h if h is not None else random.random() for h in anchor]

        self._mode = mode
        self._group_of = group_of
        self._ngroups = ngroups
        self._anchor = list(anchor)               # current eased hue per group
        self._frm = list(anchor)
        self._to = [self._next_hue(h) for h in anchor]
        # Stagger start times so the groups don't all change at once.
        self._t0 = [now - random.uniform(0.0, 1.0) for _ in range(ngroups)]
        self._dur = [self._new_dur() for _ in range(ngroups)]

    def set_mode(self, mode):
        self._set_mode(mode)

    # ---- render -------------------------------------------------------

    @staticmethod
    def _shortest(delta):
        if delta > 0.5:
            return delta - 1.0
        if delta < -0.5:
            return delta + 1.0
        return delta

    def draw(self):
        now = time.monotonic()

        # 1. Advance each group's anchor along its eased crossfade.
        for g in range(self._ngroups):
            dur = self._dur[g]
            p = (now - self._t0[g]) / dur if dur > 0 else 1.0
            if p >= 1.0:
                # Arrived: adopt the target and pick the next one.
                self._frm[g] = self._to[g]
                self._to[g] = self._next_hue(self._frm[g])
                self._t0[g] = now
                self._dur[g] = self._new_dur()
                self._anchor[g] = self._frm[g]
            else:
                e = p * p * (3.0 - 2.0 * p)
                self._anchor[g] = (self._frm[g] + self._shortest(self._to[g] - self._frm[g]) * e) % 1.0

        # 2. Ease each segment's shown color toward its group's anchor. This is the
        #    continuity layer that keeps mode switches and color changes smooth.
        dt = now - self._last
        self._last = now
        k = 1.0 if dt <= 0.0 else 1.0 - math.exp(-dt / _FOLLOW_TAU)
        for s in range(5):
            tgt = self._anchor[self._group_of[s]]
            self._seg_disp[s] = (self._seg_disp[s] + self._shortest(tgt - self._seg_disp[s]) * k) % 1.0

        # 3. Paint every LED with its segment's current color.
        px = self.pixel_object
        seg, disp, dither = self._seg, self._seg_disp, self._dither
        for i in range(len(seg)):
            r, g, b = hsv_to_rgb(disp[seg[i]], 1.0, 1.0)
            put_dithered(px, i, (int(r * 255), int(g * 255), int(b * 255)), dither[i])
