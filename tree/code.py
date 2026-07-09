import asyncio
import board
import busio
import os
import time
import socketpool
import wifi
import mdns
import json
from microcontroller import watchdog
from watchdog import WatchDogMode
from adafruit_httpserver.server import Server, Request, Response
from adafruit_minimqtt.adafruit_minimqtt import MQTT

from tree import Tree
from effects.timer import Timer
from util.encoders import Dials
from util.controller import Controller
from util.mqtt import (
    set_mqtt_client, publish_message,
    MQTT_TOPIC_STATE, MQTT_TOPIC_SET, MQTT_TOPIC_AVAILABILITY,
    MQTT_DISCOVERY_PREFIX, MQTT_DISCOVERY_TOPIC, MQTT_TIMER_STATE,
    MQTT_TIMER_SET, MQTT_TIMER_DISCOVERY_TOPIC
)

# Configure the watchdog with a 10 second timeout. It is deliberately NOT armed
# here: blocking WiFi/MQTT setup during startup can take longer than the timeout,
# and nothing feeds the watchdog until the feeder task starts. Arming it now would
# reset (and bootloop) the board whenever the network or broker is slow/absent.
# It is armed in main() once network setup is complete.
watchdog.timeout = 10.0  # 10 seconds

print("Creating tree...")
tree = Tree()
print("Tree created!")
tree.on()

print("Connecting to WiFi...")
for attempt in range(10):
    try:
        wifi.radio.connect(os.getenv("WIFI_SSID"), os.getenv("WIFI_PASSWORD"))
        break
    except Exception as e:
        print(f"WiFi connection attempt {attempt + 1}/10 failed: {e}")
        time.sleep(2)
print("Connected!", str(wifi.radio.ipv4_address))

# Set up socket pool
pool = socketpool.SocketPool(wifi.radio)

print("Starting mDNS...")
try:
    mdns_name = os.getenv("MDNS_NAME")
    mdns_server = mdns.Server(wifi.radio)
    mdns_server.hostname = mdns_name
    mdns_server.advertise_service(service_type="_http", protocol="_tcp", port=int(os.getenv("SERVER_PORT")))
    print(f"mDNS started at {mdns_name}.local")
except Exception as e:
    print(f"Failed to start mDNS: {e}")
    print("Continuing without mDNS...")

# Set up HTTP server
server = Server(pool, "/static", debug=False)

# Set up MQTT client
print("Setting up MQTT client...")
mqtt_client = MQTT(
    broker=os.getenv("MQTT_BROKER"),
    port=int(os.getenv("MQTT_PORT", "1883")),
    username=os.getenv("MQTT_USERNAME"),
    password=os.getenv("MQTT_PASSWORD"),
    socket_pool=pool,
    socket_timeout=0.02,  # 20ms timeout for smooth 30fps animation
    recv_timeout=5  # bound blocking connect/reconnect below the 10s watchdog window
)

# Initialize MQTT utilities
set_mqtt_client(mqtt_client)

# Set up Last Will and Testament
mqtt_client.will_set(
    topic=MQTT_TOPIC_AVAILABILITY,
    msg="offline",
    retain=True,  # Retain the message so HA knows state even after restart
    qos=1  # Use QoS 1 to ensure message delivery
)

def cleanup_old_discovery():
    """Send empty discovery messages to remove old entities with redundant names."""
    old_topics = [
        f"{MQTT_DISCOVERY_PREFIX}/light/mr_tree/mr_tree_light/config",
        f"{MQTT_DISCOVERY_PREFIX}/sensor/mr_tree_timer/mr_tree_timer/config",
        f"{MQTT_DISCOVERY_PREFIX}/number/mr_tree/mr_tree_timer_duration/config",
        f"{MQTT_DISCOVERY_PREFIX}/button/mr_tree/mr_tree_timer_start/config",
        f"{MQTT_DISCOVERY_PREFIX}/button/mr_tree/mr_tree_timer_pause/config",
        f"{MQTT_DISCOVERY_PREFIX}/button/mr_tree/mr_tree_timer_cancel/config"
    ]

    for topic in old_topics:
        publish_message(topic, "", retain=True)
        print(f"Sent cleanup message to {topic}")

def publish_discovery():
    """Publish MQTT discovery configuration for Home Assistant."""
    device = {
        "identifiers": ["mr_tree"],
        "name": "Mr Tree",
        "model": "LED Tree",
        "manufacturer": "Haha Moment",
        "sw_version": "1.0.0",
        "configuration_url": f"http://{wifi.radio.ipv4_address}:7433"
    }

    # Light config
    light_config = {
        "name": "Light",
        "unique_id": "light",
        "command_topic": MQTT_TOPIC_SET,
        "state_topic": MQTT_TOPIC_STATE,
        "schema": "json",
        "brightness": True,
        "rgb": True,
        "effect": True,
        "effect_list": Tree.EFFECTS,
        "supported_color_modes": ["rgb"],
        "optimistic": False,
        "qos": 1,
        "retain": True,
        "device": device,
        "json_attributes_topic": MQTT_TOPIC_STATE,
        "json_attributes_template": "{{ {'animation_state': value_json.animation_state} | tojson }}",
        "availability_topic": MQTT_TOPIC_AVAILABILITY,
        "payload_available": "online",
        "payload_not_available": "offline"
    }

    # Timer sensor config
    timer_config = {
        "name": "Timer",
        "unique_id": "timer",
        "state_topic": MQTT_TIMER_STATE,
        "device_class": "duration",
        "unit_of_measurement": "s",
        "value_template": "{{ value_json.remaining }}",
        "json_attributes_topic": MQTT_TIMER_STATE,
        "json_attributes_template": "{{ {'duration': value_json.duration, 'state': value_json.state} | tojson }}",
        "device": device,
        "availability_topic": MQTT_TOPIC_AVAILABILITY,
        "payload_available": "online",
        "payload_not_available": "offline"
    }

    # Timer duration number config
    timer_duration_config = {
        "name": "Timer Duration",
        "unique_id": "timer_duration",
        "command_topic": f"{MQTT_TIMER_SET}/duration",
        "state_topic": MQTT_TIMER_STATE,
        "value_template": "{{ value_json.duration }}",
        "device_class": "duration",
        "unit_of_measurement": "s",
        "min": 1,
        "max": 86400,  # 24 hours (full day)
        "step": 1,
        "device": device,
        "icon": "mdi:timer-cog",
        "availability_topic": MQTT_TOPIC_AVAILABILITY,
        "payload_available": "online",
        "payload_not_available": "offline"
    }

    # Timer control buttons
    timer_buttons = [
        {
            "name": "Start Timer",
            "unique_id": "timer_start",
            "command_topic": MQTT_TIMER_SET,
            "payload_press": '{"command": "start"}',  # JSON string
            "device": device,
            "icon": "mdi:timer-play",
            "availability_topic": MQTT_TOPIC_AVAILABILITY,
            "payload_available": "online",
            "payload_not_available": "offline"
        },
        {
            "name": "Pause Timer",
            "unique_id": "timer_pause",
            "command_topic": MQTT_TIMER_SET,
            "payload_press": '{"command": "pause"}',  # JSON string
            "device": device,
            "icon": "mdi:timer-pause",
            "availability_topic": MQTT_TOPIC_AVAILABILITY,
            "payload_available": "online",
            "payload_not_available": "offline"
        },
        {
            "name": "Cancel Timer",
            "unique_id": "timer_cancel",
            "command_topic": MQTT_TIMER_SET,
            "payload_press": '{"command": "cancel"}',  # JSON string
            "device": device,
            "icon": "mdi:timer-off",
            "availability_topic": MQTT_TOPIC_AVAILABILITY,
            "payload_available": "online",
            "payload_not_available": "offline"
        }
    ]

    try:
        print(f"Publishing discovery config to {MQTT_DISCOVERY_TOPIC}")
        publish_message(MQTT_DISCOVERY_TOPIC, light_config, retain=True)

        print(f"Publishing timer discovery config to {MQTT_TIMER_DISCOVERY_TOPIC}")
        publish_message(MQTT_TIMER_DISCOVERY_TOPIC, timer_config, retain=True)

        # Publish timer duration number
        topic = f"{MQTT_DISCOVERY_PREFIX}/number/mr_tree/timer_duration/config"
        print(f"Publishing timer duration config to {topic}")
        publish_message(topic, timer_duration_config, retain=True)

        # Publish timer control buttons
        for button in timer_buttons:
            topic = f"{MQTT_DISCOVERY_PREFIX}/button/mr_tree/{button['unique_id']}/config"
            print(f"Publishing timer button config to {topic}")
            publish_message(topic, button, retain=True)

        print("All discovery configurations published successfully!")
    except Exception as e:
        print(f"Error publishing discovery config: {e}")
        import traceback
        traceback.print_exc()

def mqtt_connect(mqtt_client, userdata, flags, rc):
    """Handle MQTT connection."""
    print(f"Connected to MQTT broker! (rc={rc})")
    print(f"Subscribing to topics:")
    print(f"  - {MQTT_TOPIC_SET}")
    print(f"  - {MQTT_TIMER_SET}")
    print(f"  - {MQTT_TIMER_SET}/duration")

    mqtt_client.subscribe(MQTT_TOPIC_SET)
    mqtt_client.subscribe(MQTT_TIMER_SET)  # Subscribe to timer control topic
    mqtt_client.subscribe(f"{MQTT_TIMER_SET}/duration")  # Subscribe to timer duration topic

    # Clean up old discovery messages first
    print("Cleaning up old discovery messages...")
    cleanup_old_discovery()

    # Publish discovery configuration
    print("Publishing discovery configuration...")
    publish_discovery()

    # Publish online status
    print("Publishing online status...")
    publish_message(MQTT_TOPIC_AVAILABILITY, "online", retain=True)

    # Publish initial state
    print("Publishing initial state...")
    publish_state()

def handle_state_change(state_params):
    """Handle state changes from any source (MQTT or HTTP).

    Args:
        state_params: dict containing any of: state, brightness, color, effect, effect_params, speed, animation_state
    Returns:
        None
    """
    try:
        if "state" in state_params:
            if state_params["state"] == "ON":
                tree.on()
            elif state_params["state"] == "OFF":
                tree.off()

        if "effect" in state_params:
            effect = state_params["effect"]
            effect_params = state_params.get("effect_params", {})
            tree.set_animation(effect, effect_params)
        elif "color" in state_params:
            # Expect RGB dict from HA
            color = state_params["color"]
            if isinstance(color, dict):
                r = color.get("r", 0)
                g = color.get("g", 0)
                b = color.get("b", 0)
                tree.set_color((r, g, b))

        if "brightness" in state_params:
            # Expect brightness as 0-255
            tree.set_brightness(state_params["brightness"])

        if "speed" in state_params:
            # Expect speed as 0-100
            tree.set_speed(float(state_params["speed"]) / 100)

        if "animation_state" in state_params:
            if state_params["animation_state"] == "paused":
                tree.pause()
            elif state_params["animation_state"] == "running":
                tree.resume()

        publish_state()
        # Keep the dial controller's mode/values coherent with HA commands.
        controller.sync_from_ha(state_params)
    except Exception as e:
        print(f"Error handling state change: {e}")
        raise

def start_timer(duration=300):
    """Turn the tree on if needed, then start a fresh timer for `duration` seconds."""
    if not tree.is_on():
        tree.on()
        publish_state()  # Notify subscribers of the implicit ON
    tree.set_animation("timer", {"duration": duration})
    tree.animation.start()

def handle_timer_message(message):
    """Handle timer control messages.

    Expected message format:
    {
        "command": "start"|"resume"|"pause"|"cancel",
        "duration": seconds  # Optional, only for start command
    }
    """
    try:
        data = json.loads(message)
        command = data.get("command", "").lower()

        # Get current animation if it's a timer
        current_animation = getattr(tree, "animation", None)
        is_timer = isinstance(current_animation, Timer)

        if command == "start":
            # Use duration from message, or from existing timer, or default to 300
            if "duration" in data:
                duration = data["duration"]
            elif is_timer:
                duration = current_animation.duration
            else:
                duration = 300  # Default 5 minutes
            start_timer(duration)
        elif command == "resume" and is_timer:
            current_animation.resume()
        elif command == "pause" and is_timer:
            current_animation.pause()
        elif command == "cancel" and is_timer:
            current_animation.cancel()
    except Exception as e:
        print(f"Error handling timer message: {e}")

def mqtt_message(mqtt_client, topic, message):
    """Handle incoming MQTT messages."""
    print(f"MQTT << {topic}: {message}")
    try:
        if topic == MQTT_TOPIC_SET:
            state = json.loads(message)
            handle_state_change(state)
        elif topic == f"{MQTT_TIMER_SET}/duration":
            # Handle duration number input - only set duration, don't start or cancel
            duration = int(float(message))  # Handle both integer and float inputs
            print(f"Setting timer duration to {duration} seconds")
            if isinstance(tree.animation, Timer):
                tree.animation.set_duration(duration)
            else:
                # Create a timer with the specified duration but don't start it
                tree.set_animation("timer", {"duration": duration})
        elif topic == MQTT_TIMER_SET:
            handle_timer_message(message)
    except Exception as e:
        print(f"Error handling MQTT message: {e}")

def publish_state():
    """Publish the current state to MQTT."""
    try:
        tree_state = tree.state()
        # Tree state is already in HA format, no need to convert
        publish_message(MQTT_TOPIC_STATE, tree_state)
    except Exception as e:
        print(f"Error publishing state: {e}")

# Set up MQTT callbacks
mqtt_client.on_connect = mqtt_connect
mqtt_client.on_message = mqtt_message

# Set up dials (rotary encoders). Missing/failed dials are skipped so the tree
# still runs over MQTT without them.
print("Initializing dials...")
# Run the seesaw bus at 400kHz so per-poll dial reads are ~4x faster and steal
# less time from the render loop. Fall back to the default bus if unavailable.
try:
    i2c = busio.I2C(board.SCL, board.SDA, frequency=400_000)
except Exception as e:
    print(f"Fast I2C unavailable ({e}); using default bus")
    i2c = board.I2C()
dials = Dials(i2c)
if dials.any_present:
    dials.calibrate()
controller = Controller(tree, dials, publish_state)

@server.route("/")
def base(request: Request):
    """
    Serve a static control page
    """
    # The control page is a dev-time convenience (primary control is MQTT/dial),
    # so read it per request rather than holding it in RAM permanently. The `with`
    # block closes the file handle, which the previous open().read() leaked.
    with open("index.html", "r") as f:
        return Response(request, f.read(), content_type="text/html")

@server.route("/on")
def on(request: Request):
    """
    Turn the tree on.
    """
    handle_state_change({"state": "ON"})
    return Response(request, "Tree on")

@server.route("/off")
def off(request: Request):
    """
    Turn the tree off.
    """
    handle_state_change({"state": "OFF"})
    return Response(request, "Tree off")

@server.route("/color/<color>")
def color(request: Request, color: str):
    """
    Set the tree color.
    """
    rgb = hex_to_rgb(color)
    handle_state_change({"color": {"r": rgb[0], "g": rgb[1], "b": rgb[2]}})
    return Response(request, f"Tree color set to {color}")

@server.route("/brightness/<brightness>")
def brightness(request: Request, brightness: str):
    """
    Set the tree brightness.
    """
    handle_state_change({"brightness": int(brightness)})
    return Response(request, f"Tree brightness set to {brightness}")

@server.route("/effect/<effect>", methods=["POST"])
def effect(request: Request, effect: str):
    """
    Set the tree effect with optional parameters.
    """
    params = {}
    if request.body:
        try:
            params = json.loads(request.body.decode())
        except json.JSONDecodeError:
            return Response(request, "Invalid JSON parameters", status=400)

    handle_state_change({"effect": effect, "effect_params": params})
    return Response(request, "Tree effect set")

@server.route("/pause")
def pause(request: Request):
    """
    Pause the tree effect.
    """
    handle_state_change({"animation_state": "paused"})
    return Response(request, "Tree effect paused")

@server.route("/resume")
def resume(request: Request):
    """
    Resume the tree effect.
    """
    handle_state_change({"animation_state": "running"})
    return Response(request, "Tree effect resumed")

@server.route("/speed/<speed>")
def speed(request: Request, speed: str):
    """
    Set the animation speed.
    """
    handle_state_change({"speed": float(speed)})
    return Response(request, f"Tree animation speed set to {speed}")

@server.route("/state")
def get_state(request: Request):
    """
    Get the tree state.
    """
    return Response(request, json.dumps(tree.state()), content_type="application/json")

@server.route("/state", methods=["POST"])
def set_state(request: Request):
    """
    Set multiple tree attributes at once.
    Accepts JSON body with any of: state, brightness, color, effect, effect_params
    Returns the new state.
    """
    try:
        params = json.loads(request.body.decode())
        handle_state_change(params)
        return Response(request, json.dumps(tree.state()), content_type="application/json")
    except json.JSONDecodeError:
        return Response(request, "Invalid JSON", status=400)
    except Exception as e:
        return Response(request, f"Error: {str(e)}", status=400)

@server.route("/timer/start", methods=["POST"])
def timer_start(request: Request):
    """
    Start a timer with optional duration.
    Accepts JSON body with: duration (optional, defaults to 300 seconds)
    """
    try:
        duration = 300  # Default 5 minutes
        if request.body:
            params = json.loads(request.body.decode())
            duration = params.get("duration", 300)

        start_timer(duration)

        return Response(request, json.dumps({"message": f"Timer started for {duration} seconds"}), content_type="application/json")
    except json.JSONDecodeError:
        return Response(request, "Invalid JSON", status=400)
    except Exception as e:
        return Response(request, f"Error: {str(e)}", status=400)

@server.route("/timer/pause", methods=["POST"])
def timer_pause(request: Request):
    """
    Pause the current timer.
    """
    try:
        if isinstance(tree.animation, Timer):
            tree.animation.pause()
            return Response(request, json.dumps({"message": "Timer paused"}), content_type="application/json")
        else:
            return Response(request, "No timer running", status=400)
    except Exception as e:
        return Response(request, f"Error: {str(e)}", status=400)

@server.route("/timer/resume", methods=["POST"])
def timer_resume(request: Request):
    """
    Resume the current timer.
    """
    try:
        if isinstance(tree.animation, Timer):
            tree.animation.resume()
            return Response(request, json.dumps({"message": "Timer resumed"}), content_type="application/json")
        else:
            return Response(request, "No timer running", status=400)
    except Exception as e:
        return Response(request, f"Error: {str(e)}", status=400)

@server.route("/timer/cancel", methods=["POST"])
def timer_cancel(request: Request):
    """
    Cancel the current timer.
    """
    try:
        if isinstance(tree.animation, Timer):
            tree.animation.cancel()
            return Response(request, json.dumps({"message": "Timer cancelled"}), content_type="application/json")
        else:
            return Response(request, "No timer running", status=400)
    except Exception as e:
        return Response(request, f"Error: {str(e)}", status=400)

@server.route("/timer/state")
def timer_state(request: Request):
    """
    Get the current timer state.
    """
    try:
        if isinstance(tree.animation, Timer):
            return Response(request, json.dumps(tree.animation.get_state()), content_type="application/json")
        else:
            return Response(request, json.dumps({"remaining": 0, "duration": 0, "state": "idle"}), content_type="application/json")
    except Exception as e:
        return Response(request, f"Error: {str(e)}", status=400)

def _inspect_light(indices):
    """Testbed helper: freeze animations and light exactly `indices` white so a
    physical LED can be located (for section tagging and coordinate fixing)."""
    tree.pause()
    if tree.string.brightness == 0:
        tree.string.brightness = 0.3  # ensure visible even if the tree was 'off'
    tree.string.fill((0, 0, 0))
    for i in indices:
        if 0 <= i < len(tree.string):
            tree.string[i] = (255, 255, 255)
    tree.string.show()

@server.route("/inspect/<index>")
def inspect(request: Request, index: str):
    """Light a single LED and report its stored coordinate."""
    i = int(index)
    _inspect_light([i])
    x, y, z = tree.coordinates[i]
    return Response(request, json.dumps({"index": i, "x": x, "y": y, "z": z}), content_type="application/json")

@server.route("/inspect/range/<start>/<end>")
def inspect_range(request: Request, start: str, end: str):
    """Light a contiguous LED range (inclusive) to preview a candidate section."""
    a, b = int(start), int(end)
    indices = list(range(min(a, b), max(a, b) + 1))
    _inspect_light(indices)
    return Response(request, json.dumps({"start": a, "end": b, "count": len(indices)}), content_type="application/json")

@server.route("/inspect/off")
def inspect_off(request: Request):
    """Exit inspect mode by re-rendering the controller's current mode."""
    controller.set_mode(controller.mode)
    return Response(request, "inspect off")

# ---- Binary-coded capture (for photogrammetry) -----------------------------
# Plays a timed sequence a camera can record: two all-on markers bracket N
# bit-frames (frame k lights LEDs whose index has bit k set), each preceded by a
# dark gap. Offline, blobs are located and their on/off pattern across frames
# decodes each blob's LED index; multiple angles triangulate to 3D coordinates.
_capture_pending = False
_capture_dur = 1.2      # seconds each bit-frame is held
_capture_bright = 0.08  # LED brightness during capture (low, to avoid bloom)

def _capture_bits():
    bits = 1
    while (1 << bits) < len(tree.string):
        bits += 1
    return bits

def _begin_capture(request, dur, bright):
    global _capture_pending, _capture_dur, _capture_bright
    _capture_dur = dur
    _capture_bright = bright
    _capture_pending = True
    bits = _capture_bits()
    gap, marker = 0.4, 1.0
    total = 0.6 + marker + bits * (gap + dur) + gap + marker + 0.4
    return Response(request, json.dumps({
        "leds": len(tree.string), "bits": bits, "frame_dur": dur, "brightness": bright,
        "gap_dur": gap, "marker_dur": marker, "estimated_seconds": round(total, 1),
        "note": "Record now: two all-on markers bracket the bit-frames.",
    }), content_type="application/json")

@server.route("/capture/start")
def capture_start(request: Request):
    return _begin_capture(request, _capture_dur, _capture_bright)

@server.route("/capture/start/<dur>")
def capture_start_dur(request: Request, dur: str):
    return _begin_capture(request, float(dur), _capture_bright)

@server.route("/capture/start/<dur>/<bright>")
def capture_start_dur_bright(request: Request, dur: str, bright: str):
    return _begin_capture(request, float(dur), float(bright))

def hex_to_rgb(hex):
    return tuple(int(hex[i:i+2], 16) for i in (0, 2, 4))

async def handle_requests():
    while True:
        server.poll()
        await asyncio.sleep(0)  # Yield control immediately to other tasks

async def handle_mqtt():
    """Handle MQTT message loop."""
    connection_retries = 0
    max_retries = 5

    while True:
        try:
            mqtt_client.loop(timeout=0.02)  # Must be >= socket timeout (0.02s)
            connection_retries = 0  # Reset retry counter on successful loop
        except Exception as e:
            print(f"MQTT error: {e}")
            connection_retries += 1

            if connection_retries <= max_retries:
                # Try to reconnect with exponential backoff
                backoff_time = min(2 ** connection_retries, 30)  # Cap at 30 seconds
                print(f"MQTT reconnection attempt {connection_retries}/{max_retries} in {backoff_time}s")
                await asyncio.sleep(backoff_time)

                try:
                    mqtt_client.reconnect()
                    print("MQTT reconnected successfully")
                except Exception as reconnect_error:
                    print(f"MQTT reconnection failed: {reconnect_error}")
            else:
                print("MQTT max retries exceeded, continuing with degraded functionality")
                await asyncio.sleep(30)  # Wait longer before trying again
                connection_retries = 0  # Reset counter for next batch of attempts

        await asyncio.sleep(0.01)  # Short sleep to allow animation task to run frequently

async def handle_encoders():
    """Poll the dials and dispatch turn/press interactions to the controller."""
    if not dials.any_present:
        print("No dials present; encoder task idle")
        return
    controller.start()
    while True:
        try:
            controller.poll()
        except Exception as e:
            print(f"Encoder poll error: {e}")
        await asyncio.sleep(0.03)  # ~33Hz: responsive for dials, light on the loop

async def run_capture(dur):
    """Play the binary-coded capture sequence (non-blocking via awaits)."""
    n = len(tree.string)
    bits = _capture_bits()
    gap, marker = 0.4, 1.0
    prev_brightness = tree.string.brightness
    tree.pause()
    tree.string.brightness = _capture_bright
    print(f"Capture: {bits} bit-frames over ~{n} LEDs, {dur}s each, brightness {_capture_bright}")

    def fill(color):
        tree.string.fill(color)
        tree.string.show()

    def show_bit(k):
        for i in range(n):
            tree.string[i] = (255, 255, 255) if (i >> k) & 1 else (0, 0, 0)
        tree.string.show()

    fill((0, 0, 0)); await asyncio.sleep(0.6)
    fill((255, 255, 255)); await asyncio.sleep(marker)      # start marker
    for k in range(bits):
        fill((0, 0, 0)); await asyncio.sleep(gap)
        show_bit(k); await asyncio.sleep(dur)
    fill((0, 0, 0)); await asyncio.sleep(gap)
    fill((255, 255, 255)); await asyncio.sleep(marker)      # end marker
    fill((0, 0, 0)); await asyncio.sleep(0.4)

    tree.string.brightness = prev_brightness
    controller.set_mode(controller.mode)  # resume normal display
    print("Capture sequence complete")

async def handle_capture():
    """Run a capture sequence when one is requested via /capture/start."""
    global _capture_pending
    while True:
        if _capture_pending:
            _capture_pending = False
            try:
                await run_capture(_capture_dur)
            except Exception as e:
                print(f"Capture error: {e}")
        await asyncio.sleep(0.1)

async def handle_watchdog():
    """Feed the watchdog periodically."""
    feed_count = 0
    while True:
        try:
            watchdog.feed()
            feed_count += 1
            if feed_count % 30 == 0:  # Log every 30 seconds
                print(f"Watchdog fed {feed_count} times")
        except Exception as e:
            print(f"Watchdog feed error: {e}")
        await asyncio.sleep(1)

async def handle_timer_updates():
    """Handle periodic timer state updates via MQTT."""
    while True:
        try:
            if isinstance(tree.animation, Timer):
                publish_message(MQTT_TIMER_STATE, tree.animation.get_state())
        except Exception as e:
            print(f"Error publishing timer state: {e}")
        await asyncio.sleep(1)  # Update every second

async def handle_availability_heartbeat():
    """Send periodic availability heartbeat to maintain online status."""
    while True:
        try:
            # Send availability heartbeat every 30 seconds
            publish_message(MQTT_TOPIC_AVAILABILITY, "online", retain=True)
            print("Sent availability heartbeat")
        except Exception as e:
            print(f"Error sending availability heartbeat: {e}")
        await asyncio.sleep(30)

async def main():
    print("Starting server")
    server.start(str(wifi.radio.ipv4_address), 7433)
    print("Connecting to MQTT broker...")

    # Try to connect to MQTT with retries
    mqtt_connected = False
    for attempt in range(3):
        try:
            mqtt_client.connect()
            mqtt_connected = True
            print("Successfully connected to MQTT broker!")
            break
        except Exception as e:
            print(f"MQTT connection attempt {attempt + 1}/3 failed: {e}")
            if attempt < 2:  # Don't sleep on the last attempt
                await asyncio.sleep(2)

    if not mqtt_connected:
        print("WARNING: Failed to connect to MQTT broker after 3 attempts")
        print("Device will continue with degraded functionality (no Home Assistant integration)")

    # Network setup is done: arm the watchdog now. From here the feeder task keeps
    # it alive, and recv_timeout bounds any single blocking network call below 10s.
    watchdog.mode = WatchDogMode.RESET
    watchdog.feed()

    print("Creating server task")
    server_task = asyncio.create_task(handle_requests())
    print("Creating animation task")
    animation_task = asyncio.create_task(tree.animate())
    print("Creating encoder task")
    encoder_task = asyncio.create_task(handle_encoders())
    print("Creating MQTT task")
    mqtt_task = asyncio.create_task(handle_mqtt())
    print("Creating timer updates task")
    timer_task = asyncio.create_task(handle_timer_updates())
    print("Creating availability heartbeat task")
    heartbeat_task = asyncio.create_task(handle_availability_heartbeat())
    print("Creating capture task")
    capture_task = asyncio.create_task(handle_capture())
    print("Creating watchdog task")
    watchdog_task = asyncio.create_task(handle_watchdog())
    print("Starting tasks")
    try:
        await asyncio.gather(server_task, animation_task, encoder_task, mqtt_task, timer_task, heartbeat_task, capture_task, watchdog_task)
    except Exception as e:
        print(f"Critical error in main loop: {e}")
        # Feed watchdog one more time before potentially restarting
        watchdog.feed()
        raise  # Re-raise to trigger restart
    print("Tasks started")

if __name__ == "__main__":
    asyncio.run(main())