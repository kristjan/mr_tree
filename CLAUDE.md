# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Mr Tree" — an LED Christmas tree driven by a CircuitPython microcontroller (Adafruit Feather ESP32-S3, 4MB Flash / 2MB PSRAM — board ID `adafruit_feather_esp32s3_4mbflash_2mbpsram`, VID `0x239A`, CircuitPython 9.2.1, per the board's `boot_out.txt`). A strand of 100 NeoPixels is addressed in 3D space via per-LED `(x, y, z)` coordinates so animations can sweep and fill along real geometric axes rather than strand index. The device exposes an HTTP control server, an mDNS name, and a full Home Assistant MQTT integration (auto-discovery + light/timer entities).

All device code lives in [tree/](tree/) and runs *on the microcontroller* under CircuitPython — not CPython. The `venv/` at the repo root is a host-side toolchain (circup, pyserial, home-assistant tooling); it is not the runtime.

## Deploying and running

The board mounts as a USB drive at `/Volumes/CIRCUITPY/`. CircuitPython auto-runs `code.py` on boot and reloads on file change.

- **Deploying:** `./deploy.sh` — syncs all of [tree/](tree/) to `/Volumes/CIRCUITPY/` once and exits (default). `./deploy.sh --watch` instead watches with `fswatch` and rsyncs changed files continuously. There is no build or compile step; edited files run on save. CircuitPython auto-reloads on each USB write, but the reboot is deferred until writes settle and then takes ~10-20s (WiFi + MQTT reconnect) before the new code is serving; for a deterministic, immediate reload, `curl http://<host>:7433/reboot` after a sync.
- **Libraries:** managed with `circup` (in `venv/bin/`), driven by [tree/circuitpython-requirements.txt](tree/circuitpython-requirements.txt). These are the `adafruit_*` / `neopixel` bundle libraries installed onto the board's `lib/` — do not expect them to import on the host.
- **Serial console / REPL:** use `pyserial-miniterm` (in `venv/bin/`) against the board's USB serial port to see `print()` output; the code is heavily instrumented with prints for debugging over serial.
- **Secrets:** copy [tree/settings.toml.example](tree/settings.toml.example) to `tree/settings.toml` (WiFi, MQTT broker, mDNS name, server port). `settings.toml` is gitignored and excluded from deploy — never commit it. Values are read at runtime via `os.getenv(...)`.

There is no test suite, linter, or CI in this repo. Verification is manual: deploy to the board and watch serial output / the web UI / Home Assistant.

## Architecture

### Entry point: [tree/code.py](tree/code.py)
The whole app is one asyncio event loop (`asyncio.gather`) running these concurrent tasks:
- `handle_requests` — polls the `adafruit_httpserver` (port 7433) for the REST control API and serves [tree/index.html](tree/index.html).
- `tree.animate()` — the render loop, ~30fps (`asyncio.sleep(0.033)`), calls the active animation's `animate()` unless frozen.
- `handle_mqtt` — pumps the MQTT loop with reconnect + exponential backoff.
- `handle_timer_updates` / `handle_availability_heartbeat` — publish timer state and `online` availability every 1s / 30s.
- `handle_watchdog` — feeds a 10s hardware watchdog (`WatchDogMode.RESET`); if any task wedges, the board resets.
- `handle_encoders` — polls three Adafruit seesaw rotary dials over I2C (`0x36`/`0x37`/`0x38` = left/center/right) at ~33Hz and dispatches turn/press events to the dial controller ([tree/util/controller.py](tree/util/controller.py) + [tree/util/encoders.py](tree/util/encoders.py)): RGB / animation / timer modes, per-dial NeoPixel feedback, and power-fade coupling to the strand. Idle only if no dials are attached.

The MQTT/render timing is interdependent: `socket_timeout` (5ms) bounds how long a `mqtt_client.loop()` poll can stall the single-threaded render loop, kept well under one fade frame (~16ms at 60fps) so packets read fine without stepping a fade. On top of that, `handle_mqtt` stands aside entirely (`tree.is_transitioning()`) for the ~1s a fade/sprout/drain renders, so a blocking socket read never steps a transition. Changing these can stutter the LEDs — see commit `74e5b3f`.

### Control surface — two front-ends, one core
Both the HTTP routes and the MQTT message handlers funnel into **`handle_state_change(state_params)`** in [tree/code.py](tree/code.py). That function is the single choke point for state mutation (`state`, `brightness`, `color`, `effect`/`effect_params`, `speed`, `animation_state`); after applying, it always calls `publish_state()` to keep Home Assistant in sync. When adding a control, route it through `handle_state_change` rather than poking `tree` directly.

### The Tree — [tree/tree.py](tree/tree.py)
`Tree` owns the `NeoPixel` strand and the currently active animation. Key behaviors that are easy to get wrong:
- **Brightness is scaled, not literal.** HA/API brightness is 0–255 but is mapped to a physical `0..MAX_BRIGHTNESS` range (`brightness / 255 * MAX_BRIGHTNESS`, the `MAX_BRIGHTNESS` constant in [tree/tree.py](tree/tree.py)) to bound current draw against the shared 5V/2.4A supply and limit color distortion at full drive. `state()` reverses the scaling. Any brightness math must respect this; read the power-budget comment on the constant before raising it.
- **On/off is brightness, not power.** `off()` stores current brightness and sets it to 0 (pausing any animation); `on()` restores it, filling 20% white if the strand was all-black so a bare HA "ON" produces visible light.
- **Perceived color** reported to HA is a brightness-weighted average of the top 25% brightest sampled pixels (`calculate_perceived_color`), sampling ~10 pixels to limit memory churn.
- **Coordinates** are loaded from [tree/coordinates.csv](tree/coordinates.csv) (100 rows of `x,y,z`); index = pixel index. This drives all spatial effects.

### Animations — [tree/effects/](tree/effects/) + [tree/util/tree_animation.py](tree/util/tree_animation.py)
All effects subclass `TreeAnimation`, which extends the Adafruit `adafruit_led_animation.Animation` and adds `_coordinates` and `_bounds` (min/max per axis, computed once). `frozen` maps to the parent's `_paused`. Register a new effect by:
1. adding its name to `Tree.EFFECTS` (this list is also what HA advertises as `effect_list`),
2. constructing it in `Tree.load_effect`,
3. subclassing `TreeAnimation` and implementing `draw()` (spatial effects iterate `self._coordinates` and color by `x/y/z` position).

Existing effects — `Tree.EFFECTS` (also HA's `effect_list`, in this order) is `hue_shift`, `rainbow_cycle`, `cherry_blossom`, `pinwheel`, `timer`. `sweep` also exists as an effect module and is instantiable via `load_effect`, but is **not** in `EFFECTS` (not advertised to HA, and filtered out of the web UI's effect grid).
- **`HueShift`** — splits the tree into horizontal bands by normalized z-rank; each band melts in place to a new random hue on a staggered clock (no vertical motion). `bands` (1–12) is the per-effect param.
- **`RainbowCycle`** — hue as a function of normalized z-height scrolling over time; speed = `frequency`.
- **`CherryBlossom`** — fixed-brown trunk (lowest LEDs by z) with warm-white branches, a `pink_fraction` subset twinkling white↔pink.
- **`Pinwheel`** — hue by angle around the vertical axis through the x-y centroid, rotating over time; `repeats` = color cycles per revolution.
- **`Sweep`** (unpublished) — a lit band sweeps along X→Y→Z in turn, with lead/lag falloff; speed maps to `step` and `lag` window (see `Tree.set_speed`). Supports "peers" whose colors max-blend.
- **`Timer`** — fills the tree bottom-to-top, color lerping green→yellow→red as time runs out, with a downward pulse wave and per-LED fade-out, then a rainbow completion celebration. Timer state (`remaining`/`duration`/`state`) is its own MQTT sensor + Number + Start/Pause/Cancel buttons. Note: `Timer.draw()` deliberately does **not** publish MQTT (it would block the render loop); the `handle_timer_updates` task polls `get_state()` instead.

### Home Assistant / MQTT — [tree/util/mqtt.py](tree/util/mqtt.py) + `publish_discovery()` in code.py
Topics and the discovery prefix live in `util/mqtt.py`. On MQTT connect the device: cleans up old discovery topics, publishes fresh HA MQTT-discovery configs (a JSON-schema light + a timer sensor + a duration Number + three buttons, all sharing one `device` block), sets availability `online`, and publishes initial state. A retained Last Will marks it `offline` if it drops. `set_mqtt_client()` injects the client into the util module so effects can publish without importing code.py.

## Conventions specific to this codebase

- **Memory is tight.** This is a microcontroller. Prefer in-place pixel writes, sampling over full-strand copies, and avoid allocating large transient lists in hot paths (`state()` and the effects already do this deliberately).
- **Don't block the event loop.** Never do MQTT/network I/O inside `draw()` or any per-frame path; hand it to one of the periodic tasks. Blocking risks a watchdog reset.
- **Serial `print()` is the debugger.** Prints on the `MQTT <<` / `MQTT >>` / task-lifecycle boundaries are intentional operational logging, not stray debug — keep them useful when editing.
- **CircuitPython, not CPython.** Only libraries present on the board (the `adafruit_*` bundle, `neopixel`, plus CircuitPython builtins like `board`, `wifi`, `mdns`, `microcontroller`) are importable at runtime. The host `venv/` will import things the board cannot.
