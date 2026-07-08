# Dial (rotary encoder) interaction spec

Three Adafruit I²C QT rotary encoders (seesaw), each with a push-button and an
onboard NeoPixel, arranged left → center → right. They add local physical control
on top of the existing MQTT/HA control. The tree must keep working exactly as today
if the dials are absent or fail to initialize.

## Hardware

- I²C addresses: **0x37, 0x38, 0x36** for physical left → center → right (confirmed on
  hardware; the leftmost dial is 0x37).
- Per encoder: `IncrementalEncoder` (`.position`, relative), button on **pin 24**
  (`INPUT_PULLUP`, pressed == `value False`), onboard NeoPixel on **pin 6**.
- CW rotation = increase (negate `.position` if the hardware reads the other way).
- Physical→address mapping is confirmed by a boot calibration routine (below); the
  order is a single editable constant so we can swap it without code changes.
- **Robust init**: initialize each encoder in its own try/except. A missing/loose
  dial is skipped with a log line and the tree runs normally without it. Init must
  never crash startup (this was the original defect that got the encoders removed).
- **Bus/poll tuning**: the seesaw bus runs at 400kHz and dials are polled at ~33Hz, to
  keep the blocking I²C reads from stealing time from the ~30fps render loop.

## Global button semantics (same in every mode)

- **Left press** → cycle mode: RGB → Animation → Timer → RGB. (In Timer, this cancels
  the timer, which is also the natural next step of the cycle back to RGB.)
- **Center press** → toggle tree on/off.
- **Right press + turn** (hold Right while rotating) → master brightness, 0–255, with
  acceleration. The turn-while-pressed suppresses the button's release action.
- **Left/Center press are ignored while Right is held** (press-turn in progress).

## Sync with MQTT/HA

Every dial action goes through the same controller ops that HA commands use, and
**publishes tree state to MQTT** afterward, so HA always reflects physical changes.
Conversely HA commands drive the local mode for coherence:
- HA color command → RGB mode, updates the R/G/B baseline.
- HA effect command → Animation mode, selects that effect.
- HA on/off / brightness → applied and mirrored in controller state.

High-frequency dial changes (color, brightness, speed, param, timer minutes) are
**throttled to one MQTT publish per 200ms** with a trailing publish when the dial stops,
so spinning a dial doesn't flood the broker. Discrete events (mode switch, power,
timer start/pause) publish immediately.

The tree stays a self-contained end device. (If two-way sync ever needs more than
MQTT can express, the fallbacks are reintroducing the HA custom component or calling
the HA REST API from the tree — but neither is planned.)

## Turn acceleration

Applied to RGB channels, timer minutes, and brightness. Step scales **linearly** with
detents-per-poll (capped at 6) so fast spins move proportionally further while a single
twist can't slam a channel end to end. Base step = **16** per detent for color, 12 for
brightness. 16 for color keeps one detent a visible step even at low display brightness
(where the ~0.06 scale factor otherwise makes small steps round away). One encoder count
= one detent on this hardware.

## Modes

### RGB mode (default at boot)

The whole tree is one solid color. Dials adjust that color's channels.
- **Left turn** → Red (0–255, step 8, accel, clamp).
- **Center turn** → Green.
- **Right turn** → Blue.
- Dial LEDs: left = `(R,0,0)`, center = `(0,G,0)`, right = `(0,0,B)` — each dial glows
  its own channel at its current level. The dial LED blinks white (~8 Hz) while the user
  keeps turning a channel past its 0 or 255 limit (limit cue).
- Setting any channel calls `tree.set_color((r,g,b))` and publishes state.

### Animation mode

Plays one animation from the library (currently `rainbow_cycle`, `sweep`).
- **Left turn** → select animation (cycle through the library).
- **Center turn** → speed (maps through `Tree.set_speed`).
- **Right turn** → the animation's one character parameter:
  - `sweep` → hue (color of the sweep band).
  - `rainbow_cycle` → bandwidth: 0.1 (≈one color over the whole tree, next sweeping
    up from the bottom) to 4.0 (four full color cycles across the height).
- Dial LEDs: left = current animation's signature color; center brightness ∝ speed;
  right = the param's hue/level.

### Timer mode

Pick a duration by filling the tree, then run a countdown. Cap **100 minutes** —
**one minute = one LED**, lit from the bottom up by height rank (not a z threshold,
so spacing is uniform despite the tree's non-uniform vertical LED positions).
- Sub-states: **EDITING** (armed, not running) and **RUNNING**; PAUSED is EDITING with a
  preserved remaining value.
- **Left turn** → set/adjust minutes, 1–100 (accel). Tree lights exactly that many
  LEDs from the bottom up, in a cool "setup" color (blue) to distinguish it from a
  running timer. (Left *press* still cancels/exits — turn and press are distinct.)
- **Right press** → start (EDITING→RUNNING) / pause (RUNNING→EDITING, preserving
  remaining) / resume (start from the shown value, edited or not).
- **Left press** → cancel timer, return to RGB.
- **Auto-start**: if EDITING/PAUSED with no input for **30 s**, start automatically with
  the shown value.
- **RUNNING** uses the existing Timer effect display (relative fill `remaining/duration`
  with green→yellow→red transitions and the pulse wave). Note: pressing start jumps the
  display from the `minutes/100` setup fill to a full relative fill that then drains;
  this brief transition is accepted. On completion the existing rainbow celebration
  plays; Left returns to RGB.
- Dial LEDs: center = green while editing; right = green (startable) / amber (running,
  press to pause); left = off.

## Boot calibration routine

At startup, after encoder init, light each present dial's onboard NeoPixel in
position order (left=red, center=green, right=blue under the assumed mapping) for ~1s
and print `position → address` to serial. The user confirms the physical order and R/G/B
assignment once; if wrong, we reorder the address constant. Runs only briefly at boot.

## Non-goals (for now)

- No unit tests/simulator yet (revisit if we hit trouble).
- No long-press shortcuts yet (architecture supports adding them later).
- No idle-revert timeout except the timer auto-start above.
