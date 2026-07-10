# ESPHome dials — I2C bus diagnosis & fix plan

Status: **dials disabled on the `esphome` branch** (commit `85dd287`); the full dial
config is at commit `be00a6c`. The light + effects + HA work; the three seesaw dials
do not. This is the plan to fix them, for the next hardware session.

## Evidence (from on-device logs)

```
[i2c.idf] Recovery: failed, SCL is held low on the bus
[i2c.idf] Found no devices                       (first boot)
[seesaw]  Address: 0x37  CPU: unknown (00)  Version: <garbled, inconsistent>
[esp-idf] E i2c.master: I2C software timeout      (repeating, blocking the loop)
```

Effects of the failure (once dials were wired in):
- The blocking per-poll seesaw reads **stall the render loop** → bursty, seconds-apart fades.
- Garbage encoder/button reads **fire dial handlers on their own** → effects flip, power toggles.

Enabling GPIO7 (I2C_POWER) via an `ALWAYS_ON` gpio switch moved it from "no devices"
to "devices respond but garbled" — so GPIO7 power is necessary but not sufficient.

## Root cause — ranked

1. **Power sequencing (most likely).** CircuitPython enables `I2C_POWER` (GPIO7) as
   part of bus setup, *before* the first transaction ([tree/code.py:428](../tree/code.py#L428)
   uses `busio.I2C` after the board powers the STEMMA rail). In ESPHome the i2c bus
   initializes at `setup_priority::BUS` (earliest), but the GPIO7 switch only goes high
   at `HARDWARE` (later) — so the boot-time i2c recovery runs on an **unpowered** bus,
   sees SCL low, fails, and can leave the ESP-IDF i2c master wedged even after GPIO7
   rises. CircuitPython uses the *same* 400kHz, so clock rate is **not** the difference —
   ordering is.
2. **Signal quality at 400kHz** on the 3-dial STEMMA chain (secondary). Even powered,
   reads were inconsistent. Lower clock is more tolerant of chain capacitance / pull-ups.
3. **seesaw component vs ESP-IDF i2c** (least likely). `ssieb/esphome_components` is
   framework-agnostic but was only exercised by us under esp-idf; its read path may not
   tolerate clock-stretching the way Adafruit's Arduino/CircuitPython driver does.

## Fixes to try, in order

### 1. Power GPIO7 high *before* i2c init (addresses root cause #1)

The gpio `switch`/`output` can't beat the i2c bus's `BUS` setup priority. Two options:

- **Preferred: a tiny external component** whose `setup()` runs at a priority *above*
  `BUS` and drives GPIO7 high + a short delay. Sketch:

  ```cpp
  // components/i2c_power/i2c_power.h
  class I2CPower : public Component {
   public:
    float get_setup_priority() const override { return 1100.0f; }  // before BUS (1000)
    void setup() override {
      gpio_set_direction((gpio_num_t) 7, GPIO_MODE_OUTPUT);
      gpio_set_level((gpio_num_t) 7, 1);
      delay(10);   // let the rail + pull-ups settle before i2c scans
    }
  };
  ```
  ```yaml
  external_components: [ { source: components } ]   # local
  i2c_power:
  ```

- **Simpler test first:** keep the `switch: gpio GPIO7 restore_mode: ALWAYS_ON` and add
  `i2c: { scan: false, timeout: 10ms }`, then in `on_boot: priority: 800` do a
  `switch.turn_on: i2c_power` + `delay: 50ms`. May not beat `BUS`, but cheap to rule out.

### 2. Lower the I2C clock (addresses #2)

```yaml
i2c:
  frequency: 100kHz     # from 400kHz; try 50kHz if still marginal
```

### 3. Bound the blocking reads so a bad bus can't stall rendering (mitigation)

```yaml
i2c:
  timeout: 5ms          # cap how long a failed transaction blocks the loop
```
This keeps the render smooth and the dials merely non-functional if the bus is still bad,
rather than taking the whole device down with it.

### 4. Fallbacks if 1–3 don't land

- Vendor `ssieb/esphome_components` locally and add read retries / a longer inter-byte
  delay in the seesaw read path.
- Build the seesaw dials under the **arduino** framework (its `Wire` I2C handles these
  encoders in CircuitPython/Arduino land); the RMT custom timing + DMA still work there.
  Bigger change — last resort.

## How to re-enable the dials for testing

The dial config (external seesaw component, i2c + GPIO7 power, 3 seesaw devices, encoder
sensors, buttons, dial NeoPixels, plus the `enc_*`/`fx_index` globals and the on_boot
dial-LED lines) is intact at commit `be00a6c`:

```
git show be00a6c:esphome/mr_tree.yaml
```

Re-apply those blocks to `esphome/mr_tree.yaml`, then layer on fix #1 + #2 + #3 above,
compile, and OTA to the tree's static IP (`192.168.50.100`). Watch the logs for the
seesaw `CPU:` line showing a real chip id (`SAMD09`) instead of `unknown (00)`, and for
the absence of `I2C software timeout`.
