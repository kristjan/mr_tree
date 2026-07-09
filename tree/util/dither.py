"""Ordered dithering for a single pixel write, shared by slow color effects.

NeoPixel applies brightness as `output = int(value * brightness)`, so at the tree's
usual low brightness a channel only has ~16-19 distinct output levels and a slow
color fade shows visible steps. `put_dithered` rounds each channel's physical output
up or down against a per-pixel threshold, so neighbouring LEDs land on different
levels and the eye averages the strand to a far finer color — the same technique
`util/transition.py` uses for fades, exposed for animations that fade colors slowly.

Pass a stable per-pixel `threshold` in [0, 1) (e.g. a golden-ratio sequence over the
strand); the channels are offset internally so the dither noise stays neutral.
"""

_scratch = [0, 0, 0]


def put_dithered(pixels, i, rgb, threshold):
    br = pixels.brightness
    if br <= 0.0:
        pixels[i] = rgb
        return
    inv = 1.0 / br
    s = _scratch
    t = threshold
    for c in range(3):
        d = rgb[c] * br
        lo = int(d)
        o = lo + 1 if (d - lo) > t else lo
        v = int((o + 0.5) * inv)
        s[c] = 255 if v > 255 else v
        t += 0.333
        if t > 1.0:
            t -= 1.0
    pixels[i] = s
