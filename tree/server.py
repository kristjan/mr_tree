import os
import socketpool
import wifi

from adafruit_httpserver.server import Server, Request, Response


print("Connecting to WiFi...")
wifi.radio.connect(os.getenv("WIFI_SSID"), os.getenv("WIFI_PASSWORD"))
print("Connected!", str(wifi.radio.ipv4_address))
pool = socketpool.SocketPool(wifi.radio)
server = Server(pool, "/static", debug=True)


@server.route("/")
def base(request: Request):
    """
    Serve a default static plain text message.
    """
    return Response(request, "Hello from the CircuitPython HTTP Server!")



async def serve():
    print(f"Listening on http://{wifi.radio.ipv4_address}:7433")
    await server.serve_forever(str(wifi.radio.ipv4_address), port=7433)