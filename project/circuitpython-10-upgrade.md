# CircuitPython 10 upgrade

Status: **planned, not started.** The device currently runs CircuitPython **9.2.1**; target is **10.2.1** (latest stable, 2026-05-12). This is an optional, deliberate upgrade — nothing is broken on 9.2.1, and the audit fixes are independent of it.

## TL;DR

- The board is supported: there is an official 10.2.1 build for `adafruit_feather_esp32s3_4mbflash_2mbpsram`.
- CP10 forces **one line of code change** (`os.getenv("SERVER_PORT")` — see below), already applied defensively on 9.2.1.
- The real cost is **mechanical**, and larger than a normal flash: this 4MB board needs a **bootloader update that erases the filesystem**, plus a full `.mpy` library reinstall from the 10.x bundle.
- Every library we use (minimqtt, httpserver, led_animation, neopixel, seesaw) is compatible with both CP9 and CP10; none pins CP10.

## Why upgrade (and why not)

Upside: current libraries, ongoing security/bugfix support, newer ESP-IDF. Downside: a working LAN-only holiday device gets a re-flash with a filesystem wipe and a reinstall step, for modest functional gain. Recommendation: do it deliberately when the board is already out and you have ~20 minutes, not reactively.

## Code change required by CP10

`os.getenv()` in CP10 **always returns a string** (in CP9 it returned typed values — an int for an integer literal). Only one call site was affected:

- `code.py`: `mdns_server.advertise_service(..., port=os.getenv("SERVER_PORT"))` — `advertise_service` needs an int. On CP9 that was `7433` (int); on CP10 it would be `"7433"` (str) and mDNS advertise fails.
- **Fixed defensively already**: wrapped in `int(...)`. `int(7433)` and `int("7433")` both work, so this is safe on 9.2.1 today and correct on 10.x.

All other `os.getenv` calls already wrap in `int()` (e.g. `MQTT_PORT`).

CP10 also adds `supervisor.get_setting()` (returns typed values incl. float) and `settings.toml` now supports floats — not needed here, noted for future use.

## Migration items checked and NOT affecting us

- **minimqtt v8.0.0** replaced `MMQTTException` with built-in exception types + `MMQTTStateError`. Our code catches bare `Exception` everywhere and never references `MMQTTException` by name → unaffected.
- `will_set()` must be called before `connect()` (v8.0.0 raises otherwise) — our code already does.
- CP10 removed `sys.print_exception()` — we use `traceback.print_exc()`, unaffected.
- CP10 removed `watchdog.WatchDogTimer.deinit()` — we never call it.
- CP10 removed `displayio`/`synthio` deprecated bindings — we use neither.
- CP10 changed internal `_asyncio` (`push_head`/`push_sorted`/`pop_head` removed). Resolved automatically by reinstalling the `asyncio` bundle library — see step 7.

## Firmware flash runbook

Steps 1–5 require physical access (button presses) and are done by the user. Steps 6–8 can be driven from the host.

1. **Back up the entire CIRCUITPY drive** (all code + `settings.toml`). The bootloader update in step 3 erases the drive.
2. Check the current TinyUF2 bootloader version: slow-double-tap Reset to reach the `FTHRS3BOOT` drive, open `INFO_UF2.TXT`. If < 0.33.0, do step 3.
3. **Update the TinyUF2 bootloader to 0.35.0** — *required* for this 4MB board: CP10's firmware partition doubled to 2.8MB and does not fit under the old bootloader. **This step erases CIRCUITPY.**
   - `tinyuf2-adafruit_feather_esp32s3-0.35.0-combined.bin` (see the Adafruit "Update TinyUF2 Bootloader for CircuitPython 10" and "Factory Reset" guides for the exact esptool invocation — confirm on the guide page before running).
4. **Enter the UF2 bootloader**: tap Reset once, wait for the LED to turn purple, then tap Reset again while purple (a slow double-click, not a fast double-tap). `FTHRS3BOOT` mounts.
5. Drag `adafruit-circuitpython-adafruit_feather_esp32s3_4mbflash_2mbpsram-en_US-10.2.1.uf2` onto `FTHRS3BOOT`. The drive reboots and remounts as `CIRCUITPY` running 10.2.1.
6. Restore `settings.toml` (and any other backed-up files).
7. **Reinstall libraries from the 10.x bundle**: upgrade host `circup` first (2.1.0 → 3.0.4; 2.1.0 is too old to enumerate installed versions), then `circup update --all`. Note: sources disagree on whether the `.mpy` format strictly changed 9→10, but a refresh is cheap and correct either way; the `asyncio` library update is **mandatory** because of the `_asyncio` internal removals above.
8. Re-deploy `tree/` (`deploy.sh`), confirm the `SERVER_PORT` `int()` change is present, watch the serial console through a full boot: WiFi connect → mDNS → MQTT connect → discovery → animation.

## Verified reference facts (2026-07)

| Component | Current | Latest | Notes |
|---|---|---|---|
| CircuitPython | 9.2.1 | 10.2.1 (stable) | 10.3.0-alpha.3 is prerelease only |
| TinyUF2 bootloader | (board default, likely < 0.33.0) | 0.35.0 | ≥0.33.0 required for CP10 on 4MB flash |
| circup (host) | 2.1.0 | 3.0.4 | |
| Adafruit bundle | 20250708 | 20260707 | |
| adafruit_minimqtt | — | 8.1.0 | CP9+CP10 compatible; `.loop()` blocks for full timeout (upstream #241) |
| adafruit_httpserver | — | 4.8.2 | CP9 support since 4.5.6; async poll pattern is official |
| adafruit_led_animation | — | 2.12.6 | base Animation API unchanged |
| neopixel | — | 6.4.2 | bundle lib, independent of core; BGR order added 6.4.0 |
| adafruit_seesaw | — | 1.18.2 | ships both CP9 and CP10 mpy builds |

Sources: circuitpython.org, docs.circuitpython.org, the CircuitPython 10.0.0 GitHub release notes ("Incompatibility warnings" section), and each library's GitHub releases. There is no single official 9→10 migration guide beyond the release notes.
