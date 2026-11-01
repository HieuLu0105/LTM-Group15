"""Thu thập thông số thật của máy (CPU, RAM, ổ đĩa, mạng, độ trễ, mất gói)."""
import asyncio
import os
import platform
import socket
import subprocess
import sys
import time
from collections import deque

import psutil

from hardware import GpuMonitor, cpu_name, gather_inventory
from traffic import TrafficMonitor

# Các điểm đo độ trễ cố định (internet). Gateway được tự phát hiện thêm.
PUBLIC_TARGETS = [
    ("Cloudflare DNS", "1.1.1.1", 443),
    ("Google DNS", "8.8.8.8", 53),
]
PROBE_TIMEOUT = 1.0
LOSS_WINDOW = 30  # số lần đo gần nhất dùng để tính packet loss


def _no_window():
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}


def default_gateway():
    """Tìm default gateway (best-effort, không cần quyền admin)."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/net/route") as f:
                for line in list(f)[1:]:
                    p = line.split()
                    if p[1] == "00000000":
                        h = int(p[2], 16)
                        return socket.inet_ntoa(h.to_bytes(4, "little"))
        elif sys.platform == "win32":
            out = subprocess.run(["route", "print", "-4", "0.0.0.0"], capture_output=True,
                                 text=True, timeout=5, **_no_window()).stdout
            best = None
            for line in out.splitlines():
                p = line.split()
                if len(p) >= 5 and p[0] == "0.0.0.0" and p[1] == "0.0.0.0":
                    metric = int(p[4]) if p[4].isdigit() else 9999
                    if best is None or metric < best[0]:
                        best = (metric, p[2])
            return best[1] if best else None
        elif sys.platform == "darwin":
            out = subprocess.run(["route", "-n", "get", "default"], capture_output=True,
                                 text=True, timeout=5).stdout
            for line in out.splitlines():
                if "gateway:" in line:
                    return line.split(":")[1].strip()
    except Exception:
        pass
    return None


async def tcp_probe(host, port, timeout=PROBE_TIMEOUT):
    """Đo RTT bằng TCP connect (không cần quyền raw socket như ICMP).
    Kết nối bị từ chối vẫn tính là host phản hồi. Trả về ms hoặc None nếu timeout."""
    t0 = time.perf_counter()
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        ms = (time.perf_counter() - t0) * 1000
        w.close()
        return ms
    except ConnectionRefusedError:
        return (time.perf_counter() - t0) * 1000
    except (asyncio.TimeoutError, OSError):
        return None


class Collector:
    def __init__(self):
        self.started = time.time()
        self.latest = None
        self.info = self._system_info()
        self.targets = []
        self.history = {}  # host -> deque[bool]
        self._last_net = None
        self._last_t = None
        self.rx_total = 0
        self.tx_total = 0
        psutil.cpu_percent(None)
        self._disk_root = os.path.abspath(os.sep)
        self.hardware = None  # điền bởi load_hardware()
        self.gpu = GpuMonitor()
        self.gpu.start()
        self._last_io = None
        self._disk_map = {}
        self.traffic = TrafficMonitor()  # băng thông theo dịch vụ / ứng dụng
        self.traffic.start()

    def load_hardware(self):
        """Chạy 1 lần trong thread nền (PowerShell có thể mất vài giây)."""
        inv = gather_inventory()
        self._disk_map = inv["disks"]
        self.gpu.names = [c["name"] for c in inv["components"] if c["type"] == "GPU"]
        self.hardware = inv["components"]

    @staticmethod
    def _cpu_freq():
        try:
            f = psutil.cpu_freq()
            return round(f.current) if f and f.current else None
        except Exception:
            return None

    def _volumes(self):
        vols, seen = [], set()
        for p in psutil.disk_partitions(all=False):
            opts = (p.opts or "").lower()
            if "cdrom" in opts or not p.fstype:
                continue
            if p.fstype in ("squashfs", "overlay", "tmpfs", "devtmpfs", "vfat") and not sys.platform == "win32" and p.mountpoint != "/":
                continue
            if p.mountpoint.startswith(("/snap", "/boot", "/run", "/sys", "/proc", "/dev")) or p.device in seen:
                continue
            seen.add(p.device)
            try:
                u = psutil.disk_usage(p.mountpoint)
            except Exception:
                continue
            label = p.mountpoint.rstrip("\\") if sys.platform == "win32" else p.mountpoint
            info = self._disk_map.get(label[:1].upper()) if sys.platform == "win32" else None
            if info is None:
                base = os.path.basename(p.device).rstrip("0123456789")
                info = self._disk_map.get("/dev/" + base) or self._disk_map.get(p.device)
            vols.append({"mount": label, "fstype": p.fstype,
                         "model": info["model"] if info else None, "kind": info["kind"] if info else None,
                         "percent": round(u.percent, 1), "used_gb": round(u.used / 1024 ** 3, 1),
                         "total_gb": round(u.total / 1024 ** 3, 1), "free_gb": round(u.free / 1024 ** 3, 1)})
        return vols

    def _system_info(self):
        vm = psutil.virtual_memory()
        return {
            "hostname": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()}",
            "cpu": cpu_name(),
            "cores": psutil.cpu_count(logical=True),
            "ram_gb": round(vm.total / 1024 ** 3, 1),
        }

    def refresh_targets(self):
        gw = default_gateway()
        t = []
        if gw:
            t.append(("Default gateway", gw, 80))
        t += PUBLIC_TARGETS
        self.targets = t
        for _, host, _ in t:
            self.history.setdefault(host, deque(maxlen=LOSS_WINDOW))
        return gw

    async def sample(self):
        now = time.time()
        net = psutil.net_io_counters()
        dt_net = 1.0
        if self._last_net is not None:
            dt = max(0.001, now - self._last_t)
            dt_net = dt
            rx_b = max(0, net.bytes_recv - self._last_net.bytes_recv)
            tx_b = max(0, net.bytes_sent - self._last_net.bytes_sent)
            rx = rx_b * 8 / dt / 1e6
            tx = tx_b * 8 / dt / 1e6
            self.rx_total += rx_b
            self.tx_total += tx_b
        else:
            rx = tx = 0.0
        self._last_net, self._last_t = net, now

        results = await asyncio.gather(*(tcp_probe(h, p) for _, h, p in self.targets))
        endpoints = []
        for (name, host, _), ms in zip(self.targets, results):
            self.history[host].append(ms is not None)
            endpoints.append({"name": name, "host": host, "online": ms is not None,
                              "latency": None if ms is None else round(ms, 1)})
        try:
            io = psutil.disk_io_counters()
        except Exception:
            io = None
        d_read = d_write = 0.0
        if io and self._last_io:
            dt = max(0.001, now - self._last_io[0])
            d_read = max(0, io.read_bytes - self._last_io[1].read_bytes) / dt / 1e6
            d_write = max(0, io.write_bytes - self._last_io[1].write_bytes) / dt / 1e6
        if io:
            self._last_io = (now, io)
        pub = [e for e in endpoints if e["name"] != "Default gateway"] or endpoints
        lat_vals = [e["latency"] for e in pub if e["latency"] is not None]
        latency = round(sum(lat_vals) / len(lat_vals), 1) if lat_vals else 0.0
        samples = [ok for e in pub for ok in self.history[e["host"]]]
        loss = round(100 * samples.count(False) / len(samples), 2) if samples else 0.0

        disk = psutil.disk_usage(self._disk_root)
        vm = psutil.virtual_memory()
        self.latest = {
            "type": "metrics", "time": time.strftime("%H:%M:%S"),
            "uptime": int(now - self.started),
            "rx": round(rx, 2), "tx": round(tx, 2),
            "cpu": round(psutil.cpu_percent(None), 1),
            "cpu_freq": self._cpu_freq(),
            "memory": round(vm.percent, 1),
            "memory_used_gb": round(vm.used / 1024 ** 3, 1),
            "disk": round(disk.percent, 1),
            "disk_free_gb": round(disk.free / 1024 ** 3, 1),
            "latency": latency, "loss": loss,
            "total_rx": round(self.rx_total / 1e6, 2),
            "total_tx": round(self.tx_total / 1e6, 2),
            "disk_read": round(d_read, 2), "disk_write": round(d_write, 2),
            "volumes": self._volumes(), "gpus": self.gpu.gpus,
            "online": bool(lat_vals),
            "endpoints": endpoints,
            "breakdown": self.traffic.snapshot(dt_net),
        }
        return self.latest
