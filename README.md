# NetPulse — Real-time Network & Hardware Monitor

NetPulse is a lightweight monitor that runs on your own computer and shows live network and hardware metrics in a web dashboard. It was built by **Group 15** for the *Network Developing* class.

> Feedback is welcome: **netpulsegroup15@gmail.com**

## Features
- **Traffic throughput**: live inbound / outbound bandwidth (Mbps), 30-second chart.
- **Bandwidth by service / application**: ranking from highest to lowest (HTTPS, QUIC, DNS, SSH… or chrome.exe, Spotify.exe…). Needs packet capture, see [below](#bandwidth-by-service--application).
- **Latency & packet loss**: TCP round-trip time to your default gateway, `1.1.1.1` and `8.8.8.8`.
- **System health**: CPU, RAM, disk usage, GPU usage (NVIDIA via `nvidia-smi`; AMD/Intel via Windows counters).
- **Hardware inventory**: CPU, GPU, RAM modules, disks, network adapter.
- **Live event log** and WebSocket ping / pause controls.

No fake data is generated: if a metric cannot be collected, the dashboard says so.

## Download and run (Windows, no Python needed)
1. Download `NetPulse.exe` from the [Releases](../../releases) page.
2. Run it. Your browser opens `http://127.0.0.1:8080` automatically. Close the console window to stop.
3. For the *Services / Applications* table, first install [Npcap](https://npcap.com), then right-click `NetPulse.exe` → **Run as administrator**.

Windows SmartScreen may warn because the exe is not code-signed: click **More info → Run anyway**.

## Run from source
Requires Python 3.10+.
```powershell
py -m pip install -r requirements.txt
py app.py                 # add --no-browser to skip opening the browser
```
If port 8080 is busy, NetPulse picks the next free port (up to 8099) and prints the address.

## Bandwidth by service / application
The *Traffic throughput* panel has two tabs, sorted by bandwidth (5-second rolling average):

- **Services**: classified by port (443 → HTTPS, 53 → DNS, 22 → SSH, …).
- **Applications**: classified by process name (local port → PID via `psutil`).

This uses [`scapy`](https://scapy.net) packet capture, so it needs **Npcap** (Windows) and **administrator / root** rights. Without them the panel shows the reason instead of numbers, and everything else keeps working. Very short-lived connections appear as "Other / unattributed". At very high traffic rates, Python packet parsing can use a lot of CPU.

## How it works
```text
Browser (static/app.js)  <== WebSocket /ws, JSON every second ==>  app.py (aiohttp)
                                                                     │
                                                          collector.py  (every 1 s)
                                                           ├─ psutil        network, CPU, RAM, disk
                                                           ├─ TCP probes    latency, packet loss
                                                           ├─ hardware.py   PowerShell / registry / nvidia-smi
                                                           └─ traffic.py    scapy → per-service / per-app bandwidth
```
| Message | Direction | Purpose |
|---|---|---|
| `hello`, `hardware`, `metrics`, `status`, `pong` | server → browser | system info, inventory, per-second metrics, events |
| `pause`, `ping`, `refresh` | browser → server | UI controls |

The dashboard listens on `127.0.0.1` only, so it is not exposed to your LAN, and nothing is sent to any external server. The only outgoing traffic is the latency probes to `1.1.1.1` and `8.8.8.8`.

## Project structure
```text
app.py             aiohttp server, WebSocket endpoint, launcher
collector.py       per-second metrics collector (the "agent")
hardware.py        hardware inventory and GPU monitor
traffic.py         packet capture and per-service / per-app bandwidth
static/            dashboard (index.html, app.js, style.css)
build.bat          builds dist\NetPulse.exe locally
.github/workflows  builds NetPulse.exe on GitHub Actions
```

## Build the exe yourself
- **Locally (Windows)**: double-click `build.bat` → `dist\NetPulse.exe`.
- **GitHub**: Actions → *Build NetPulse.exe* → Run workflow. Pushing a tag such as `v2.2.0` also attaches the exe to a GitHub Release.

## Limitations
- Windows-first. Hardware inventory relies on PowerShell; on Linux/macOS some items may be missing.
- Latency uses TCP connect time, not ICMP ping.
- GPU details (temperature, power, clocks) are only available for NVIDIA GPUs.
- Monitors the local machine only; there is no remote agent or multi-device view yet.
- Educational project, not a hardened enterprise tool.
