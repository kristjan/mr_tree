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

from tree import Tree
from effects.rainbow_cycle import RainbowCycle
from effects.sweep import Sweep

print("Creating tree...")
tree = Tree()
print("Tree created!")
tree.on()

print("Connecting to WiFi...")
wifi.radio.connect(os.getenv("WIFI_SSID"), os.getenv("WIFI_PASSWORD"))
print("Connected!", str(wifi.radio.ipv4_address))

print("Starting mDNS...")
mdns_name = os.getenv("MDNS_NAME")
mdns_server = mdns.Server(wifi.radio)
mdns_server.hostname = mdns_name
mdns_server.advertise_service(service_type="_http", protocol="_tcp", port=os.getenv("SERVER_PORT"))
print(f"mDNS started at {mdns_name}.local")

pool = socketpool.SocketPool(wifi.radio)
server = Server(pool, "/static", debug=True)

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

@server.route("/effect/<effect>")
def effect(request: Request, effect: str):
    """
    Set the tree effect.
    """
    tree.set_animation(effect)
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
def state(request: Request):
    """
    Get the tree state.
    """
    return Response(request, json.dumps(tree.state()), content_type="application/json")

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

async def main():
    print("Starting server")
    server.start(str(wifi.radio.ipv4_address), 7433)
    print("Creating server task")
    server_task = asyncio.create_task(handle_requests())
    print("Creating animation task")
    animation_task = asyncio.create_task(tree.animate())
    print("Creating encoder task")
    encoder_task = asyncio.create_task(handle_encoders())
    print("Starting tasks")
    await asyncio.gather(server_task, animation_task, encoder_task)
    print("Tasks started")

if __name__ == "__main__":
    asyncio.run(main())