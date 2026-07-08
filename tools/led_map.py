#!/usr/bin/env python3
"""Interactive LED mapper for Mr Tree.

Walks the strand one LED at a time, lighting each on the physical tree (via the
device's /inspect endpoint) so you can tag its section and fix bad coordinates.
Saves to tree/sections.csv (index,section) and rewrites tree/coordinates.csv.
Re-run any time to resume — existing tags are loaded.

Usage:
  python tools/led_map.py [--host mr-tree.local] [--port 7433]
  (pass --host 192.168.50.100 if mDNS doesn't resolve)

At the prompt the current LED is lit white on the tree. Commands:
  <name>             tag current LED with a section (e.g. trunk), then advance
  <Enter>            reuse the last section for current LED, then advance
  :n / :p            next / previous LED (no tag)
  :j <i>             jump to LED i
  :c <x> <y> <z>     correct current LED's coordinate
  :r <a> <b> <name>  tag an inclusive range a..b
  :u                 clear current LED's tag
  :list              show counts per section and how many remain untagged
  :s                 save now
  :q                 save and quit
  :help              show this help
"""
import argparse
import json
import os
import sys
from urllib.request import urlopen

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COORDS = os.path.join(REPO, "tree", "coordinates.csv")
SECTIONS = os.path.join(REPO, "tree", "sections.csv")


def load_coords():
    coords = []
    with open(COORDS) as f:
        for line in f:
            line = line.strip()
            if line:
                x, y, z = line.split(",")
                coords.append([int(x), int(y), int(z)])
    return coords


def save_coords(coords):
    with open(COORDS, "w") as f:
        for x, y, z in coords:
            f.write(f"{x},{y},{z}\n")


def load_sections():
    s = {}
    if os.path.exists(SECTIONS):
        with open(SECTIONS) as f:
            for line in f:
                line = line.strip()
                if line:
                    idx, name = line.split(",", 1)
                    s[int(idx)] = name
    return s


def save_sections(sections):
    with open(SECTIONS, "w") as f:
        for idx in sorted(sections):
            f.write(f"{idx},{sections[idx]}\n")


def get(base, path):
    try:
        with urlopen(f"{base}{path}", timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  ! request {path} failed: {e}")
        return None


def show_summary(sections, n):
    counts = {}
    for name in sections.values():
        counts[name] = counts.get(name, 0) + 1
    print(f"  tagged {len(sections)}/{n}:")
    for name in sorted(counts):
        print(f"    {name}: {counts[name]}")
    untagged = [i for i in range(n) if i not in sections]
    if untagged:
        print(f"    untagged: {len(untagged)} (first: {untagged[:10]})")


def main():
    ap = argparse.ArgumentParser(description="Interactive LED section mapper for Mr Tree.")
    ap.add_argument("--host", default="mr-tree.local")
    ap.add_argument("--port", type=int, default=7433)
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"

    coords = load_coords()
    n = len(coords)
    sections = load_sections()
    last_section = None
    i = 0

    print(f"Mapping {n} LEDs via {base}.")
    print("Current LED is lit on the tree. Type a section name (or Enter to reuse), :help for commands.")
    get(base, f"/inspect/{i}")

    def advance():
        nonlocal i
        if i < n - 1:
            i += 1
            get(base, f"/inspect/{i}")
        else:
            print("  (last LED)")

    while True:
        x, y, z = coords[i]
        tag = sections.get(i, "-")
        try:
            raw = input(f"[{i:3d}] ({x},{y},{z}) [{tag}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raw = ":q"

        if raw == "":
            if last_section is not None:
                sections[i] = last_section
                save_sections(sections)
            advance()
            continue

        if not raw.startswith(":"):
            sections[i] = raw
            last_section = raw
            save_sections(sections)
            advance()
            continue

        parts = raw[1:].split()
        cmd = parts[0] if parts else ""

        if cmd in ("q", "quit"):
            save_sections(sections)
            save_coords(coords)
            get(base, "/inspect/off")
            print(f"Saved {SECTIONS} and {COORDS}. Bye.")
            return
        elif cmd in ("s", "save"):
            save_sections(sections)
            save_coords(coords)
            print("  saved.")
        elif cmd == "n":
            advance()
        elif cmd == "p":
            if i > 0:
                i -= 1
                get(base, f"/inspect/{i}")
        elif cmd == "j" and len(parts) == 2:
            j = int(parts[1])
            if 0 <= j < n:
                i = j
                get(base, f"/inspect/{i}")
            else:
                print(f"  out of range 0..{n-1}")
        elif cmd == "c" and len(parts) == 4:
            coords[i] = [int(round(float(v))) for v in parts[1:4]]
            save_coords(coords)
            print(f"  set coord {i} = {tuple(coords[i])}")
        elif cmd == "r" and len(parts) == 4:
            a, b, name = int(parts[1]), int(parts[2]), parts[3]
            for k in range(min(a, b), max(a, b) + 1):
                if 0 <= k < n:
                    sections[k] = name
            last_section = name
            save_sections(sections)
            print(f"  tagged {a}..{b} = {name}")
        elif cmd == "u":
            sections.pop(i, None)
            save_sections(sections)
        elif cmd == "list":
            show_summary(sections, n)
        elif cmd in ("help", "h", "?"):
            print(__doc__)
        else:
            print("  ? unknown command; :help for options")


if __name__ == "__main__":
    main()
