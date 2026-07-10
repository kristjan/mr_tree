# Mr Tree — ESPHome port (spike)

An ESPHome reimplementation of the CircuitPython tree, on the **same board**
(Adafruit Feather ESP32-S3). Built to answer the two questions in
[../project/esphome-migration.md](../project/esphome-migration.md): does it render
*smoother* (compiled C++ + RMT/DMA), and does it integrate *tighter* with Home
Assistant (native API)?

> This is a branch spike. Flashing it **replaces** the CircuitPython firmware.
> To go back, run `../provision_board.sh` (full mode). See below.

## Flash it (one script)

```
esphome/flash.sh
```

That regenerates secrets (from `../settings.toml`) and the coordinate header,
builds, and flashes over USB — the only manual step is the ROM bootloader when
prompted (hold BOOT, tap RESET, release BOOT), same as `provision_board.sh`. After
it flashes it streams logs; watch for WiFi connect → API up. Then adopt **Mr Tree**
in Home Assistant (Settings → Devices → ESPHome; it should be auto-discovered).

Re-attach to logs later with `esphome/flash.sh --logs-only`.

To revert to the CircuitPython tree: `../provision_board.sh`.

## Layout

| File | Role |
|---|---|
| `mr_tree.yaml` | The ESPHome config: light, effects, HA entities, timer, dials. |
| `tree_effects.h` | All effects ported to plain C++ (no ESPHome types). The lambdas call into this. |
| `tree_coords.h` | **Generated** by `tools/gen_esphome_coords.py` from `tree/coordinates.csv` + `tree/segments.csv`. Do not edit. |
| `flash.sh` | Build + flash + logs. |
| `secrets.yaml` | **Generated** from `../settings.toml` by `tools/gen_esphome_secrets.py` (gitignored). |

Single source of truth: the coordinate/segment CSVs and `settings.toml` are shared
with the CircuitPython app; the generators derive the ESPHome inputs from them, so
nothing is hand-duplicated.

## What's implemented

- **Light** on GPIO18 (board.A1), 100 WS2812, `rgb_order: RGB`, **RMT + DMA**, native
  API, OTA, mDNS (`mr-tree.local`), a boot rainbow → default effect sequence.
- **Effects** (HA effect list), ported from the Python: `Hue Shift`, `Rainbow
  Cycle`, `Pinwheel`, `Cherry Blossom`, plus `Timer` and `Boot Rainbow`.
- **Control numbers** in HA: Speed, Hue Shift Mode, Rainbow Bandwidth, Pinwheel
  Repeats, Cherry Pink, Timer Duration.
- **Timer subsystem**: duration Number, remaining-seconds Sensor, state text Sensor,
  Start/Pause/Resume/Cancel buttons, and the 3-layer timer animation (fill + pulse
  wave + fade-out + rainbow celebration).
- **Dials**: three seesaw encoders (LEFT 0x37 / CENTER 0x38 / RIGHT 0x36), buttons
  (pin 24), and onboard NeoPixels (pin 6), via `ssieb/esphome_components`.
- **Power cap**: every effect scales output by `MAX_BRIGHT = 0.30`, so full-white
  stays within the 5V/2.4A budget regardless of the HA brightness slider.
- **Web UI + REST API** via `web_server` at `http://mr-tree.local/` (local/offline).

### Dial behavior — subset of the original

The dial *hardware* is fully wired. The *behavior* is a faithful subset of the
CircuitPython controller's **Animation mode** — each dial keeps the same job it has
there — but the full mode state machine (RGB / Timer modes, acceleration, all the
press semantics from `tree/util/controller.py`) is not ported yet.

The current mapping lives in `mr_tree.yaml` (the seesaw `sensor`/`binary_sensor`
blocks) — that's the source of truth; it isn't restated here so the two can't drift.

## Known differences from the CircuitPython app (intentional, for the spike)

- **Native transitions** instead of the spatial sprout/drain fades and low-brightness
  dithering (a scope decision — revisit only if they disappoint).
- **No perceived-color HA reporting** (dropped — no ESPHome equivalent).
- **Web UI**: the `web_server` component serves a local page at `http://mr-tree.local/`
  plus a REST API (`/<domain>/<entity>/<action>`). A custom page can drive the device
  with low-level calls to that API. It is not a reproduction of the old :7433 SPA.
- Effect params exposed as separate HA `number` entities rather than the single
  `speed` attribute.

## Verified vs. not

- ✅ **Compiles** clean under ESP-IDF with `use_dma: true` (this is the point — the
  port is real).
- ⚠️ **Not yet run on hardware** by the author of this branch — flashing needs the
  physical bootloader tap and takes the tree down. The `flash.sh` run is the first
  true end-to-end test: smoothness, HA adoption, and dial feel are what to judge.

## Regenerate after data changes

```
venv/bin/python tools/gen_esphome_coords.py   # after editing coordinates/segments
```
