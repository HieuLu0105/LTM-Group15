import asyncio
import json
import pathlib
import socket
import sys
import threading
import time
import webbrowser
import os
import aiohttp
import observability as obs
from alerts.engine import AlertEngine, DEFAULTS, LABELS
from alerts.telegram import send as telegram_send
from sensors import SensorMonitor, max_temperature
from aiohttp import web

from collector import Collector

APP_NAME = "NetPulse"
VERSION = "2.2.0"
PREFERRED_PORT = 8080


def resource_dir():
    # Khi đóng gói bằng PyInstaller, file tĩnh nằm trong sys._MEIPASS
    return pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent))


STATIC = resource_dir() / "static"


# User-writable settings, separate from packaged resources.
CONFIG_PATH = pathlib.Path.home() / ".netpulse" / "alert_config.json"

def load_rules():
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {k: {**v, **saved.get(k, {})} for k, v in DEFAULTS.items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return {k: dict(v) for k, v in DEFAULTS.items()}


def extract_alert_values(data, sensors):
    gpus = data.get('gpus') or []
    gpu_temps = [g['temp'] for g in gpus if isinstance(g.get('temp'), (int, float))]
    gpu_usage = [g['usage'] for g in gpus if isinstance(g.get('usage'), (int, float))]
    return {'cpu': data.get('cpu'), 'memory': data.get('memory'), 'disk': data.get('disk'),
            'cpu_temp': max_temperature(sensors, 'cpu'),
            'gpu_temp': max(gpu_temps + ([max_temperature(sensors, 'gpu')] if max_temperature(sensors, 'gpu') is not None else []), default=None),
            'gpu_usage': max(gpu_usage, default=None)}


async def get_alerts(request):
    return web.json_response({'rules': request.app['rules'],
                              'telegram_configured': bool(os.environ.get('TELEGRAM_BOT_TOKEN') and os.environ.get('TELEGRAM_CHAT_ID'))})


async def save_alerts(request):
    try:
        incoming = await request.json()
        if not isinstance(incoming, dict) or set(incoming) != set(DEFAULTS):
            raise ValueError('Expected all six alert rules')
        clean = {}
        for key, rule in incoming.items():
            if not isinstance(rule, dict) or type(rule.get('enabled')) is not bool or rule.get('mode') not in ('instant', 'sustained'):
                raise ValueError(f'Invalid rule: {key}')
            threshold = float(rule['threshold'])
            duration = int(rule['duration'])
            cooldown = int(rule['cooldown'])
            if not (0 <= threshold <= (150 if 'temp' in key else 100) and 0 <= duration <= 3600 and 0 <= cooldown <= 86400):
                raise ValueError(f'Invalid range: {key}')
            clean[key] = {'enabled': rule['enabled'], 'threshold': threshold,
                          'duration': duration, 'cooldown': cooldown, 'mode': rule['mode']}
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = CONFIG_PATH.with_suffix('.tmp')
        temp.write_text(json.dumps(clean, indent=2), encoding='utf-8')
        temp.replace(CONFIG_PATH)
        request.app['rules'] = clean
        request.app['alert_engine'].states.clear()
        return web.json_response({'ok': True})
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise web.HTTPBadRequest(text=str(exc))


async def test_telegram(request):
    ok, message = await notify(request.app, 'NetPulse test notification: Telegram is connected.')
    return web.json_response({'ok': ok, 'message': message}, status=200 if ok else 400)


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


async def refresh_sensors(app):
    if app['sensor_busy']:
        return
    app['sensor_busy'] = True
    try:
        app['sensor_data'] = await asyncio.to_thread(app['sensor_monitor'].snapshot)
    finally:
        app['sensor_busy'] = False


async def notify(app, message, parent=None):
    for attempt in range(1,4):
        ok, reason = await telegram_send(app['telegram_session'], message)
        # Never persist exception URLs, which may contain bot tokens.
        app['store'].event('INFO' if ok else 'ERROR','Telegram',f'Attempt {attempt}: '+('Sent' if ok else 'Delivery failed'),parent)
        if ok or 'Missing TELEGRAM' in reason: break
        if attempt<3: await asyncio.sleep(2**attempt)
    return ok, 'Sent' if ok else 'Delivery failed; check configuration/network'


async def telegram_context(app):
    async with aiohttp.ClientSession() as session:
        app['telegram_session'] = session
        yield


async def get_hardware_detail(request):
    collector = request.app['collector']
    return web.json_response({'info': collector.info, 'components': collector.hardware or [],
                              'metrics': request.app['hardware_metrics'], 'sensors': request.app['sensor_data'],
                              'live': collector.latest or {}})


async def collect_loop(app):
    collector: Collector = app["collector"]
    loop = asyncio.get_running_loop()

    async def run():
        loop.run_in_executor(None, collector.load_hardware)
        await loop.run_in_executor(None, collector.refresh_targets)
        previous=None
        while True:
            t0 = time.perf_counter()
            try:
                data = await collector.sample()
                now=time.monotonic()
                current=(collector.rx_total,collector.tx_total,now,bool(data.get('online')))
                if previous:
                    app['store'].sample(max(0,current[0]-previous[0]),max(0,current[1]-previous[1]),current[3],min(10,now-previous[2]))
                    if current[3]!=previous[3]: app['store'].event('RECOVERY' if current[3] else 'WARNING','Network','Public TCP probes restored' if current[3] else 'Public TCP probes failed')
                previous=current
                app['series'].append({'time':data['time'],'rx':data['rx'],'tx':data['tx']})
                # Sensor probing can involve PowerShell; never block WebSocket/network sampling.
                if time.monotonic() - app['sensor_last_check'] >= 5:
                    app['sensor_last_check'] = time.monotonic()
                    asyncio.create_task(refresh_sensors(app))
                values = extract_alert_values(data, app['sensor_data'])
                app['hardware_metrics'] = values
                for event in app['alert_engine'].evaluate(values, app['rules']):
                    unit = '°C' if 'temp' in event['key'] else '%'
                    kind = 'ALERT' if event['kind'] == 'alert' else 'RECOVERY'
                    msg = (f"NetPulse {kind}\nHost: {collector.info['hostname']}\n"
                           f"{LABELS[event['key']]}: {event['value']:.1f}{unit}\n"
                           f"Threshold: {event['threshold']:.1f}{unit}\nTime: {time.strftime('%Y-%m-%d %H:%M:%S')}")
                    parent=app['store'].event('WARNING' if kind=='ALERT' else 'RECOVERY','Hardware',msg)
                    asyncio.create_task(notify(app, msg,parent))
            except Exception as exc:  # không để agent chết vì một lần đo lỗi
                print("collector error:", exc)
                app['store'].event('ERROR','Collector',type(exc).__name__)
            await asyncio.sleep(max(0.0, 1.0 - (time.perf_counter() - t0)))

    app["collect_task"] = asyncio.create_task(run())
    yield
    app["collect_task"].cancel()
    await asyncio.gather(app["collect_task"],return_exceptions=True)
    collector.traffic.stop()


def create_app():
    app = web.Application()
    app["collector"] = Collector()
    app['rules'] = load_rules()
    app['alert_engine'] = AlertEngine()
    app['sensor_monitor'] = SensorMonitor()
    app['sensor_data'] = []
    app['sensor_busy'] = False
    app['sensor_last_check'] = 0
    app['hardware_metrics'] = {}
    app['store']=obs.Store(pathlib.Path.home()/'.netpulse'/'telemetry.sqlite3')
    app.cleanup_ctx.append(obs.context)
    app.cleanup_ctx.append(telegram_context)
    app.cleanup_ctx.append(collect_loop)
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/health", health)
    app.router.add_get("/api/traffic",obs.traffic)
    app.router.add_get("/api/events",obs.events)
    app.router.add_post(r"/api/events/{id:\d+}/ack",obs.ack)
    app.router.add_post("/api/diagnostics/{kind}",obs.diagnostics)
    app.router.add_get("/api/hardware", get_hardware_detail)
    app.router.add_get("/api/alerts", get_alerts)
    app.router.add_post("/api/alerts", save_alerts)
    app.router.add_post("/api/telegram/test", test_telegram)
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
