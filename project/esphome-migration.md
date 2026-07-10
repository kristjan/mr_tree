# ESPHome migration

Status: **spike BUILT on the `esphome` branch, compiles clean, not yet run on hardware.** The device runs a hand-written CircuitPython app (asyncio event loop, MQTT discovery). This documents whether moving to **ESPHome** on the same board buys us the two things we want — *tighter Home Assistant integration* and *smoother animations* — and how we'd do it. Nothing is broken today; this is a deliberate platform change, not a fix.

**Spike (this branch):** a full port lives under [esphome/](../esphome/) — light (RMT+DMA) + all effects + timer + HA entities + the three seesaw dials — and **compiles green under ESP-IDF**. Flash it with `esphome/flash.sh` (reverts via `provision_board.sh`). The one thing left to prove is on-hardware smoothness/feel — see [esphome/README.md](../esphome/README.md).

Relationship to the [CircuitPython 10 upgrade](circuitpython-10-upgrade.md): these are **alternative directions**, not both. A full ESPHome move replaces the firmware and the whole CircuitPython app; if we commit to it, the CP10 upgrade is moot. Don't do both.

## TL;DR

- **The board runs ESPHome.** Adafruit Feather ESP32-S3 (`adafruit_feather_esp32s3_4mbflash_2mbpsram`) is a first-class ESP32-S3 target. 4MB flash fits an ESPHome image with OTA headroom.
- **The two goals map onto ESPHome's two structural wins:** the **native API** (one-click HA, no discovery JSON to maintain, binary protocol, ~ms latency, encrypted) for integration; **RMT + DMA** WS2812 output for smoothness (pixel timing is offloaded to hardware, so the network stack stops competing with rendering — the MQTT-vs-render contention we currently engineer around goes away).
- **Nothing requires a from-scratch driver.** Every feature has a proven path (details below). The dials — which looked like the big risk — are covered by an existing external component that handles encoder, button, *and* the onboard NeoPixel, at multiple I2C addresses.
- **The one unproven claim is the premise itself:** that it renders *smoother* under real load (WiFi + native API + three-dial I2C polling + per-frame lambda math on ESPHome's cooperative `loop()`). This is reasoned, not measured. **A one-dial spike settles it in a day** and is the go/no-go gate.
- **Scope decisions already made** (this doc reflects them): use ESPHome's **native transitions** rather than porting our sprout/drain-by-height + dithering (revisit only if they disappoint); **drop** the perceived-color HA reporting. Both remove significant lambda work.
- **Free win:** OTA firmware push over WiFi (the "push new code over wifi" item in [TODO.md](TODO.md)) is native to ESPHome.

## Why ESPHome (and the costs)

Current pain the platform change addresses:

- **Integration is hand-maintained.** `publish_discovery()` emits HA MQTT-discovery JSON for a light + timer sensor + duration Number + three buttons, plus a manual `online` heartbeat and LWT, plus a retained-message boot handshake. Native API replaces all of it with adopt-and-go.
- **Smoothness is bounded by interpreted Python and single-threaded asyncio.** Animations run ~30fps; a blocking MQTT socket read stalls the render loop mid-fade, so `handle_mqtt` stands aside during transitions. Compiled C++ with hardware RMT/DMA removes both limits structurally.

Costs we accept:

- Rewriting effects as C++ lambdas (volume, not novelty).
- A third-party dependency for the dials.
- Two deliberate regressions (below).
- Losing the Python edit-save-runs loop (`deploy.sh`) in exchange for a compile step (offset by OTA).

## Feature port mapping

| Feature | Path on ESPHome | Effort |
|---|---|---|
| WS2812 strand (100 px, RGB order) | `esp32_rmt_led_strip`, `chipset: ws2812`, `rgb_order: RGB`, `use_dma: true` | Config |
| Power on/off, brightness, color | Native `light` + native API | Config |
| Brightness cap (`MAX_BRIGHTNESS = 0.30`) | `max_power` / gamma, or clamp in the light config | Config |
| Fades / transitions | **ESPHome native transitions** (`default_transition_length`) — *not* porting sprout/drain-by-height or dithering initially (scope decision) | Config |
| Spatial effects: `hue_shift`, `rainbow_cycle`, `pinwheel`, `cherry_blossom` | `addressable_lambda` per effect, `coordinates.csv` baked into a `static const` array | Write C++ (the core work) |
| `sweep` (currently unpublished) | Same, if we want it | Optional |
| Timer: duration / remaining / start / pause / cancel | `number` (duration) + `global` (deadline) + `interval` (tick) + template `sensor` (remaining) + `button` ×3; standard pattern | Glue-config |
| Timer 3-layer animation + celebration | One more `addressable_lambda` | Write C++ |
| 3 seesaw dials: rotation, button, onboard NeoPixel | **`ssieb/esphome_components` seesaw** — see below | Component install |
| Dial behavior: mode cycle, press-to-power, accel curve, mode→color | ESPHome automations/lambdas reading the dial entities | Write logic (app-level, platform-independent) |
| Availability / online | Native API handles it | Config |
| Boot rainbow | `on_boot` automation running a fill effect | Config |
| OTA push over WiFi | Native `ota:` | Config (a win) |
| Perceived-color reporting to HA | **Dropped** (scope decision) | — |
| Custom web UI on :7433 | Not ported — use HA dashboards (`web_server` optional). **Open decision.** | Decide |
| Photogrammetry capture (`/capture/*`) | Keep as a separate CircuitPython scratch build for re-measuring; migrate the CSV as static data | Don't port |

## The dials — verified against source

Cloned to gitignored [reference/esphome_components](../reference/esphome_components) and read directly. The `seesaw` component ([README](../reference/esphome_components/components/seesaw/README.md)) supports the rotary encoder, its button, temperature, touch, and the single NeoPixel LED. Relevant facts:

- **All three functions we use are covered:** encoder → `sensor` `type: encoder` (with optional `min_value`/`max_value` clamping), button → `binary_sensor` on pin 2, onboard NeoPixel → `light` `platform: seesaw` on pin 14. The NeoPixel being covered removes what looked like custom work.
- **Three dials at once:** the component sets `MULTI_CONF = True` and takes a per-device I2C `address` (`i2c_device_schema`, default `0x49`); every platform references its parent seesaw by id (`cv.use_id(Seesaw)`). So: three `seesaw:` blocks at `0x36`/`0x37`/`0x38`, each with its own encoder sensor + button + neopixel light.
- **Dependency note:** third-party repo; the encoder-button support is a relatively recent commit. We'd pin a commit and vendor/track it. Version-pin, don't float.

What we still write is the **behavior** — cycle-mode, press-to-power, the acceleration curve, mode→color mapping — which is app logic we'd port on any platform, reading the component's entities.

## Timer approach

No native ESPHome "timer entity," but the on-device countdown is a standard recipe: a `number` for duration, a `global` for the deadline/remaining, an `interval` to tick it down, and a template `sensor` exposing remaining seconds to HA; Start/Pause/Cancel become `button` entities driving automations. Reference implementation: Karl Quinsland's [dynamic timers in ESPHome](https://karlquinsland.com/esphome-dynamic-timer/). The timer's visual (fill + pulse wave + fade-out + rainbow celebration) is one `addressable_lambda`, in the same bucket as the other effects.

## Known risks / unproven

1. **Render smoothness under real load (the go/no-go).** ESPHome's `loop()` is cooperative: it runs WiFi + native API + three-dial I2C polling + our per-frame lambda alongside the light output. RMT/DMA offloads *pixel timing*, but a component that hogs a tick can still stutter an `addressable_lambda`. Very likely fine at 100 px; unproven on this board with this load. **The spike measures exactly this.**
2. **Effect-porting volume.** Four-to-five effects plus the composite timer, each as C++ lambdas with per-frame float math (hsv, atan2, smoothstep). Tractable, not trivial.
3. **Third-party seesaw dependency** — pin and track it.
4. **`board.A1` → GPIO mapping** for the strip data pin — a one-line lookup from the Feather S3 pinout; resolve during the spike.

## Plan

Phased, each phase gated by the previous. **Phase 0 is the decision point** — everything after it is only worth doing if the spike renders visibly smoother than the current firmware.

- **Phase 0 — Spike (de-risk smoothness).** Separate ESPHome config, nothing touching [tree/](../tree/). One seesaw dial (encoder + button + neopixel), `esp32_rmt_led_strip` + `use_dma: true`, native API, and `hue_shift` as an `addressable_lambda` off the real `coordinates.csv`. Flash alongside the CircuitPython build and compare smoothness + HA responsiveness. **Gate: does it look better? If no, stop here.**
- **Phase 1 — Core light.** Strip + native API + on/off/brightness/color as a real HA light entity, native transitions, brightness cap. Adopt in HA, confirm one-click.
- **Phase 2 — Effects.** Port `hue_shift`, `rainbow_cycle`, `pinwheel`, `cherry_blossom` as `addressable_lambda`s. (`sweep` optional.)
- **Phase 3 — Dials.** Install/pin the seesaw component, wire all three dials (encoder/button/neopixel), reimplement mode/accel/press behavior in automations.
- **Phase 4 — Timer.** `number` + `global` + `interval` + template `sensor` + three `button`s; the timer animation lambda.
- **Phase 5 — Polish + cutover.** OTA, boot rainbow, availability, decide the web-UI question, retire the CircuitPython firmware.

## Accepted regressions / open decisions

- **Dropped:** perceived-color HA reporting; sprout/drain-by-height fades and dithering (using native transitions instead — revisit only if they disappoint).
- **Open:** custom web UI on :7433 — likely replaced by HA dashboards; decide in Phase 5.
- **Not ported:** photogrammetry capture routes — kept as a separate CircuitPython tool for re-measuring coordinates.

## Sources

- Board / strip: [ESPHome `esp32_rmt_led_strip`](https://esphome.io/components/light/esp32_rmt_led_strip.html), [Adafruit ESP32-S3 Feather](https://learn.adafruit.com/adafruit-esp32-s3-feather); board ID from the device's own `boot_out.txt`.
- Integration: [ESPHome native API](https://esphome.io/components/api.html).
- Effects: [ESPHome light effects / `addressable_lambda`](https://esphome.io/components/light/index.html).
- Dials: [ssieb/esphome_components](https://github.com/ssieb/esphome_components) — read from source in [reference/esphome_components](../reference/esphome_components).
- Timer: [Dynamic timers in ESPHome](https://karlquinsland.com/esphome-dynamic-timer/).
- FastLED (evaluated, not chosen as a destination — a pure LED library with no WiFi/MQTT/HA; its role would only be as an ESPHome backend, and on ESP32-S3 `esp32_rmt_led_strip` is preferred): [FastLED docs](https://fastled.io/docs/).
