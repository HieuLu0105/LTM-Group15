"""Phân loại băng thông theo DỊCH VỤ (cổng) và theo ỨNG DỤNG (tiến trình).

Cách hoạt động
- Bắt gói tin bằng scapy (cần Npcap trên Windows + chạy với quyền Administrator/root).
- Mỗi gói được cộng dồn byte vào 2 bảng đếm:
    * dịch vụ: theo cổng phía xa (443 -> HTTPS, 53 -> DNS, ...)
    * ứng dụng: theo cổng cục bộ -> PID (psutil.net_connections) -> tên tiến trình
- snapshot() mỗi giây tính Mbps hiện tại và trung bình trượt, rồi sắp xếp giảm dần.

Không có quyền bắt gói thì báo "unavailable" kèm lý do, KHÔNG sinh số giả.
"""
import socket
import threading
import time
from collections import defaultdict, deque

import psutil

try:  # scapy là phụ thuộc tuỳ chọn: thiếu thì tính năng này tự tắt
    from scapy.all import AsyncSniffer, IP, IPv6, TCP, UDP
    _SCAPY_ERR = None
except Exception as exc:  # pragma: no cover - phụ thuộc môi trường
    AsyncSniffer = IP = IPv6 = TCP = UDP = None
    _SCAPY_ERR = exc

TOP_N = 8          # số dòng hiển thị mỗi bảng
WINDOW = 5         # số mẫu (giây) dùng để làm mượt thứ tự xếp hạng

# (giao thức, cổng) -> tên dịch vụ; cổng không khớp giao thức riêng sẽ thử bảng ANY
_SERVICES = {
    ("tcp", 80): "HTTP", ("tcp", 443): "HTTPS", ("udp", 443): "QUIC / HTTP3",
    ("tcp", 8080): "HTTP-Alt", ("tcp", 8443): "HTTPS-Alt",
    ("tcp", 53): "DNS", ("udp", 53): "DNS", ("tcp", 853): "DNS over TLS",
    ("udp", 5353): "mDNS", ("udp", 1900): "SSDP / UPnP", ("udp", 123): "NTP",
    ("udp", 67): "DHCP", ("udp", 68): "DHCP", ("udp", 137): "NetBIOS",
    ("udp", 138): "NetBIOS", ("tcp", 139): "NetBIOS", ("tcp", 445): "SMB",
    ("tcp", 22): "SSH", ("tcp", 23): "Telnet", ("tcp", 21): "FTP",
    ("tcp", 25): "SMTP", ("tcp", 465): "SMTP", ("tcp", 587): "SMTP",
    ("tcp", 110): "POP3", ("tcp", 995): "POP3", ("tcp", 143): "IMAP", ("tcp", 993): "IMAP",
    ("tcp", 3389): "RDP", ("udp", 3389): "RDP", ("tcp", 389): "LDAP", ("tcp", 636): "LDAP",
    ("tcp", 5222): "XMPP", ("tcp", 5228): "Google Push (FCM)", ("tcp", 1883): "MQTT",
    ("tcp", 8883): "MQTT", ("tcp", 3306): "MySQL", ("tcp", 5432): "PostgreSQL",
    ("tcp", 1433): "SQL Server", ("tcp", 6379): "Redis", ("tcp", 27017): "MongoDB",
    ("udp", 5060): "SIP", ("tcp", 5060): "SIP", ("udp", 3478): "STUN / WebRTC",
    ("udp", 1194): "OpenVPN", ("udp", 51820): "WireGuard",
}
OTHER_APP = "Other / unattributed"


def classify_service(proto, remote_port, local_port):
    """Tên dịch vụ của một gói: ưu tiên cổng phía xa, rồi tới cổng cục bộ."""
    for port in (remote_port, local_port):
        name = _SERVICES.get((proto, port))
        if name:
            return name
    if proto == "icmp":
        return "ICMP"
    return "Other " + proto.upper() if proto in ("tcp", "udp") else "Other"


class TrafficMonitor:
    def __init__(self):
        self._lock = threading.Lock()
        self._svc = defaultdict(lambda: [0, 0])   # tên -> [rx_bytes, tx_bytes] cộng dồn
        self._app = defaultdict(lambda: [0, 0])
        self._prev = {"svc": {}, "app": {}}
        self._hist = {"svc": deque(maxlen=WINDOW), "app": deque(maxlen=WINDOW)}
        self._local_ips = set()
        self._ips_t = 0.0
        self._port_pid = {}
        self._pid_name = {}
        self._sniffer = None
        self._reason = None
        self._stop = threading.Event()

    # ------------------------------------------------------------ vòng đời
    def start(self):
        if AsyncSniffer is None:
            self._reason = "Per-service capture needs scapy (pip install scapy). Details: %s" % _SCAPY_ERR
            return
        try:
            self._refresh_local_ips()
            self._refresh_ports()
            self._sniffer = AsyncSniffer(prn=self._on_packet, store=False)
            self._sniffer.start()
        except Exception as exc:
            self._sniffer = None
            self._reason = "Cannot start packet capture: %s" % exc
            return
        threading.Thread(target=self._map_loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        try:
            if self._sniffer is not None and self._sniffer.running:
                self._sniffer.stop()
        except Exception:
            pass

    def _capture_ok(self):
        s = self._sniffer
        if s is None:
            return False
        thread = getattr(s, "thread", None)
        if thread is not None and not thread.is_alive():
            exc = getattr(s, "exception", None)
            self._reason = ("Capture stopped: %s" % exc) if exc else \
                "Capture stopped. Run as Administrator and install Npcap (Windows) / run as root (Linux)."
            return False
        return True

    # ------------------------------------------------- ánh xạ cổng -> tiến trình
    def _refresh_local_ips(self):
        ips = {"127.0.0.1", "::1"}
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family in (socket.AF_INET, socket.AF_INET6):
                    ips.add(a.address.split("%")[0])
        self._local_ips, self._ips_t = ips, time.time()

    def _refresh_ports(self):
        m = {}
        try:
            for c in psutil.net_connections(kind="inet"):
                if c.pid and c.laddr:
                    proto = "tcp" if c.type == socket.SOCK_STREAM else "udp"
                    m[(proto, c.laddr.port)] = c.pid
        except Exception:
            return  # thiếu quyền: giữ bảng cũ
        self._port_pid = m

    def _name_of(self, pid):
        name = self._pid_name.get(pid)
        if name is None:
            try:
                name = psutil.Process(pid).name()
            except Exception:
                name = "PID %d" % pid
            self._pid_name[pid] = name
        return name

    def _map_loop(self):
        while not self._stop.wait(2.0):
            self._refresh_ports()
            if time.time() - self._ips_t > 15:
                self._refresh_local_ips()
            if len(self._pid_name) > 2000:
                self._pid_name.clear()

    # ------------------------------------------------------------- xử lý gói
    def _on_packet(self, pkt):
        try:
            if IP in pkt:
                l3 = pkt[IP]; proto_num = l3.proto
            elif IPv6 in pkt:
                l3 = pkt[IPv6]; proto_num = l3.nh
            else:
                return
            if TCP in pkt:
                proto, sp, dp = "tcp", pkt[TCP].sport, pkt[TCP].dport
            elif UDP in pkt:
                proto, sp, dp = "udp", pkt[UDP].sport, pkt[UDP].dport
            else:
                proto, sp, dp = ("icmp" if proto_num in (1, 58) else "other"), 0, 0
            self.add(l3.src, l3.dst, proto, sp, dp, len(pkt))
        except Exception:
            pass

    def add(self, src, dst, proto, sport, dport, size):
        """Ghi nhận một gói (tách riêng khỏi scapy để dễ kiểm thử)."""
        local = self._local_ips
        s_loc, d_loc = src in local, dst in local
        if s_loc == d_loc:      # loopback hoặc không liên quan tới máy này
            return
        if s_loc:
            idx, lport, rport = 1, sport, dport    # gửi đi (tx)
        else:
            idx, lport, rport = 0, dport, sport    # nhận về (rx)
        svc = classify_service(proto, rport, lport)
        pid = self._port_pid.get((proto, lport))
        app = self._name_of(pid) if pid else OTHER_APP
        with self._lock:
            self._svc[svc][idx] += size
            self._app[app][idx] += size

    # --------------------------------------------------------------- báo cáo
    def _rank(self, key, table, dt):
        prev = self._prev[key]
        cur = {k: tuple(v) for k, v in table.items()}
        deltas = {k: (v[0] - prev.get(k, (0, 0))[0], v[1] - prev.get(k, (0, 0))[1]) for k, v in cur.items()}
        self._prev[key] = cur
        hist = self._hist[key]
        hist.append((dt, deltas))
        span = sum(h[0] for h in hist) or 1.0
        rows = []
        for name, (rx_t, tx_t) in cur.items():
            w_rx = sum(h[1].get(name, (0, 0))[0] for h in hist)
            w_tx = sum(h[1].get(name, (0, 0))[1] for h in hist)
            avg = (w_rx + w_tx) * 8 / span / 1e6
            if avg <= 0:
                continue
            rx_now, tx_now = deltas[name]
            rows.append({"name": name,
                         "rx": round(rx_now * 8 / dt / 1e6, 3), "tx": round(tx_now * 8 / dt / 1e6, 3),
                         "avg": round(avg, 3), "total_mb": round((rx_t + tx_t) / 1e6, 2)})
        rows.sort(key=lambda r: r["avg"], reverse=True)   # ăn nhiều băng thông nhất lên đầu
        whole = sum(r["avg"] for r in rows) or 1.0
        for r in rows:
            r["share"] = round(100 * r["avg"] / whole, 1)
        return rows[:TOP_N]

    def snapshot(self, dt):
        if not self._capture_ok():
            return {"available": False, "reason": self._reason or "Packet capture is not running.",
                    "services": [], "apps": []}
        dt = max(0.001, dt)
        with self._lock:
            svc = {k: list(v) for k, v in self._svc.items()}
            app = {k: list(v) for k, v in self._app.items()}
        return {"available": True, "reason": None,
                "services": self._rank("svc", svc, dt), "apps": self._rank("app", app, dt)}
