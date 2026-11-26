"""Threshold alerts: duration, cooldown, hysteresis and recovery."""
import time

DEFAULTS = {
    "cpu": {"enabled": True, "threshold": 90, "duration": 10, "cooldown": 300, "mode": "sustained"},
    "memory": {"enabled": True, "threshold": 90, "duration": 10, "cooldown": 300, "mode": "sustained"},
    "disk": {"enabled": True, "threshold": 90, "duration": 0, "cooldown": 300, "mode": "instant"},
    "cpu_temp": {"enabled": True, "threshold": 85, "duration": 10, "cooldown": 300, "mode": "sustained"},
    "gpu_temp": {"enabled": True, "threshold": 85, "duration": 10, "cooldown": 300, "mode": "sustained"},
    "gpu_usage": {"enabled": False, "threshold": 95, "duration": 30, "cooldown": 300, "mode": "sustained"},
}
LABELS = {"cpu":"CPU usage", "memory":"RAM usage", "disk":"Disk usage", "cpu_temp":"CPU temperature", "gpu_temp":"GPU temperature", "gpu_usage":"GPU usage"}

class AlertEngine:
    def __init__(self):
        self.states = {}

    def evaluate(self, values, rules, now=None):
        now = time.monotonic() if now is None else now
        events = []
        for key, rule in rules.items():
            st = self.states.setdefault(key, {"since": None, "active": False, "last_sent": float('-inf')})
            value = values.get(key)
            if not rule.get('enabled', False) or value is None:
                st['since'] = None
                continue
            threshold = float(rule['threshold'])
            if value > threshold:
                if st['since'] is None: st['since'] = now
                duration = 0 if rule.get('mode') == 'instant' else float(rule.get('duration', 10))
                if now - st['since'] >= duration and not st['active']:
                    st['active'] = True
                    if now - st['last_sent'] >= float(rule.get('cooldown', 300)):
                        events.append({'key': key, 'kind': 'alert', 'value': value, 'threshold': threshold})
                        st['last_sent'] = now
            elif value <= threshold - (2 if 'temp' in key else 1):
                st['since'] = None
                if st['active']:
                    st['active'] = False
                    events.append({'key': key, 'kind': 'recovery', 'value': value, 'threshold': threshold})
        return events
