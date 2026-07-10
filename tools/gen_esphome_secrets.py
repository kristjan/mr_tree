#!/usr/bin/env python3
"""Generate esphome/secrets.yaml from settings.toml (WiFi creds).

Lets the ESPHome build reuse the same WiFi credentials as the CircuitPython app
without duplicating them. Reads WIFI_SSID / WIFI_PASSWORD from settings.toml and
writes esphome/secrets.yaml. Prints only the key names it wrote, never the values.

    venv/bin/python tools/gen_esphome_secrets.py
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(ROOT, "settings.toml")
OUT = os.path.join(ROOT, "esphome", "secrets.yaml")


def main():
    if not os.path.exists(SETTINGS):
        raise SystemExit(f"settings.toml not found at {SETTINGS}")

    vals = {}
    with open(SETTINGS) as f:
        for line in f:
            m = re.match(r'\s*([A-Z_]+)\s*=\s*"(.*)"\s*$', line)
            if m:
                vals[m.group(1)] = m.group(2)

    ssid = vals.get("WIFI_SSID")
    pw = vals.get("WIFI_PASSWORD")
    if not ssid or pw is None:
        raise SystemExit("WIFI_SSID / WIFI_PASSWORD not found in settings.toml")

    def esc(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write("# Generated from settings.toml by tools/gen_esphome_secrets.py — do not commit.\n")
        f.write(f'wifi_ssid: "{esc(ssid)}"\n')
        f.write(f'wifi_password: "{esc(pw)}"\n')

    print(f"wrote {OUT} (wifi_ssid, wifi_password)")  # names only, never values


if __name__ == "__main__":
    main()
