#!/bin/bash
#
# provision_board.sh — take a board to Mr Tree's full current state in one shot.
#
# Does everything a factory-fresh (or ESPHome-wiped) Adafruit Feather ESP32-S3
# needs to become the running tree again:
#   1. downloads + flashes the pinned CircuitPython firmware (esptool, over the
#      ROM bootloader),
#   2. installs the libraries (circup, from tree/circuitpython-requirements.txt),
#   3. deploys our code (tree/ -> CIRCUITPY, via deploy.sh),
#   4. copies settings.toml (WiFi/MQTT secrets) onto the board.
#
# The ONLY manual step is putting the board into the ROM bootloader once:
#   hold BOOT, tap RESET, release BOOT.
# After that esptool auto-reboots into CircuitPython and the rest is unattended.
#
# Usage:
#   ./provision_board.sh                 # full provision (firmware + libs + code + settings)
#   ./provision_board.sh --skip-firmware # board already runs CircuitPython; libs + code + settings only
#   PORT=/dev/cu.usbmodemXXXX ./provision_board.sh   # force the serial port
#
# Recovery from ESPHome: this is the way back. ESPHome overwrites the firmware,
# so there is no CIRCUITPY drive until step 1 re-flashes it — run the full mode.

set -euo pipefail
cd "$(dirname "$0")"

# --- fixed for this hardware -------------------------------------------------
BOARD_ID="adafruit_feather_esp32s3_4mbflash_2mbpsram"
CP_VERSION="9.2.1"   # keep in step with the version we run; see project/circuitpython-10-upgrade.md
CHIP="esp32s3"

# --- paths -------------------------------------------------------------------
VENV="venv"
PY="$VENV/bin/python"
CIRCUITPY="/Volumes/CIRCUITPY"
TREE_SRC="tree"
REQS="$TREE_SRC/circuitpython-requirements.txt"
SETTINGS_SRC="settings.toml"          # gitignored; referenced by path, never read here
FW_DIR="firmware"                      # gitignored cache
BIN="$FW_DIR/adafruit-circuitpython-$BOARD_ID-en_US-$CP_VERSION.bin"
FW_URL="https://downloads.circuitpython.org/bin/$BOARD_ID/en_US/adafruit-circuitpython-$BOARD_ID-en_US-$CP_VERSION.bin"

SKIP_FIRMWARE=0
case "${1:-}" in
    --skip-firmware) SKIP_FIRMWARE=1 ;;
    "" ) ;;
    * ) echo "Usage: $0 [--skip-firmware]" >&2; exit 2 ;;
esac

say()  { printf '\n\033[1;36m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$1" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$1" >&2; exit 1; }

# Poll for the CIRCUITPY drive. After an esptool flash the ESP32-S3 usually needs
# one physical RESET before CircuitPython re-enumerates USB mass storage, so if it
# doesn't appear on its own we prompt for a tap and keep waiting.
wait_for_circuitpy() {
    local secs=0
    [ -d "$CIRCUITPY" ] && return 0
    echo "  Waiting for $CIRCUITPY (up to 30s)..."
    while [ "$secs" -lt 30 ]; do
        [ -d "$CIRCUITPY" ] && return 0
        sleep 1; secs=$((secs + 1))
    done
    printf '\n  >>> Tap RESET once on the board (a single press — NOT BOOT) to boot CircuitPython.\n'
    read -r -p "  Press Enter after tapping RESET... " _
    secs=0
    while [ "$secs" -lt 60 ]; do
        [ -d "$CIRCUITPY" ] && return 0
        sleep 1; secs=$((secs + 1))
    done
    return 1
}

# --- preflight ---------------------------------------------------------------
say "Preflight"
[ -x "$PY" ] || die "No venv python at $PY (run from the repo root with the venv set up)."
command -v curl  >/dev/null || die "curl not found."
command -v rsync >/dev/null || die "rsync not found."
[ -f "$REQS" ] || die "Missing $REQS."
[ -f "$SETTINGS_SRC" ] || die "Missing $SETTINGS_SRC — the secrets file the board needs. Create it from tree/settings.toml.example first."
[ -x "./deploy.sh" ] || die "Missing ./deploy.sh."

# esptool (pin to v4: v5 renamed the subcommands used below)
if ! "$PY" -m esptool version >/dev/null 2>&1; then
    say "Installing esptool into the venv"
    "$VENV/bin/pip" install --quiet "esptool>=4,<5"
fi

# circup 2.x can't reliably enumerate/install; the repo's CP10 notes call this out.
if ! "$VENV/bin/circup" --version 2>/dev/null | grep -qE 'version 3|version 4'; then
    say "Upgrading circup (>=3) in the venv"
    "$VENV/bin/pip" install --quiet -U "circup>=3"
fi

# --- 1. firmware -------------------------------------------------------------
if [ "$SKIP_FIRMWARE" -eq 0 ]; then
    say "Firmware: CircuitPython $CP_VERSION for $BOARD_ID"
    mkdir -p "$FW_DIR"
    if [ ! -s "$BIN" ]; then
        say "Downloading $FW_URL"
        curl -fL --retry 3 -o "$BIN" "$FW_URL" || die "Firmware download failed. Check the version/URL."
    else
        echo "  cached: $BIN"
    fi
    [ -s "$BIN" ] || die "Firmware image is empty: $BIN"

    cat <<'EOF'

  >>> Put the board into the ROM bootloader now:
        1. hold down BOOT (aka B0/DFU)
        2. tap RESET
        3. release BOOT
      The board will NOT show up as a USB drive — that is correct.
EOF
    read -r -p "  Press Enter once the board is in the bootloader... " _

    PORT="${PORT:-}"
    if [ -z "$PORT" ]; then
        # bash 3.2 (macOS default) has no mapfile; glob into an array instead.
        _ports=( /dev/cu.usbmodem* )
        [ -e "${_ports[0]}" ] || die "No /dev/cu.usbmodem* serial port found. Re-run with PORT=/dev/cu.usbmodemXXXX."
        [ "${#_ports[@]}" -eq 1 ] || die "Found ${#_ports[@]} candidate ports (${_ports[*]}). Re-run with PORT=/dev/cu.usbmodemXXXX."
        PORT="${_ports[0]}"
    fi
    echo "  Using serial port: $PORT"

    say "Erasing flash"
    "$PY" -m esptool --chip "$CHIP" --port "$PORT" erase_flash
    say "Writing CircuitPython @ 0x0"
    "$PY" -m esptool --chip "$CHIP" --port "$PORT" write_flash -z 0x0 "$BIN"
    # esptool hard-resets by default, so the board reboots into CircuitPython here.

    say "Waiting for $CIRCUITPY to mount"
    wait_for_circuitpy || die "$CIRCUITPY still did not appear. Try unplug/replug USB, then re-run with --skip-firmware."
else
    say "Skipping firmware (assuming CircuitPython already running)"
    wait_for_circuitpy || die "$CIRCUITPY not mounted. Tap RESET or replug USB, or drop --skip-firmware to flash firmware first."
fi

# Give the freshly-booted filesystem a moment to settle before writing.
sleep 2

# --- 2. libraries ------------------------------------------------------------
say "Installing libraries from $REQS"
"$VENV/bin/circup" install -r "$REQS"

# --- 3. settings (secrets) ---------------------------------------------------
say "Copying settings.toml onto the board"
cp "$SETTINGS_SRC" "$CIRCUITPY/settings.toml"   # contents never printed

# --- 4. code -----------------------------------------------------------------
say "Deploying code (deploy.sh --once)"
./deploy.sh --once

say "Done. The board should reboot and run within ~20s (WiFi -> mDNS -> MQTT -> discovery)."
echo "  Watch it:  $VENV/bin/pyserial-miniterm <the board's serial port>"
