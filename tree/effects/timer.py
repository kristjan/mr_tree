import time
import adafruit_led_animation.color as color
from colorsys import hsv_to_rgb
from util.tree_animation import TreeAnimation
import math

class Timer(TreeAnimation):
    def __init__(self, pixel_object, coordinates, speed, duration, name):
        """Initialize the timer effect.

        Args:
            pixel_object: The NeoPixel object
            coordinates: List of (x,y,z) coordinates for each LED
            speed: Animation speed
            duration: Timer duration in seconds
            name: Name of the effect
        """
        super().__init__(pixel_object=pixel_object, coordinates=coordinates, speed=speed, color=color.GREEN, name=name)
        self.duration = duration
        self.fade_duration = duration * 0.05  # 5% of timer duration
        self.start_time = None
        self.is_running = False
        self.completion_start = None
        self.completion_duration = 3.0  # Duration of completion effect in seconds
        self.pulse_start = time.monotonic()
        # Store last fill height and time for fade out effect
        self.last_fill_height = None
        self.fade_start_times = {}  # Dictionary to track when each LED starts fading
        self.was_lit = set()  # Track which LEDs were lit in previous frame

    def _get_pulse_brightness(self, z, z_max, z_min, fill_height):
        """Calculate brightness for pulse wave effect."""
        # Wave moves down every 2.5 seconds (1.5s for wave + 1s pause at bottom)
        wave_period = 2.5
        wave_time = (time.monotonic() - self.pulse_start) % wave_period

        # If in pause period at bottom, return full brightness
        if wave_time > 1.5:
            return 1.0

        # Convert time to position (top to bottom)
        wave_center = z_max - (wave_time / 1.5 * (z_max - z_min))

        # Only show wave below fill height (in the filled part)
        if z > fill_height:
            return None

        # Calculate distance from wave center
        distance = abs(z - wave_center)
        # Wave width is 10% of tree height
        wave_width = (z_max - z_min) * 0.10

        if distance > wave_width:
            return 1.0  # Full brightness for filled area outside wave

        # Smooth falloff using cosine, but invert it and make more pronounced
        brightness = 1.0 - (math.cos(distance / wave_width * math.pi / 2) * 0.7)
        return brightness

    def _get_fadeout_brightness(self, i, z, current_fill_height):
        """Calculate brightness for LEDs that are fading out."""
        # If LED is currently in the filled area, mark it as lit and return full brightness
        if z <= current_fill_height:
            self.was_lit.add(i)
            if i in self.fade_start_times:
                del self.fade_start_times[i]
            return 1.0

        # If LED was lit but is now above fill height, it should fade
        if i in self.was_lit:
            # Start the fade
            if i not in self.fade_start_times:
                self.fade_start_times[i] = time.monotonic()
                self.was_lit.remove(i)

        # If this LED is fading, calculate its brightness
        if i in self.fade_start_times:
            time_since_fade_start = time.monotonic() - self.fade_start_times[i]

            if time_since_fade_start > self.fade_duration:
                del self.fade_start_times[i]
                return 0.0

            # Smooth fade using cosine curve instead of linear
            progress = time_since_fade_start / self.fade_duration
            return (math.cos(progress * math.pi) + 1) / 2

        return 0.0

    def start(self):
        """Start the timer."""
        self.start_time = time.monotonic()
        self.is_running = True
        self.completion_start = None

    def draw(self):
        if not self.is_running:
            if self.completion_start is not None:
                self._draw_completion_effect()
            else:
                self.pixel_object.fill(color.BLACK)
            return

        elapsed = time.monotonic() - self.start_time
        remaining = max(0, self.duration - elapsed)
        progress = remaining / self.duration

        # Get z-coordinate bounds
        z_min, z_max = self._bounds[2]
        z_range = z_max - z_min

        # Calculate the current fill level
        fill_height = z_min + (z_range * progress)

        # Smooth color transitions between green->yellow->red
        if progress > 0.5:
            # Fade from green (0.33) to yellow (0.17) between 100% and 50%
            t = (progress - 0.5) * 2  # t goes from 0 to 1
            hue = 0.17 + (t * 0.16)   # interpolate between 0.17 and 0.33
        elif progress > 0.2:
            # Fade from yellow (0.17) to red (0.0) between 50% and 20%
            t = (progress - 0.2) / 0.3  # t goes from 0 to 1
            hue = t * 0.17  # interpolate between 0.0 and 0.17
        else:
            # Stay red
            hue = 0.0

        # Convert current color to RGB once
        current_rgb = [int(c * 255) for c in hsv_to_rgb(hue, 1.0, 1.0)]

        for i, (x, y, z) in enumerate(self._coordinates):
            # Get fade-out brightness for this LED
            fade_brightness = self._get_fadeout_brightness(i, z, fill_height)

            if fade_brightness > 0:
                # Always calculate pulse brightness, even for fading LEDs
                pulse_brightness = self._get_pulse_brightness(z, z_max, z_min, fill_height)
                # Default to full brightness if outside pulse area
                pulse_brightness = 1.0 if pulse_brightness is None else pulse_brightness

                # Combine fade and pulse brightness
                final_brightness = fade_brightness * pulse_brightness
                self.pixel_object[i] = [int(c * final_brightness) for c in current_rgb]
            else:
                self.pixel_object[i] = color.BLACK

        # Store current fill height for next frame
        self.last_fill_height = fill_height

        # Stop the animation when time is up
        if remaining <= 0:
            self.is_running = False
            self.completion_start = time.monotonic()

    def _draw_completion_effect(self):
        """Draw a continuous rainbow wave moving up the tree, pausing when fully lit."""
        elapsed = time.monotonic() - self.completion_start
        z_min, z_max = self._bounds[2]
        z_range = z_max - z_min

        # Complete cycle is 3 seconds: 2s for wave + 1s pause
        cycle_time = elapsed % 3.0

        if cycle_time >= 2.0:
            # During pause, keep tree fully illuminated
            for i, (x, y, z) in enumerate(self._coordinates):
                # Map height to hue: bottom is cyan (0.5), wraps through blue, purple, red, orange, yellow to green (0.33)
                # This gives us 0.83 of the color wheel to work with
                hue = 0.5 + ((z - z_min) / z_range * 0.83) % 1.0
                rgb = [int(c * 255) for c in hsv_to_rgb(hue, 1.0, 1.0)]
                self.pixel_object[i] = rgb
        else:
            # During wave animation
            wave_position = (cycle_time * z_range / 2.0)
            wave_height = z_min + wave_position

            for i, (x, y, z) in enumerate(self._coordinates):
                if z <= wave_height:
                    # Map height to hue: bottom is cyan (0.5), wraps through blue, purple, red, orange, yellow to green (0.33)
                    hue = 0.5 + ((z - z_min) / z_range * 0.83) % 1.0
                    rgb = [int(c * 255) for c in hsv_to_rgb(hue, 1.0, 1.0)]
                    self.pixel_object[i] = rgb
                else:
                    self.pixel_object[i] = color.BLACK