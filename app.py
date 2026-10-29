import asyncio
import json
import math
import pathlib
import random
import time
from datetime import datetime
from aiohttp import web

ROOT = pathlib.Path(__file__).parent

async def index(request):
    return web.FileResponse(ROOT / "static" / "index.html")

async def static_files(request):
    name = request.match_info["name"]
    path = (ROOT / "static" / name).resolve()
    if path.parent != (ROOT / "static").resolve() or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)

async def websocket_handler(request):
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    started = time.time()
    rx_base = random.uniform(80, 180)
    tx_base = random.uniform(15, 55)
    state = {"paused": False}
    await ws.send_json({"type": "status", "message": "WebSocket connected", "time": datetime.now().strftime("%H:%M:%S")})

    async def stream_metrics():
        while not ws.closed:
            if not state["paused"]:
                now = time.time()
                rx = max(8, rx_base + random.uniform(-35, 55) + 22 * abs(math.sin(now / 5)))
                tx = max(2, tx_base + random.uniform(-12, 18) + 8 * abs(math.cos(now / 4)))
                cpu = min(96, max(8, 38 + 18 * math.sin(now / 7) + random.uniform(-8, 8)))
                memory = min(92, max(25, 58 + 8 * math.sin(now / 11) + random.uniform(-3, 3)))
                latency = max(8, random.gauss(34, 8))
                packet_loss = 0 if random.random() > 0.08 else round(random.uniform(0.1, 1.2), 2)
                await ws.send_json({
                    "type": "metrics", "time": datetime.now().strftime("%H:%M:%S"),
                    "uptime": int(now - started), "rx": round(rx, 1), "tx": round(tx, 1),
                    "cpu": round(cpu, 1), "memory": round(memory, 1),
                    "latency": round(latency, 1), "loss": packet_loss,
                    "total_rx": round((now - started) * rx / 8, 2),
                    "total_tx": round((now - started) * tx / 8, 2),
                })
            await asyncio.sleep(1)

    task = asyncio.create_task(stream_metrics())
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    command = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if command.get("action") == "pause":
                    state["paused"] = bool(command.get("value"))
                    await ws.send_json({"type": "status", "message": "Stream paused" if state["paused"] else "Stream resumed", "time": datetime.now().strftime("%H:%M:%S")})
                elif command.get("action") == "ping":
                    await ws.send_json({"type": "pong", "time": datetime.now().strftime("%H:%M:%S")})
            elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                break
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return ws

async def health(request):
    return web.json_response({"app": "NetPulse", "status": "ok"})

def create_app():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/health", health)
    app.router.add_get("/static/{name}", static_files)
    return app

if __name__ == "__main__":
    print("\\nNetPulse Network Monitor")
    print("Open http://127.0.0.1:8080 in your browser. Press Ctrl+C to stop.\\n")
    web.run_app(create_app(), host="0.0.0.0", port=8080)
