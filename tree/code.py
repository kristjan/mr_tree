import asyncio
import board
import os
import socketpool
import wifi
import mdns
import json
from microcontroller import watchdog
from watchdog import WatchDogMode
from adafruit_httpserver.server import Server, Request, Response
from adafruit_seesaw.seesaw import Seesaw
from adafruit_seesaw.rotaryio import IncrementalEncoder
from adafruit_seesaw.digitalio import DigitalIO
from adafruit_minimqtt.adafruit_minimqtt import MQTT

from tree import Tree
from effects.rainbow_cycle import RainbowCycle
from effects.sweep import Sweep
from effects.timer import Timer
from util.mqtt import (
    set_mqtt_client, publish_message,
    MQTT_TOPIC_STATE, MQTT_TOPIC_SET, MQTT_TOPIC_AVAILABILITY,
    MQTT_DISCOVERY_PREFIX, MQTT_DISCOVERY_TOPIC, MQTT_TIMER_STATE,
    MQTT_TIMER_SET, MQTT_TIMER_DISCOVERY_TOPIC
)

# Set up watchdog with a 10 second timeout
watchdog.timeout = 10.0  # 10 seconds
watchdog.mode = WatchDogMode.RESET  # Reset the system when watchdog expires
watchdog.feed()  # Feed it once before starting main program

print("Creating tree...")
tree = Tree()
print("Tree created!")
tree.on()

print("Connecting to WiFi...")
wifi.radio.connect(os.getenv("WIFI_SSID"), os.getenv("WIFI_PASSWORD"))
print("Connected!", str(wifi.radio.ipv4_address))

# Set up socket pool
pool = socketpool.SocketPool(wifi.radio)

print("Starting mDNS...")
try:
    mdns_name = os.getenv("MDNS_NAME")
    mdns_server = mdns.Server(wifi.radio)
    mdns_server.hostname = mdns_name
    mdns_server.advertise_service(service_type="_http", protocol="_tcp", port=os.getenv("SERVER_PORT"))
    print(f"mDNS started at {mdns_name}.local")
except Exception as e:
    print(f"Failed to start mDNS: {e}")
    print("Continuing without mDNS...")

# Set up HTTP server
server = Server(pool, "/static", debug=True)

# Set up MQTT client
print("Setting up MQTT client...")
mqtt_client = MQTT(
    broker=os.getenv("MQTT_BROKER"),
    port=int(os.getenv("MQTT_PORT", "1883")),
    username=os.getenv("MQTT_USERNAME"),
    password=os.getenv("MQTT_PASSWORD"),
    socket_pool=pool,
    socket_timeout=0.01  # Reduce socket timeout to 10ms
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
    except Exception as e:
        print(f"Error publishing discovery config: {e}")

def mqtt_connect(mqtt_client, userdata, flags, rc):
    """Handle MQTT connection."""
    print("Connected to MQTT broker!")
    mqtt_client.subscribe(MQTT_TOPIC_SET)
    mqtt_client.subscribe(MQTT_TIMER_SET)  # Subscribe to timer control topic
    mqtt_client.subscribe(f"{MQTT_TIMER_SET}/duration")  # Subscribe to timer duration topic
    # Clean up old discovery messages first
    cleanup_old_discovery()
    # Publish discovery configuration
    publish_discovery()
    # Publish online status
    mqtt_client.publish(MQTT_TOPIC_AVAILABILITY, "online", retain=True, qos=1)
    # Publish initial state
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
    except Exception as e:
        print(f"Error handling state change: {e}")
        raise

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

            # Always create a fresh timer instance when starting
            tree.set_animation("timer", {"duration": duration})
            tree.animation.start()
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
        message = json.dumps(tree_state)
        print(f"MQTT >> {MQTT_TOPIC_STATE}: {message}")
        mqtt_client.publish(MQTT_TOPIC_STATE, message)
    except Exception as e:
        print(f"Error publishing state: {e}")

# Set up MQTT callbacks
mqtt_client.on_connect = mqtt_connect
mqtt_client.on_message = mqtt_message

# Initialize rotary encoders
i2c = board.I2C()
encoders = []
for addr in [0x37, 0x38, 0x36]:
    ss = Seesaw(i2c, addr)
    ss.pin_mode(24, ss.INPUT_PULLUP)

    encoder = IncrementalEncoder(ss)
    button = DigitalIO(ss, 24)

    encoders.append((encoder, button))

@server.route("/")
def base(request: Request):
    """
    Serve a static control page
    """
    return Response(request, open("index.html", "r").read(), content_type="text/html")

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

        # Create fresh timer and start it
        tree.set_animation("timer", {"duration": duration})
        tree.animation.start()

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

def hex_to_rgb(hex):
    return tuple(int(hex[i:i+2], 16) for i in (0, 2, 4))

async def handle_requests():
    while True:
        server.poll()
        await asyncio.sleep(0.01)  # Actually sleep for 10ms to prevent busy loop

async def handle_encoders():
    last_positions = [0, 0, 0]
    while True:
        # for i, (encoder, button) in enumerate(encoders):
        #     position = encoder.position
        #     if position != last_positions[i]:
        #         diff = last_positions[i] - position
        #         last_positions[i] = position
        #         tree.turn(i, diff)
        #     if not button.value:
        #         tree.press(i)
        await asyncio.sleep(0.1)

async def handle_mqtt():
    """Handle MQTT message loop."""
    while True:
        try:
            mqtt_client.loop(timeout=0.1)  # Increase timeout to 100ms for stability
        except Exception as e:
            print(f"MQTT error: {e}")
            # Try to reconnect with backoff
            try:
                await asyncio.sleep(1)  # Wait before reconnecting
                mqtt_client.reconnect()
            except Exception as e:
                print(f"MQTT reconnection failed: {e}")
        await asyncio.sleep(0.5)  # Sleep for 500ms between polls

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

async def main():
    print("Starting server")
    server.start(str(wifi.radio.ipv4_address), 7433)
    print("Connecting to MQTT broker...")
    try:
        mqtt_client.connect()
    except Exception as e:
        print(f"Failed to connect to MQTT broker: {e}")
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
    print("Creating watchdog task")
    watchdog_task = asyncio.create_task(handle_watchdog())
    print("Starting tasks")
    try:
        await asyncio.gather(server_task, animation_task, encoder_task, mqtt_task, timer_task, watchdog_task)
    except Exception as e:
        print(f"Critical error in main loop: {e}")
        # Feed watchdog one more time before potentially restarting
        watchdog.feed()
        raise  # Re-raise to trigger restart
    print("Tasks started")

if __name__ == "__main__":
    asyncio.run(main())