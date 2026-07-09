# LED coordinate capture pipeline

How to (re)generate `tree/coordinates.csv` — the 3D `(x,y,z)` position of every
LED — by photographing the tree. Fully scripted; re-run any time we shoot new
video. All scripts live in `tools/` and take the videos as arguments.

## Method

Light one LED at a time and film the tree from several turntable angles. Each
LED's 2D position is found in every angle it's visible in, then triangulated to
3D. One-at-a-time (not binary-coded) because the LEDs are densely wound and
merge when several are lit at once.

## 1. Capture (device)

Trigger the sequence over HTTP; it lights each LED alone with an all-on marker
every 10 LEDs (the markers re-sync the index mapping):

    http://mr-tree.local:7433/capture/singles            # 0.3s/LED, brightness 0.12
    http://mr-tree.local:7433/capture/singles/<dur>/<bright>   # override

Per angle (~53s each):
- **Dark room, phone exposure locked LOW** (pro/manual mode) so each LED is a
  crisp dot, not a bloom. This is the #1 thing to get right — overexposure kills
  the decode.
- Phone **fixed** (tripod/propped); it must not move during a recording.
- Start recording, fire `/capture/singles`, let it finish (dark → flash → 10
  LEDs → flash → …), stop.
- **Rotate the turntable ~90°** and repeat. Do **4 angles** (0/90/180/270).
- Optional: matte black cloth over the glass turntable to kill reflections
  (otherwise the `--crop` handles them).

Drop the four videos in `reference/video/` (gitignored).

## 2. Check one angle

    venv/bin/python tools/triangulate.py diagnose --singles reference/video/<one>.mp4 --crop 0.72

Want: **11 markers** and **~100/100** recovered. Fewer recovered at one angle is
fine if LEDs were occluded — other angles fill them in. If markers ≠ 11 or
recovery is low, adjust `--crop` (fraction of height kept — drop the dial LEDs /
table below the tree) or `--bright` / `--marker-count`.

## 3. Build the coordinates

Pass the videos in **rotation order**:

    venv/bin/python tools/triangulate.py build --singles --crop 0.72 \
        reference/video/<a>.mp4 <b>.mp4 <c>.mp4 <d>.mp4 -o tree/coordinates.csv

Angles default to evenly-spaced over 360°; override with `--angles 0,90,180,270`.
The build auto-corrects for the tree translating vertically as it spins
(off-centre mounting) and interpolates any LED not seen in ≥2 angles from its
strand neighbours.

## 4. View / sanity-check

    venv/bin/python tools/make_viewer.py tree/coordinates.csv scratch/tree_viewer.html
    # open the HTML: drag to rotate, scroll to zoom, space to spin, 'c' recolor

Look for a trunk descending to low z and a canopy spread up top.

## Tuning flags (triangulate.py)

- `--crop F` keep only the top fraction F of the frame (removes the dial LEDs and
  turntable below the tree). Vertical only — the tree is not left/right symmetric,
  so no horizontal cropping.
- `--bright N` near-clipping level (per /8 frame) counted as a lit LED (default 235).
- `--marker-count N` bright-pixel count above which a frame is an all-on marker.
- `--thresh / --min-area / --max-area` blob detection.

## Gotchas learned

- **Exposure is everything.** At 0.25 brightness / auto-exposure the LEDs bloomed
  into one white mass and nothing decoded. Low brightness + locked-low exposure
  gives crisp dots.
- The **dial LEDs on the control box** and the **glass reflection** sit below the
  tree and are persistently bright — `--crop 0.72` removes them.
- The **normal display resuming** after the sequence shows up as one long bright
  run; the decoder rejects markers longer than ~1.5s.
- Rotation need not be perfectly centred — vertical drift is auto-aligned — but
  keep the ~90° steps roughly even.

## Related

- `tools/led_map.py` — separately tag each LED's **section** (trunk/branch/…) by
  lighting it on the tree; writes `tree/sections.csv`. See [[dials]] (cherry
  blossom trunk boundary).
