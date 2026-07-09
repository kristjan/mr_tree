#!/usr/bin/env python3
"""Precompute the trunk + 4-branch segmentation and write tree/segments.csv.

    venv/bin/python tools/gen_segments.py

The device loads the static result (one segment id per line, parallel to
coordinates.csv) instead of recomputing at boot. Re-run this whenever
tree/coordinates.csv or OVERRIDES below changes.

Segmentation: the trunk is the lowest TRUNK_N LEDs by height; the rest (branch
LEDs) are grouped by the direction they point away from the trunk's x-y axis,
cutting at the BRANCHES largest angular gaps. OVERRIDES fix bulbs the geometry
can't classify (chiefly ones sitting on the trunk axis, where their angle is
meaningless). seg = 0 for trunk, 1..BRANCHES for branches.
"""
import math

TRUNK_N = 36
BRANCHES = 4

# index -> segment (0 = trunk, 1..4 = branch). Hand corrections from the viewer.
OVERRIDES = {
    32: 3,   # low on branch 3, sits ~on the trunk axis so its angle is unreliable
}

COORDS = "tree/coordinates.csv"
OUT = "tree/segments.csv"


def compute_segments(coordinates, trunk_n=TRUNK_N, branches=BRANCHES, overrides=OVERRIDES):
    n = len(coordinates)
    order = sorted(range(n), key=lambda i: coordinates[i][2])
    is_trunk = [False] * n
    for i in order[:trunk_n]:
        is_trunk[i] = True

    tx = sum(coordinates[i][0] for i in range(n) if is_trunk[i]) / max(1, trunk_n)
    ty = sum(coordinates[i][1] for i in range(n) if is_trunk[i]) / max(1, trunk_n)

    branch = [i for i in range(n) if not is_trunk[i]]
    two_pi = 2.0 * math.pi
    ang = [0.0] * n
    for i in branch:
        ang[i] = math.atan2(coordinates[i][1] - ty, coordinates[i][0] - tx) % two_pi

    ordered = sorted(branch, key=lambda i: ang[i])
    m = len(ordered)
    gaps = []
    for k in range(m):
        a0 = ang[ordered[k]]
        a1 = ang[ordered[(k + 1) % m]]
        gaps.append(((a1 - a0) % two_pi, a0, a1))
    top = sorted(gaps, key=lambda g: g[0], reverse=True)[:branches]
    cuts = sorted(((a0 + ((a1 - a0) % two_pi) / 2.0) % two_pi) for _, a0, a1 in top)

    seg = [0] * n
    for i in branch:
        c = sum(1 for t in cuts if ang[i] >= t)
        seg[i] = 1 + (c % branches)

    for i, s in overrides.items():
        if 0 <= i < n:
            seg[i] = s
    return seg


def main():
    coords = []
    for line in open(COORDS):
        line = line.strip()
        if line:
            x, y, z = line.split(",")
            coords.append((float(x), float(y), float(z)))

    seg = compute_segments(coords)
    with open(OUT, "w") as f:
        for s in seg:
            f.write(f"{s}\n")

    names = ["trunk", "branch 1", "branch 2", "branch 3", "branch 4"]
    sizes = {names[s]: seg.count(s) for s in range(BRANCHES + 1)}
    print(f"wrote {OUT} ({len(seg)} LEDs)  {sizes}")


if __name__ == "__main__":
    main()
