"""Dial interaction controller: the mode state machine.

Translates dial turn/press events into tree operations, keeps mode + values
coherent with HA/MQTT commands, and drives the dials' onboard LED feedback.
See project/dials.md for the full interaction model.
"""

import time
from colorsys import hsv_to_rgb

from effects.timer import Timer
from util.encoders import LEFT, CENTER, RIGHT

# Modes
RGB = "rgb"
ANIMATION = "animation"
TIMER = "timer"

# Animations selectable via the dial (the timer is its own mode).
ANIMATIONS = ["rainbow_cycle", "sweep"]
ANIM_LED = {"rainbow_cycle": (40, 0, 40), "sweep": (0, 20, 60)}

MAX_MINUTES = 100
TIMER_AUTOSTART_S = 30
TIMER_SETUP_COLOR = (0, 0, 60)  # cool blue = "armed, not running"

RGB_STEP = 8       # base per-detent step for color channels
BRIGHT_STEP = 8    # base per-detent step for brightness


def _clamp(value, lo, hi):
    return max(lo, min(hi, int(value)))


def _clampf(value, lo, hi):
    return max(lo, min(hi, value))


def _accel(delta, base):
    """Signed step with acceleration: fast spins move much further per detent."""
    mag = abs(delta)
    step = base * mag * mag
    return step if delta >= 0 else -step


class Controller:
    def __init__(self, tree, dials, publish):
        self.tree = tree
        self.dials = dials
        self.publish = publish  # callable, publishes tree state to MQTT

        self.mode = RGB
        self.rgb = [51, 51, 51]  # matches the tree's default-on color
        try:
            self.brightness = tree.state()["brightness"]
        except Exception:
            self.brightness = 204

        self.anim_index = 0
        self.speed = 0.5            # 0-1
        self.sweep_hue = 0.66       # blue
        self.rainbow_bandwidth = 1.0

        self.timer_minutes = 5
        self._timer_editing = False
        self._last_input = time.monotonic()
        self._right_turned = False

    # ---- lifecycle ----------------------------------------------------

    def start(self):
        """Enter the default RGB mode at boot (no publish; MQTT may not be up yet)."""
        self.mode = RGB
        self.tree.set_color(tuple(self.rgb))
        self._update_leds()

    # ---- input polling ------------------------------------------------

    def poll(self):
        """Read all dials once and dispatch events. Call from the encoder task."""
        now = time.monotonic()
        right = self.dials.get(RIGHT)
        right_held = right.pressed if right else False

        for pos, dial in enumerate(self.dials.dials):
            if dial is None:
                continue
            delta = dial.read_delta()
            if delta != 0:
                self._on_turn(pos, delta, right_held)
            event = dial.poll_button()
            if event == "press":
                self._on_press(pos, right_held)
            elif event == "release":
                self._on_release(pos)

        if self.mode == TIMER and self._timer_editing and (now - self._last_input) >= TIMER_AUTOSTART_S:
            print("Timer auto-start after 30s idle")
            self._start_timer()

    # ---- event handlers ----------------------------------------------

    def _on_turn(self, pos, delta, right_held):
        self._last_input = time.monotonic()

        # Press-and-turn the right dial = master brightness, in any mode.
        if pos == RIGHT and right_held:
            self._right_turned = True
            self._adjust_brightness(delta)
            return

        if self.mode == RGB:
            self._adjust_channel(pos, delta)
        elif self.mode == ANIMATION:
            if pos == LEFT:
                self._cycle_animation(delta)
            elif pos == CENTER:
                self._adjust_speed(delta)
            elif pos == RIGHT:
                self._adjust_param(delta)
        elif self.mode == TIMER:
            if pos == CENTER and self._timer_editing:
                self._adjust_minutes(delta)

    def _on_press(self, pos, right_held):
        if pos == RIGHT:
            self._right_turned = False  # defer to release to detect press-turn
            return
        if right_held:
            return  # Left/Center ignored during a right press-turn
        if pos == LEFT:
            self.cycle_mode()
        elif pos == CENTER:
            self.toggle_power()

    def _on_release(self, pos):
        if pos != RIGHT:
            return
        if self._right_turned:
            self._right_turned = False
            return  # was a brightness press-turn, not a click
        if self.mode == TIMER:
            self._toggle_timer()

    # ---- modes --------------------------------------------------------

    def cycle_mode(self):
        if self.mode == RGB:
            self.set_mode(ANIMATION)
        elif self.mode == ANIMATION:
            self.set_mode(TIMER)
        else:  # TIMER -> cancel and return to RGB
            self._cancel_timer()
            self.set_mode(RGB)

    def set_mode(self, mode):
        self.mode = mode
        if mode == RGB:
            self.tree.set_color(tuple(self.rgb))
        elif mode == ANIMATION:
            self._start_animation()
        elif mode == TIMER:
            self._enter_timer()
        self._update_leds()
        self.publish()

    def toggle_power(self):
        if self.tree.is_on():
            self.tree.off()
        else:
            self.tree.on()
        self.publish()

    # ---- RGB ----------------------------------------------------------

    def _adjust_channel(self, pos, delta):
        self.rgb[pos] = _clamp(self.rgb[pos] + _accel(delta, RGB_STEP), 0, 255)
        self.tree.set_color(tuple(self.rgb))
        self._update_leds()
        self.publish()

    def _adjust_brightness(self, delta):
        self.brightness = _clamp(self.brightness + _accel(delta, BRIGHT_STEP), 0, 255)
        self.tree.set_brightness(self.brightness)
        self.publish()

    # ---- animation ----------------------------------------------------

    def _start_animation(self):
        name = ANIMATIONS[self.anim_index]
        self.tree.set_animation(name)
        self.tree.set_speed(self.speed)
        self._apply_anim_param()

    def _apply_anim_param(self):
        anim = self.tree.animation
        if anim is None:
            return
        name = ANIMATIONS[self.anim_index]
        if name == "sweep":
            anim.color = self._hue_to_rgb(self.sweep_hue)
        elif name == "rainbow_cycle":
            anim.bandwidth = self.rainbow_bandwidth

    def _cycle_animation(self, delta):
        step = 1 if delta > 0 else -1
        self.anim_index = (self.anim_index + step) % len(ANIMATIONS)
        self._start_animation()
        self._update_leds()
        self.publish()

    def _adjust_speed(self, delta):
        self.speed = _clampf(self.speed + delta * 0.05, 0.0, 1.0)
        self.tree.set_speed(self.speed)
        self._update_leds()
        self.publish()

    def _adjust_param(self, delta):
        name = ANIMATIONS[self.anim_index]
        if name == "sweep":
            self.sweep_hue = (self.sweep_hue + delta * 0.03) % 1.0
        elif name == "rainbow_cycle":
            self.rainbow_bandwidth = _clampf(self.rainbow_bandwidth + delta * 0.5, 1.0, 8.0)
        self._apply_anim_param()
        self._update_leds()
        self.publish()

    # ---- timer --------------------------------------------------------

    def _enter_timer(self):
        self._timer_editing = True
        self._last_input = time.monotonic()
        self._show_timer_preview()

    def _show_timer_preview(self):
        self.tree.preview_fill(self.timer_minutes / MAX_MINUTES, TIMER_SETUP_COLOR)

    def _adjust_minutes(self, delta):
        self.timer_minutes = _clamp(self.timer_minutes + _accel(delta, 1), 1, MAX_MINUTES)
        self._show_timer_preview()
        self._update_leds()
        self.publish()

    def _toggle_timer(self):
        if self._timer_editing:
            self._start_timer()
        else:
            anim = self.tree.animation
            if isinstance(anim, Timer):
                anim.pause()
                remaining = anim.get_state().get("remaining", 0)
                self.timer_minutes = _clamp(round(remaining / 60), 1, MAX_MINUTES)
            self._timer_editing = True
            self._last_input = time.monotonic()
            self._show_timer_preview()
            self._update_leds()
            self.publish()

    def _start_timer(self):
        if not self.tree.is_on():
            self.tree.on()
        self._timer_editing = False
        self.tree.set_animation("timer", {"duration": self.timer_minutes * 60})
        self.tree.animation.start()
        self._update_leds()
        self.publish()

    def _cancel_timer(self):
        anim = self.tree.animation
        if isinstance(anim, Timer):
            anim.cancel()
        self._timer_editing = False

    # ---- HA/MQTT coherence -------------------------------------------

    def sync_from_ha(self, params):
        """Update mode/values to match an HA command (tree already applied it)."""
        if "color" in params and isinstance(params["color"], dict):
            c = params["color"]
            self.rgb = [c.get("r", 0), c.get("g", 0), c.get("b", 0)]
            self.mode = RGB
        if "effect" in params:
            name = params["effect"]
            if name in ANIMATIONS:
                self.anim_index = ANIMATIONS.index(name)
                self.mode = ANIMATION
            elif name == "timer":
                self.mode = TIMER
                self._timer_editing = False
        if "brightness" in params:
            self.brightness = params["brightness"]
        if "speed" in params:
            self.speed = float(params["speed"]) / 100.0
        self._update_leds()

    # ---- LED feedback -------------------------------------------------

    def _set_led(self, pos, color):
        dial = self.dials.get(pos)
        if dial:
            dial.set_led(color)

    def _update_leds(self):
        if self.mode == RGB:
            self._set_led(LEFT, (self.rgb[0], 0, 0))
            self._set_led(CENTER, (0, self.rgb[1], 0))
            self._set_led(RIGHT, (0, 0, self.rgb[2]))
        elif self.mode == ANIMATION:
            name = ANIMATIONS[self.anim_index]
            self._set_led(LEFT, ANIM_LED.get(name, (30, 30, 30)))
            v = int(self.speed * 60)
            self._set_led(CENTER, (v, v, v))
            if name == "sweep":
                self._set_led(RIGHT, self._hue_to_rgb(self.sweep_hue))
            else:
                b = min(60, int(self.rainbow_bandwidth * 12))
                self._set_led(RIGHT, (b, b, 0))
        elif self.mode == TIMER:
            self._set_led(LEFT, (0, 0, 0))
            self._set_led(CENTER, (0, 60, 0) if self._timer_editing else (0, 0, 0))
            self._set_led(RIGHT, (0, 60, 0) if self._timer_editing else (60, 40, 0))

    def _hue_to_rgb(self, hue):
        return tuple(int(c * 255) for c in hsv_to_rgb(hue, 1.0, 1.0))
