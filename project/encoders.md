# Rotary encoders (dials) — re-enable notes

The encoder scaffolding was removed from `code.py` during the audit (it was
non-functional — the read loop was entirely commented out — and its unconditional
hardware init crashed startup whenever a dial wasn't attached). This note preserves
everything needed to re-implement it cleanly. Ties to TODO.md "Use dials to manually
set RGB values" and "Dial control for animation switching and parameter control".

## Hardware (as previously wired)

- 3 × Adafruit seesaw rotary encoders on the shared I²C bus (`board.I2C()`).
- I²C addresses: **0x37, 0x38, 0x36** (order matters — this was the left/center/right order).
- Each encoder's push-button is on **seesaw pin 24**, configured `INPUT_PULLUP`;
  pressed reads `button.value == False`.
- `IncrementalEncoder(ss)` exposes `.position` (accumulates; track deltas).

## Removed init (for reference)

```python
i2c = board.I2C()
encoders = []
for addr in [0x37, 0x38, 0x36]:
    ss = Seesaw(i2c, addr)
    ss.pin_mode(24, ss.INPUT_PULLUP)
    encoder = IncrementalEncoder(ss)
    button = DigitalIO(ss, 24)
    encoders.append((encoder, button))
```

Removed read loop intent (was commented out): per encoder, on `position` change call
`tree.turn(i, diff)`; on button press call `tree.press(i)`.

## What to reuse when re-enabling

- `Tree.press(button)` and `Tree.turn(encoder, diff)` in `tree.py` are the intended
  action hooks (kept in place). `press(LEFT)` currently advances to the next animation
  via `next_animation()`.
- `util/color_encoder.py` is an earlier, fuller per-encoder implementation (one RGB
  channel per dial, drives the seesaw's onboard NeoPixel on pin 6). Kept as reference.
  Note it has a bug: `update()` references an undefined global `encoder_steps` — fix or
  drop that clamp when reviving it.

## When re-implementing, do it robustly

- Wrap seesaw init in try/except per address and skip absent dials — a missing/loose
  encoder must not crash startup (this was the original defect). Arm nothing that a
  disconnected dial can take down.
- Drive reads from an async task (like the other `handle_*` loops) at ~10 Hz.
