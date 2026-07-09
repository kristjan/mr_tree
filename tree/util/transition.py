"""Time-based transitions for the LED string.

A `Transition` interpolates the physical NeoPixel output from a start state to a
target state over a fixed duration. The render loop (`Tree.animate`) steps it once
per frame via `update()`; when `update()` returns True the transition is complete.

Two things can be interpolated, independently or together:
- **Per-pixel color** (`owns_pixels=True`): each pixel eases from a start color to
  a target color. A non-zero `spread` staggers the pixels by a precomputed per-pixel
  `delay` (0..1), producing a spatial wavefront — the tree "sprouts" from the bottom
  up when turning on, and "drains" from the top down when turning off. `spread=0`
  fades every pixel in lockstep (a plain crossfade, e.g. red -> green).
- **Global brightness**: a scalar ease from `start_brightness` to `target_brightness`
  on the string's 0-0.25 hardware range. A brightness-only transition
  (`owns_pixels=False`) leaves the pixel buffer alone, so it can run concurrently with
  a live animation without fighting it for the buffer.

Start/target color containers may be a single `(r, g, b)` tuple (uniform, cheap) or a
100-long list (per-pixel snapshot). `report_color` / `report_brightness`, when set,
are what `Tree.state()` reports to Home Assistant so HA sees the *target* immediately
rather than an intermediate frame.
"""

import time


def _ease(p):
    """Smoothstep easing: ease-in/ease-out, gentler than linear at the ends."""
    return p * p * (3.0 - 2.0 * p)


class Transition:
    def __init__(self, string, start_pixels, target_pixels,
                 start_brightness, target_brightness, duration,
                 spread=0.0, delays=None, owns_pixels=False,
                 report_color=None, report_brightness=None, on_done=None):
        self.string = string
        self.start_pixels = start_pixels
        self.target_pixels = target_pixels
        self._start_is_list = isinstance(start_pixels, list)
        self._target_is_list = isinstance(target_pixels, list)
        self.start_brightness = start_brightness
        self.target_brightness = target_brightness
        self.duration = duration
        self.spread = spread
        self.delays = delays
        self.owns_pixels = owns_pixels
        self.report_color = report_color
        self.report_brightness = report_brightness
        self.on_done = on_done
        self.done = False
        self.start_time = time.monotonic()
        # Reused per-pixel write buffer. NeoPixel.__setitem__ copies the values
        # out, so mutating and re-assigning one list avoids allocating a fresh
        # tuple for all 100 pixels every frame (which would churn the GC and show
        # up as visible stutter in the fade).
        self._scratch = [0, 0, 0]

    def set_brightness_target(self, target_brightness):
        """Retarget the brightness ramp mid-flight (e.g. HA sends brightness after
        a color command already kicked off a transition). Rebase the start at the
        current physical brightness so the ramp stays continuous.

        For a brightness-only transition the clock is reset so the new ramp plays
        over the full duration; for a pixel-owning transition (a sprout/color fade)
        the clock is left alone so the spatial reveal keeps its progress and the
        brightness simply eases over whatever time the reveal has left."""
        self.start_brightness = self.string.brightness
        self.target_brightness = target_brightness
        self.report_brightness = int(target_brightness / 0.25 * 255)
        if not self.owns_pixels:
            self.start_time = time.monotonic()

    def _pixel(self, container, is_list, i):
        return container[i] if is_list else container

    def update(self):
        """Advance to the current wall-clock time and write one frame. Returns True
        when the transition has reached its target."""
        if self.duration > 0:
            p = (time.monotonic() - self.start_time) / self.duration
        else:
            p = 1.0
        if p >= 1.0:
            p = 1.0

        if self.owns_pixels:
            inv = 1.0 - self.spread
            plain = self.spread <= 0.0 or inv <= 0.0
            string = self.string
            start, s_list = self.start_pixels, self._start_is_list
            target, t_list = self.target_pixels, self._target_is_list
            delays, spread = self.delays, self.spread
            scratch = self._scratch
            for i in range(len(string)):
                if plain:
                    lp = p
                else:
                    lp = (p - spread * delays[i]) / inv
                    if lp < 0.0:
                        lp = 0.0
                    elif lp > 1.0:
                        lp = 1.0
                e = lp * lp * (3.0 - 2.0 * lp)
                s = start[i] if s_list else start
                t = target[i] if t_list else target
                scratch[0] = int(s[0] + (t[0] - s[0]) * e)
                scratch[1] = int(s[1] + (t[1] - s[1]) * e)
                scratch[2] = int(s[2] + (t[2] - s[2]) * e)
                string[i] = scratch

        if self.start_brightness != self.target_brightness:
            e = _ease(p)
            self.string.brightness = (
                self.start_brightness
                + (self.target_brightness - self.start_brightness) * e
            )

        self.string.show()
        self.done = p >= 1.0
        return self.done
