#!/usr/bin/env python3
"""Interactive per-LED capture via the laptop webcam.

Lights each LED on the tree (device /inspect/<i>) and reads its 2D position from
the webcam. Correspondence is perfect (we choose which LED is lit — no decode),
and each LED is verified by median-ing a few frames after it settles. One run =
one camera angle (gives horizontal x + height). Rotate the tree ~90 deg and run
again for the depth axis, then combine.

Must run OUTSIDE the sandbox (needs the camera). Point the laptop camera at the
tree in a dark room.

  venv/bin/python tools/webcam_capture.py --out scratch/view_a.csv
  (options: --host, --port, --cam, --leds, --settle, --frames, --thresh)

Also writes <out>.trace.png — a composite of every LED's detected spot, so the
capture can be eyeballed as a tree before trusting it.
"""
import argparse
import time
from urllib.request import urlopen

import cv2
import numpy as np

OFF = 999999  # out-of-range index -> device lights nothing (all off)


def light(base, i):
    try:
        urlopen(f"{base}/inspect/{i}", timeout=4).read()
    except Exception as e:
        print(f"  inspect {i} error: {e}")


def grab(cap, n):
    out = []
    for _ in range(n):
        ok, f = cap.read()
        if ok:
            out.append(f)
        time.sleep(0.03)
    return out


def brightest_centroid(diff, thresh, min_area):
    m = cv2.morphologyEx((diff > thresh).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, stats, cent = cv2.connectedComponentsWithStats(m, 8)
    best, best_area = None, 0
    for k in range(1, n):
        a = stats[k, cv2.CC_STAT_AREA]
        if a >= min_area and a > best_area:
            best_area, best = a, (float(cent[k][0]), float(cent[k][1]))
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--host", default="mr-tree.local")
    ap.add_argument("--port", type=int, default=7433)
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--leds", type=int, default=100)
    ap.add_argument("--settle", type=float, default=0.25)
    ap.add_argument("--frames", type=int, default=4)
    ap.add_argument("--thresh", type=int, default=50)
    ap.add_argument("--min-area", type=int, default=3)
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"

    cap = cv2.VideoCapture(args.cam)
    if not cap.isOpened():
        raise SystemExit("camera not available")
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # request manual exposure (platform-dependent)
    for _ in range(20):
        cap.read()  # warm up / let exposure settle

    light(base, OFF)
    time.sleep(max(0.4, args.settle))
    dark = cv2.cvtColor(np.median(grab(cap, 5), 0).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.int16)
    trace = np.zeros(dark.shape, np.uint8)

    rows, missing = [], []
    for i in range(args.leds):
        light(base, i)
        time.sleep(args.settle)
        cents = []
        for f in grab(cap, args.frames):
            d = np.clip(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.int16) - dark, 0, 255).astype(np.uint8)
            trace = np.maximum(trace, d)
            c = brightest_centroid(d, args.thresh, args.min_area)
            if c:
                cents.append(c)
        if cents:
            arr = np.array(cents)
            x, y = float(np.median(arr[:, 0])), float(np.median(arr[:, 1]))
            spread = float(np.hypot(*(arr.std(0))))
            rows.append((i, x, y))
            print(f"{i}: ({x:.0f},{y:.0f})  n={len(cents)}  spread={spread:.1f}")
        else:
            missing.append(i)
            print(f"{i}: no blob")

    light(base, OFF)
    try:
        urlopen(f"{base}/inspect/off", timeout=4).read()
    except Exception:
        pass
    cap.release()

    with open(args.out, "w") as fo:
        for i, x, y in rows:
            fo.write(f"{i},{x:.1f},{y:.1f}\n")
    vis = cv2.cvtColor(trace, cv2.COLOR_GRAY2BGR)
    for i, x, y in rows:
        cv2.circle(vis, (int(x), int(y)), 4, (0, 0, 255), 1)
    cv2.imwrite(args.out + ".trace.png", vis)
    print(f"wrote {args.out}: {len(rows)}/{args.leds}; missing {missing}")
    print(f"wrote {args.out}.trace.png (eyeball it — should look like the tree)")


if __name__ == "__main__":
    main()
