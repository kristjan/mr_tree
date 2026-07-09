#!/usr/bin/env python3
"""Photogrammetry pipeline for Mr Tree: decode binary-coded capture videos into
3D LED coordinates.

Each video (one per turntable angle) records the device's /capture sequence:
two all-on marker frames bracket N bit-frames (frame k lights the LEDs whose
index has bit k set). This tool segments each video by brightness, decodes each
LED's on/off pattern across the bit-frames to its index, and (for `build`)
triangulates the angles into a coordinates CSV.

Commands:
  diagnose VIDEO
      Segment + decode one video and report how many LED indices came back
      cleanly (the quick check that a capture is good enough to use).

  build [options] VIDEO [VIDEO ...]
      Full pipeline over the per-angle videos.
      --angles a,b,...  angle in degrees per video (default: evenly spaced / 360)
      -o PATH           output CSV (default: tree/coordinates.csv)

Tuning flags (both commands):
  --thresh N     brightness over the dark reference to count a pixel lit (default 45)
  --min-area N   minimum blob area in pixels (default 3)
  --max-area N   maximum blob area in pixels (default 6000)
  --cluster-r N  max pixel distance to merge detections into one LED (default 20)
  --leds N       expected LED count (default 100)

Examples:
  venv/bin/python tools/triangulate.py diagnose reference/video/angle0.mp4
  venv/bin/python tools/triangulate.py build reference/video/*.mp4
"""
import argparse
import math
import sys

import cv2
import numpy as np


def nbits(n):
    b = 1
    while (1 << b) < n:
        b += 1
    return b


def brightness_signal(path, scale=8):
    cap = cv2.VideoCapture(path)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    b = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        s = cv2.resize(f, (max(1, w // scale), max(1, h // scale)))
        b.append(float(cv2.cvtColor(s, cv2.COLOR_BGR2GRAY).mean()))
    cap.release()
    return np.array(b), fps, (w, h)


def find_runs(b, min_len=5):
    lo, hi = b.min(), b.max()
    thr = lo + 0.30 * (hi - lo)
    runs = []
    i = 0
    while i < len(b):
        if b[i] >= thr:
            j = i
            while j < len(b) and b[j] >= thr:
                j += 1
            if j - i >= min_len:
                runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def segment(path, bits):
    """Locate the dark reference, two markers, and the ordered bit-frames."""
    b, fps, size = brightness_signal(path)
    runs = find_runs(b)
    if len(runs) < bits + 2:
        raise RuntimeError(f"{path}: only {len(runs)} lit runs found; need >= {bits + 2}. "
                           "Check the capture played fully and is in frame.")
    peaks = sorted(((b[a:c].max(), i) for i, (a, c) in enumerate(runs)), reverse=True)
    m1, m2 = sorted([peaks[0][1], peaks[1][1]])
    between = list(range(m1 + 1, m2))
    if len(between) != bits:
        raise RuntimeError(f"{path}: the two brightest runs bracket {len(between)} runs, "
                           f"expected {bits} bit-frames.")

    def mid(i):
        a, c = runs[i]
        return (a + c) // 2

    dark_idx = max(0, runs[m1][0] - int(0.2 * fps))
    return {
        "path": path, "fps": fps, "size": size, "dark": dark_idx,
        "markers": (mid(m1), mid(m2)),
        "bits": [mid(i) for i in between],
    }


def grab(path, indices):
    want = sorted(set(indices))
    out = {}
    cap = cv2.VideoCapture(path)
    i = wi = 0
    while wi < len(want):
        ok, f = cap.read()
        if not ok:
            break
        if i == want[wi]:
            out[i] = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
            wi += 1
        i += 1
    cap.release()
    return out


def blobs(diff, thresh, min_area, max_area):
    mask = (diff > thresh).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, stats, cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    pts = []
    for k in range(1, n):
        area = stats[k, cv2.CC_STAT_AREA]
        if min_area <= area <= max_area:
            pts.append((float(cent[k][0]), float(cent[k][1])))
    return pts


def decode_view(seg, args):
    """Return {index: (u, v)} plus stats for one video."""
    frames = grab(seg["path"], [seg["dark"], *seg["markers"], *seg["bits"]])
    dark = frames[seg["dark"]]
    dets = []
    per_bit = []
    H = dark.shape[0]
    crop_y = int(args.crop * H)
    for k, fi in enumerate(seg["bits"]):
        d = np.clip(frames[fi] - dark, 0, 255)
        d[crop_y:, :] = 0  # drop turntable reflection / base below crop line
        pts = blobs(d, args.thresh, args.min_area, args.max_area)
        per_bit.append(len(pts))
        for (x, y) in pts:
            dets.append((x, y, k))

    clusters = []
    r2 = args.cluster_r ** 2
    for (x, y, k) in dets:
        best, bestd = None, r2
        for c in clusters:
            dd = (c["x"] - x) ** 2 + (c["y"] - y) ** 2
            if dd < bestd:
                best, bestd = c, dd
        if best is None:
            clusters.append({"x": x, "y": y, "n": 1, "bits": {k}})
        else:
            best["x"] = (best["x"] * best["n"] + x) / (best["n"] + 1)
            best["y"] = (best["y"] * best["n"] + y) / (best["n"] + 1)
            best["n"] += 1
            best["bits"].add(k)

    result, dupes = {}, 0
    for c in clusters:
        idx = sum(1 << k for k in c["bits"])
        if 0 <= idx < args.leds:
            if idx in result:
                dupes += 1
            result[idx] = (c["x"], c["y"])
    return result, {"clusters": len(clusters), "dupes": dupes, "per_bit": per_bit}


def brightest_blob(d, thresh, min_area, max_area):
    """Centroid of the largest connected component above threshold, or None."""
    mask = cv2.morphologyEx((d > thresh).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, _, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    best, best_area = None, 0
    for k in range(1, n):
        a = stats[k, cv2.CC_STAT_AREA]
        if min_area <= a <= max_area and a > best_area:
            best_area, best = a, (float(cent[k][0]), float(cent[k][1]))
    return best


def count_signal(path, crop, bright, scale=8):
    """Per-frame count of bright (>bright) pixels above the crop line.

    Single LEDs barely move mean brightness, but they add a clear cluster of
    near-clipping pixels; dark gaps go to ~zero once the dial LEDs / table below
    the tree are cropped away. This is what makes single-LED frames separable.
    """
    cap = cv2.VideoCapture(path)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    sig = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        s = cv2.resize(f, (max(1, w // scale), max(1, h // scale)))
        g = cv2.cvtColor(s, cv2.COLOR_BGR2GRAY)
        g[int(crop * g.shape[0]):, :] = 0
        sig.append(int((g > bright).sum()))
    cap.release()
    return np.array(sig), fps, (w, h)


def decode_view_singles(path, args):
    """Decode a one-LED-at-a-time video via marker-anchored timing: {index:(u,v)}.

    All-on markers bracket each decade of 10 single-LED frames. We locate the
    markers, then sample the 10 evenly-spaced LED slots between consecutive
    markers. An LED occluded at this angle yields no blob for its slot but does
    not shift the others, so per-view coverage can be partial and still correct.
    """
    sig, fps, size = count_signal(path, args.crop, args.bright)

    # bright runs whose peak clears the marker threshold = all-on markers
    markers = []
    i = 0
    while i < len(sig):
        if sig[i] > 0:
            j = i
            while j < len(sig) and sig[j] > 0:
                j += 1
            # real markers are brief (~0.6s); reject the long bright run of the
            # normal display resuming after the sequence ends.
            if 2 <= (j - i) < 1.5 * fps and int(sig[i:j].max()) > args.marker_count:
                markers.append([i, j])
            i = j
        else:
            i += 1
    # merge markers split by a momentary dip
    merged = []
    for m in markers:
        if merged and m[0] - merged[-1][1] < int(0.3 * fps):
            merged[-1][1] = m[1]
        else:
            merged.append(m)
    markers = merged

    # sample the 10 LED slots between each consecutive marker pair (cap to the
    # real decade count so any stray trailing marker can't add phantom slots)
    samples = []  # (led_index, frame_index)
    max_intervals = (args.leds + 9) // 10
    for d in range(min(len(markers) - 1, max_intervals)):
        a, b = markers[d][1], markers[d + 1][0]
        for j in range(10):
            samples.append((d * 10 + j, int(a + (b - a) * (j + 0.5) / 10)))

    dark_i = int(np.argmin(sig))
    frames = grab(path, [dark_i] + [f for _, f in samples])
    dark = frames[dark_i]
    crop_y = int(args.crop * dark.shape[0])

    result = {}
    for idx, fi in samples:
        if not (0 <= idx < args.leds):
            continue
        d = np.clip(frames[fi] - dark, 0, 255).astype(np.uint8)
        d[crop_y:, :] = 0
        pt = brightest_blob(d, args.thresh, args.min_area, args.max_area)
        if pt is not None:
            result[idx] = pt
    return result, {"markers": len(markers), "intervals": max(0, len(markers) - 1),
                    "recovered": len(result)}


def cmd_diagnose(args):
    if args.singles:
        result, stats = decode_view_singles(args.video, args)
        print(f"{args.video}: singles mode")
        print(f"  markers found: {stats['markers']} (want 11)  ->  {stats['intervals']} decades")
        got = sorted(result)
        missing = [i for i in range(args.leds) if i not in result]
        print(f"  recovered {len(got)}/{args.leds} at this angle; missing {len(missing)}: {missing[:20]}")
        if stats['markers'] != 11:
            print(f"  ** expected 11 markers (10 decades of 10 + end); got {stats['markers']}. "
                  "Adjust --marker-count or --crop, or a marker split/merged.")
        return
    bits = nbits(args.leds)
    seg = segment(args.video, bits)
    print(f"{args.video}: {seg['size'][0]}x{seg['size'][1]} @ {seg['fps']:.1f}fps")
    print(f"  markers at frames {seg['markers']}, {len(seg['bits'])} bit-frames")
    result, stats = decode_view(seg, args)
    print(f"  blobs per bit-frame: {stats['per_bit']}")
    print(f"  clusters: {stats['clusters']}  dupes: {stats['dupes']}")
    got = sorted(result)
    missing = [i for i in range(args.leds) if i not in result]
    print(f"  recovered {len(got)}/{args.leds} indices; missing {len(missing)}: {missing[:20]}")
    if len(got) < args.leds * 0.8:
        print("  ** LOW recovery — likely overexposed/bloomed or mis-tuned. "
              "Lower capture brightness / lock phone exposure, or adjust --thresh/--cluster-r.")


def solve_xy(measures, u0=None):
    """measures: list of (angle_rad, u). Fit u = u0 + P cos + Q sin. Return (P,Q,u0)."""
    rows, rhs = [], []
    for th, u in measures:
        if u0 is None:
            rows.append([1.0, math.cos(th), math.sin(th)])
        else:
            rows.append([math.cos(th), math.sin(th)])
        rhs.append(u - (0.0 if u0 is None else u0))
    sol, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
    if u0 is None:
        return sol[1], sol[2], sol[0]
    return sol[0], sol[1], u0


def cmd_build(args):
    bits = nbits(args.leds)
    videos = args.videos
    if args.angles:
        angles = [float(a) for a in args.angles.split(",")]
    else:
        angles = [360.0 * k / len(videos) for k in range(len(videos))]
    if len(angles) != len(videos):
        sys.exit("angle count must match video count")

    # decode every view
    views = []  # (angle_rad, {index: (u, v)})
    for path, ang in zip(videos, angles):
        if args.singles:
            result, _ = decode_view_singles(path, args)
        else:
            result, _ = decode_view(segment(path, bits), args)
        views.append((math.radians(ang), result))
        print(f"{path}: angle {ang:.0f}  recovered {len(result)}/{args.leds}")

    # Vertical alignment: the (slightly off-centre) tree translates up/down in the
    # frame as it spins, but a given LED's true height is rotation-invariant. Solve
    # a per-view v-offset so the same LEDs line up in height across views.
    offsets = [0.0] * len(views)
    for _ in range(6):
        acc, cnt = {}, {}
        for vi, (_, res) in enumerate(views):
            for i, (_, v) in res.items():
                acc[i] = acc.get(i, 0.0) + (v - offsets[vi])
                cnt[i] = cnt.get(i, 0) + 1
        led_mean = {i: acc[i] / cnt[i] for i in acc}
        new = [float(np.median([v - led_mean[i] for i, (_, v) in res.items()]))
               for (_, res) in views]
        m = float(np.mean(new))
        offsets = [o - m for o in new]

    # index -> list of (angle_rad, u, aligned_v)
    meas = {i: [] for i in range(args.leds)}
    for vi, (th, res) in enumerate(views):
        for i, (u, v) in res.items():
            meas[i].append((th, u, v - offsets[vi]))

    # global rotation-axis column from well-observed LEDs (>=3 views)
    u0s = []
    for i, ms in meas.items():
        if len(ms) >= 3:
            _, _, u0 = solve_xy([(t, u) for (t, u, _) in ms])
            u0s.append(u0)
    u0 = float(np.median(u0s)) if u0s else 0.0

    xs, ys, zs, solved = [0.0] * args.leds, [0.0] * args.leds, [0.0] * args.leds, [False] * args.leds
    for i, ms in meas.items():
        if len(ms) >= 2:
            P, Q, _ = solve_xy([(t, u) for (t, u, _) in ms], u0=u0)
            xs[i], ys[i] = P, Q
            zs[i] = float(np.mean([v for (_, _, v) in ms]))
            solved[i] = True

    n_solved = sum(solved)
    print(f"solved {n_solved}/{args.leds} LEDs (>=2 views)")

    # interpolate any unsolved LEDs from strand neighbours
    for i in range(args.leds):
        if not solved[i]:
            lo = next((j for j in range(i - 1, -1, -1) if solved[j]), None)
            hi = next((j for j in range(i + 1, args.leds) if solved[j]), None)
            if lo is not None and hi is not None:
                t = (i - lo) / (hi - lo)
                xs[i] = xs[lo] + t * (xs[hi] - xs[lo])
                ys[i] = ys[lo] + t * (ys[hi] - ys[lo])
                zs[i] = zs[lo] + t * (zs[hi] - zs[lo])
            elif lo is not None:
                xs[i], ys[i], zs[i] = xs[lo], ys[lo], zs[lo]
            elif hi is not None:
                xs[i], ys[i], zs[i] = xs[hi], ys[hi], zs[hi]
            print(f"  interpolated LED {i} (was unsolved)")

    # image y grows downward -> flip so larger z = higher; then scale each axis to 0..100
    zs = [-z for z in zs]

    def norm(vals):
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        return [int(round((v - lo) / span * 100)) for v in vals]

    X, Y, Z = norm(xs), norm(ys), norm(zs)
    with open(args.out, "w") as f:
        for i in range(args.leds):
            f.write(f"{X[i]},{Y[i]},{Z[i]}\n")
    print(f"wrote {args.out} ({args.leds} rows)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--thresh", type=int, default=45)
        p.add_argument("--min-area", type=int, default=3)
        p.add_argument("--max-area", type=int, default=6000)
        p.add_argument("--cluster-r", type=int, default=20)
        p.add_argument("--crop", type=float, default=1.0,
                       help="ignore image below this fraction of height (drops turntable reflection)")
        p.add_argument("--singles", action="store_true",
                       help="decode a one-LED-at-a-time capture (/capture/singles) instead of binary")
        p.add_argument("--bright", type=int, default=235,
                       help="singles: near-clipping pixel level counted as lit (per /8 frame)")
        p.add_argument("--marker-count", type=int, default=1000,
                       help="singles: bright-pixel count above which a frame is an all-on marker")
        p.add_argument("--leds", type=int, default=100)

    d = sub.add_parser("diagnose")
    d.add_argument("video")
    common(d)
    d.set_defaults(func=cmd_diagnose)

    b = sub.add_parser("build")
    b.add_argument("videos", nargs="+")
    b.add_argument("--angles", default=None)
    b.add_argument("-o", "--out", default="tree/coordinates.csv")
    common(b)
    b.set_defaults(func=cmd_build)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
