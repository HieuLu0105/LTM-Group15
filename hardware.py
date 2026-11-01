"""Tên linh kiện phần cứng + giám sát GPU (best-effort, không cần quyền admin)."""
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time

IS_WIN = sys.platform == "win32"
_NOWIN = {"creationflags": 0x08000000} if IS_WIN else {}


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, **_NOWIN)
        return r.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def _ps(script, timeout=25):
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script], timeout)


def _list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _gb(b):
    try:
        return round(float(b) / 1024 ** 3, 1)
    except Exception:
        return None


def cpu_name():
    try:
        if IS_WIN:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        if sys.platform.startswith("linux"):
            for line in open("/proc/cpuinfo"):
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
        if sys.platform == "darwin":
            return _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
    except Exception:
        pass
    return platform.processor() or platform.machine()


def _dmi(name):
    try:
        return open(f"/sys/class/dmi/id/{name}").read().strip()
    except Exception:
        return ""


def gather_inventory():
    """Trả về {"components": [{type,name,detail}], "disks": {key: {...}}}.
    Chạy chậm (~1-3s trên Windows) nên gọi trong thread nền."""
    comps = []
    disks = {}  # "C" (Windows) hoặc tên thiết bị -> {model, kind, size_gb}

    def add(t, name, detail=""):
        if name:
            comps.append({"type": t, "name": str(name).strip(), "detail": detail})

    if IS_WIN:
        script = r"""
$e='SilentlyContinue'
$o=[ordered]@{
 cpu=@(Get-CimInstance Win32_Processor -EA $e|select Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed)
 gpu=@(Get-CimInstance Win32_VideoController -EA $e|select Name,AdapterRAM,DriverVersion)
 board=@(Get-CimInstance Win32_BaseBoard -EA $e|select Manufacturer,Product)
 system=@(Get-CimInstance Win32_ComputerSystem -EA $e|select Manufacturer,Model)
 ram=@(Get-CimInstance Win32_PhysicalMemory -EA $e|select Manufacturer,PartNumber,Capacity,Speed)
 disk=@(Get-PhysicalDisk -EA $e|select DeviceId,FriendlyName,MediaType,BusType,Size)
 part=@(Get-Partition -EA $e|?{$_.DriveLetter}|select DriveLetter,DiskNumber)
 nic=@(Get-NetAdapter -Physical -EA $e|?{$_.Status -eq 'Up'}|select Name,InterfaceDescription,LinkSpeed)
}
$o|ConvertTo-Json -Depth 4 -Compress
"""
        try:
            d = json.loads(_ps(script) or "{}")
        except Exception:
            d = {}
        sysi = (_list(d.get("system")) or [{}])[0]
        add("System", f"{sysi.get('Manufacturer', '')} {sysi.get('Model', '')}".strip())
        brd = (_list(d.get("board")) or [{}])[0]
        add("Mainboard", f"{brd.get('Manufacturer', '')} {brd.get('Product', '')}".strip())
        for c in _list(d.get("cpu")):
            add("CPU", c.get("Name"), f"{c.get('NumberOfCores')} cores / {c.get('NumberOfLogicalProcessors')} threads"
                f" · {round((c.get('MaxClockSpeed') or 0) / 1000, 2)} GHz")
        for g in _list(d.get("gpu")):
            add("GPU", g.get("Name"), f"Driver {g.get('DriverVersion', '?')}")
        for m in _list(d.get("ram")):
            add("RAM", f"{(m.get('Manufacturer') or '').strip()} {(m.get('PartNumber') or '').strip()}".strip() or "Memory module",
                f"{_gb(m.get('Capacity'))} GB · {m.get('Speed')} MT/s")
        dm = {}
        for dk in _list(d.get("disk")):
            kind = dk.get("MediaType") if dk.get("MediaType") not in (None, "Unspecified", "") else dk.get("BusType")
            info = {"model": dk.get("FriendlyName"), "kind": kind, "size_gb": _gb(dk.get("Size"))}
            dm[str(dk.get("DeviceId"))] = info
            add("Disk", info["model"], f"{kind} · {info['size_gb']} GB")
        for p in _list(d.get("part")):
            info = dm.get(str(p.get("DiskNumber")))
            if info:
                disks[str(p.get("DriveLetter")).upper()] = info
        for n in _list(d.get("nic")):
            add("Network", n.get("InterfaceDescription") or n.get("Name"), f"{n.get('Name')} · {n.get('LinkSpeed')}")
    elif sys.platform.startswith("linux"):
        add("System", f"{_dmi('sys_vendor')} {_dmi('product_name')}".strip())
        add("Mainboard", f"{_dmi('board_vendor')} {_dmi('board_name')}".strip())
        add("CPU", cpu_name(), f"{os.cpu_count()} threads")
        if shutil.which("lspci"):
            for line in _run(["lspci"]).splitlines():
                if any(k in line for k in ("VGA", "3D controller", "Display controller")):
                    add("GPU", line.split(": ", 1)[-1])
        try:
            lb = json.loads(_run(["lsblk", "-J", "-d", "-o", "NAME,MODEL,SIZE,ROTA,TYPE"]) or "{}")
            for b in lb.get("blockdevices", []):
                if b.get("type") == "disk" and not b["name"].startswith(("loop", "ram", "zram")):
                    kind = "HDD" if str(b.get("rota")) in ("1", "True", "true") else "SSD"
                    info = {"model": b.get("model") or b["name"], "kind": kind, "size_gb": None}
                    disks["/dev/" + b["name"]] = info
                    add("Disk", info["model"], f"{kind} · {b.get('size')}")
        except Exception:
            pass
    elif sys.platform == "darwin":
        add("System", _run(["sysctl", "-n", "hw.model"]).strip())
        add("CPU", cpu_name())
    return {"components": comps, "disks": disks}


class GpuMonitor(threading.Thread):
    """Thread nền cập nhật số liệu GPU. NVIDIA: nvidia-smi (đầy đủ).
    Windows khác hãng (AMD/Intel): bộ đếm 'GPU Engine' của Windows (chỉ % sử dụng)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.gpus = []
        self.names = []  # tên GPU từ inventory (để gán cho GPU không phải NVIDIA)
        self.smi = shutil.which("nvidia-smi") or next(
            (p for p in (r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
                         r"C:\Windows\System32\nvidia-smi.exe") if os.path.exists(p)), None)

    @staticmethod
    def _num(s):
        try:
            return float(s)
        except Exception:
            return None

    def _nvidia(self):
        out = _run([self.smi, "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,"
                    "temperature.gpu,power.draw,clocks.gr,fan.speed",
                    "--format=csv,noheader,nounits"], 6)
        res = []
        for line in out.strip().splitlines():
            p = [x.strip() for x in line.split(",")]
            if len(p) < 9:
                continue
            mu, mt = self._num(p[3]), self._num(p[4])
            res.append({"name": p[1], "vendor": "NVIDIA", "usage": self._num(p[2]),
                        "mem_used_gb": None if mu is None else round(mu / 1024, 2),
                        "mem_total_gb": None if mt is None else round(mt / 1024, 1),
                        "temp": self._num(p[5]), "power": self._num(p[6]),
                        "clock": self._num(p[7]), "fan": self._num(p[8])})
        return res

    def _win_counters(self):
        script = (r"$s=(Get-Counter '\GPU Engine(*)\Utilization Percentage' -EA SilentlyContinue).CounterSamples;"
                  r"$g=@{};foreach($x in $s){if($x.InstanceName -match 'luid_(0x[0-9a-fA-F]+_0x[0-9a-fA-F]+)'){"
                  r"$k=$matches[1];$g[$k]+=$x.CookedValue}};$g|ConvertTo-Json -Compress")
        try:
            d = json.loads(_ps(script, 10) or "{}")
        except Exception:
            return []
        vals = [min(100.0, float(v)) for _, v in sorted(d.items())]
        return vals

    def run(self):
        while True:
            try:
                gpus = self._nvidia() if self.smi else []
                if IS_WIN:
                    nv_names = {g["name"] for g in gpus}
                    others = [n for n in self.names if n not in nv_names and not any(n in x or x in n for x in nv_names)]
                    if others:
                        counters = self._win_counters()
                        # best-effort: mỗi GPU không phải NVIDIA nhận 1 nhóm luid (luid nhỏ -> lớn)
                        counters = counters[: len(others)] if len(counters) >= len(others) else counters
                        for i, n in enumerate(others):
                            u = counters[i] if i < len(counters) else None
                            gpus.append({"name": n, "vendor": "Other", "usage": None if u is None else round(u, 1),
                                         "mem_used_gb": None, "mem_total_gb": None, "temp": None,
                                         "power": None, "clock": None, "fan": None})
                self.gpus = gpus
            except Exception:
                pass
            time.sleep(1.5)
