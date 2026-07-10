#!/bin/bash
#
# flash.sh — build the ESPHome firmware and flash it to the Feather ESP32-S3 over
# USB, then stream logs so you can watch it come up (WiFi -> API -> first render).
#
# This REPLACES the CircuitPython firmware currently on the board. To go back to
# the tree as it was, run  ../provision_board.sh  (full mode).
#
# The only manual step is the ROM bootloader, same as provisioning:
#   hold BOOT, tap RESET, release BOOT.
#
# Usage:
#   esphome/flash.sh                     # regen secrets+coords, build, flash, log
#   PORT=/dev/cu.usbmodemXXXX esphome/flash.sh
#   esphome/flash.sh --logs-only         # just attach to logs (board already flashed)

set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

VENV="venv"
PY="$VENV/bin/python"
ESPHOME="$VENV/bin/esphome"
CONFIG="esphome/mr_tree.yaml"

say()  { printf '\n\033[1;36m==>\033[0m %s\n' "$1"; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$1" >&2; exit 1; }

[ -x "$ESPHOME" ] || die "esphome not installed. Run: $VENV/bin/pip install esphome"

detect_port() {
    if [ -n "${PORT:-}" ]; then echo "$PORT"; return; fi
    local ports=( /dev/cu.usbmodem* )
    [ -e "${ports[0]}" ] || die "No /dev/cu.usbmodem* port. Re-run with PORT=/dev/cu.usbmodemXXXX."
    [ "${#ports[@]}" -eq 1 ] || die "Multiple ports (${ports[*]}). Re-run with PORT=/dev/cu.usbmodemXXXX."
    echo "${ports[0]}"
}

if [ "${1:-}" = "--logs-only" ]; then
    say "Attaching to logs"
    exec "$ESPHOME" logs "$CONFIG" --device "$(detect_port)"
fi

# 1. Secrets from settings.toml (WiFi), and a fresh coordinates header.
if [ ! -f esphome/secrets.yaml ] || grep -q placeholder esphome/secrets.yaml; then
    say "Generating esphome/secrets.yaml from settings.toml"
    "$PY" tools/gen_esphome_secrets.py
fi
say "Regenerating tree_coords.h"
"$PY" tools/gen_esphome_coords.py

# 2. Bootloader prompt (same as provision_board.sh).
cat <<'EOF'

  >>> Put the board into the ROM bootloader:
        1. hold down BOOT (aka B0/DFU)
        2. tap RESET
        3. release BOOT
      No LED and no USB drive is correct — the flasher confirms the connection.
EOF
read -r -p "  Press Enter once the board is in the bootloader... " _
PORT_DEV="$(detect_port)"
say "Using serial port: $PORT_DEV"

# 3. Build + upload + stream logs.
say "Building and flashing ESPHome (first build downloads the toolchain; be patient)"
exec "$ESPHOME" run "$CONFIG" --device "$PORT_DEV"
