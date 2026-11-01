import asyncio
import json
import pathlib
import socket
import sys
import threading
import time
import webbrowser
from aiohttp import web

from collector import Collector

APP_NAME = "NetPulse"
VERSION = "2.2.0"
PREFERRED_PORT = 8080


def resource_dir():
    # Khi đóng gói bằng PyInstaller, file tĩnh nằm trong sys._MEIPASS
    return pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent))


STATIC = resource_dir() / "static"


async def index(request):
    return web.FileResponse(STATIC / "index.html")


async def static_files(request):
    path = (STATIC / request.match_info["name"]).resolve()
    if path.parent != STATIC.resolve() or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)


def now_str():
    return time.strftime("%H:%M:%S")


async def websocket_handler(request):
    collector: Collector = request.app["collector"]
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    state = {"paused": False}
    await ws.send_json({"type": "hello", "info": collector.info, "version": VERSION})
    await ws.send_json({"type": "status", "message": "Agent connected", "time": now_str()})

    async def stream():
        last = None
        hw_sent = False
        while not ws.closed:
            if not hw_sent and collector.hardware is not None:
                await ws.send_json({"type": "hardware", "components": collector.hardware})
                hw_sent = True
            data = collector.latest
            if data is not None and data is not last and not state["paused"]:
                await ws.send_json(data)
                last = data
            await asyncio.sleep(0.25)

    task = asyncio.create_task(stream())
    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                command = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            action = command.get("action")
            if action == "pause":
                state["paused"] = bool(command.get("value"))
                await ws.send_json({"type": "status", "time": now_str(),
                                    "message": "Stream paused" if state["paused"] else "Stream resumed"})
            elif action == "ping":
                await ws.send_json({"type": "pong", "time": now_str()})
            elif action == "refresh":
                gw = await asyncio.get_running_loop().run_in_executor(None, collector.refresh_targets)
                await ws.send_json({"type": "status", "time": now_str(),
                                    "message": f"Endpoints refreshed (gateway: {gw or 'not found'})"})
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return ws


async def health(request):
    return web.json_response({"app": APP_NAME, "version": VERSION, "status": "ok"})


async def collect_loop(app):
    collector: Collector = app["collector"]
    loop = asyncio.get_running_loop()

    async def run():
        loop.run_in_executor(None, collector.load_hardware)
        await loop.run_in_executor(None, collector.refresh_targets)
        while True:
            t0 = time.perf_counter()
            try:
                await collector.sample()
            except Exception as exc:  # không để agent chết vì một lần đo lỗi
                print("collector error:", exc)
            await asyncio.sleep(max(0.0, 1.0 - (time.perf_counter() - t0)))

    app["collect_task"] = asyncio.create_task(run())
    yield
    app["collect_task"].cancel()


def create_app():
    app = web.Application()
    app["collector"] = Collector()
    app.cleanup_ctx.append(collect_loop)
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/health", health)
    app.router.add_get("/static/{name}", static_files)
    return app


def pick_port(start):
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


if __name__ == "__main__":
    port = pick_port(PREFERRED_PORT)
    url = f"http://127.0.0.1:{port}"
    print(f"\n{APP_NAME} v{VERSION} - Real-time system & network monitor")
    print(f"Dashboard: {url}")
    print("Đóng cửa sổ này hoặc nhấn Ctrl+C để dừng.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    # Chỉ lắng nghe localhost: số liệu máy không bị lộ ra mạng LAN
    web.run_app(create_app(), host="127.0.0.1", port=port, print=None)
