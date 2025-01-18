import asyncio
import board
import os
import socketpool
import wifi
import mdns
import json
from adafruit_httpserver.server import Server, Request, Response
from adafruit_seesaw.seesaw import Seesaw
from adafruit_seesaw.rotaryio import IncrementalEncoder
from adafruit_seesaw.digitalio import DigitalIO
from adafruit_minimqtt.adafruit_minimqtt import MQTT

from tree import Tree
from effects.rainbow_cycle import RainbowCycle
from effects.sweep import Sweep

# MQTT topics
MQTT_TOPIC_STATE = "mr_tree/state"
MQTT_TOPIC_SET = "mr_tree/set"

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
)

def mqtt_connect(mqtt_client, userdata, flags, rc):
    """Handle MQTT connection."""
    print("Connected to MQTT broker!")
    mqtt_client.subscribe(MQTT_TOPIC_SET)
    # Publish initial state
    publish_state()

def mqtt_message(mqtt_client, topic, message):
    """Handle incoming MQTT messages."""
    print(f"MQTT << {topic}: {message}")
    if topic == MQTT_TOPIC_SET:
        try:
            state = json.loads(message)
            if "on" in state:
                if state["on"]:
                    tree.on()
                else:
                    tree.off()
            if "brightness" in state:
                tree.set_brightness(state["brightness"] / 100)  # Convert from 0-100 to 0-1
            if "color" in state:
                # Expect hex color string
                color = state["color"]
                r = int(color[0:2], 16)
                g = int(color[2:4], 16)
                b = int(color[4:6], 16)
                tree.set_color((r, g, b))
            if "effect" in state:
                tree.set_animation(state["effect"])
            # Publish updated state
            publish_state()
        except Exception as e:
            print(f"Error handling MQTT message: {e}")

def publish_state():
    """Publish the current state to MQTT."""
    try:
        state = tree.state()
        message = json.dumps(state)
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
    tree.on()
    return Response(request, "Tree on")

@server.route("/off")
def off(request: Request):
    """
    Turn the tree off.
    """
    tree.off()
    return Response(request, "Tree off")

@server.route("/color/<color>")
def color(request: Request, color: str):
    """
    Set the tree color.
    """
    tree.set_color(hex_to_rgb(color))
    return Response(request, f"Tree color set to {color}")

@server.route("/brightness/<brightness>")
def brightness(request: Request, brightness: str):
    """
    Set the tree brightness.
    """
    tree.set_brightness(int(brightness) / 100)
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

    tree.set_animation(effect, params)
    return Response(request, "Tree effect set")

@server.route("/pause")
def pause(request: Request):
    """
    Pause the tree effect.
    """
    tree.pause()
    return Response(request, "Tree effect paused")

@server.route("/resume")
def resume(request: Request):
    """
    Resume the tree effect.
    """
    tree.resume()
    return Response(request, "Tree effect resumed")

@server.route("/speed/<speed>")
def speed(request: Request, speed: str):
    """
    Set the animation speed.
    """
    tree.set_speed(float(speed) / 100)
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
    Accepts JSON body with any of: on, brightness, color, effect, effect_params
    Returns the new state.
    """
    try:
        params = json.loads(request.body.decode())

        if "on" in params:
            if params["on"]:
                tree.on()
            else:
                tree.off()

        if "effect" in params:
            effect = params["effect"]
            effect_params = params.get("effect_params", {})
            tree.set_animation(effect, effect_params)
        elif "color" in params:
            # Expect color as hex string without #
            tree.set_color(hex_to_rgb(params["color"]))

        if "brightness" in params:
            # Expect brightness as 0-100
            tree.set_brightness(int(params["brightness"]) / 100)

        if "speed" in params:
            # Expect speed as 0-100
            tree.set_speed(float(params["speed"]) / 100)

        return Response(request, json.dumps(tree.state()), content_type="application/json")
    except json.JSONDecodeError:
        return Response(request, "Invalid JSON", status=400)
    except Exception as e:
        return Response(request, f"Error: {str(e)}", status=400)

def hex_to_rgb(hex):
    return tuple(int(hex[i:i+2], 16) for i in (0, 2, 4))

async def handle_requests():
    while True:
        server.poll()
        await asyncio.sleep(0)

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
        await asyncio.sleep(0.05)

async def handle_mqtt():
    """Handle MQTT message loop."""
    while True:
        try:
            mqtt_client.loop()
        except Exception as e:
            print(f"MQTT error: {e}")
            # Try to reconnect
            try:
                mqtt_client.reconnect()
            except Exception as e:
                print(f"MQTT reconnection failed: {e}")
        await asyncio.sleep(0.1)  # Small delay to prevent tight loop

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
    print("Starting tasks")
    await asyncio.gather(server_task, animation_task, encoder_task, mqtt_task)
    print("Tasks started")

if __name__ == "__main__":
    asyncio.run(main())