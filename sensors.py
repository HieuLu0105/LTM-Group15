"""Best-effort sensor discovery. Unsupported readings remain unavailable."""
import json
import sys
import time
import re
import math
from urllib.request import build_opener, ProxyHandler
import psutil
from hardware import _ps
from embedded_sensors import EmbeddedSensors

def parse_http_tree(tree):
    readings = []
    def visit(node, hardware='', hardware_id=''):
        if node.get('HardwareId'):
            hardware, hardware_id = node.get('Text', ''), node['HardwareId']
        if node.get('SensorId'):
            raw = str(node.get('RawValue', node.get('Value', ''))).strip()
            match = re.fullmatch(r'([-+]?\d+(?:[.,]\d+)?)\s*(.*)', raw)
            value = float(match[1].replace(',', '.')) if match else None
            if value is not None and not math.isfinite(value): value = None
            readings.append(dict(name=node.get('Text', ''), type=node.get('Type', ''),
                id=node['SensorId'], value=value, unit=match[2] if match else '',
                hardware=hardware, hardware_id=hardware_id, display=node.get('Value', raw),
                min=node.get('Min', ''), max=node.get('Max', ''), source='HTTP'))
        for child in node.get('Children', []) or []:
            visit(child, hardware, hardware_id)
    visit(tree)
    return readings


def http_sensors():
    opener = build_opener(ProxyHandler({}))
    with opener.open('http://localhost:8085/data.json', timeout=2) as response:
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024: raise ValueError('Sensor response too large')
    return parse_http_tree(json.loads(raw))


class SensorMonitor:
    def __init__(self):
        self.last = 0
        self.data = []
        self.embedded = EmbeddedSensors() if sys.platform == "win32" else None
        self.embedded_error = None

    def snapshot(self):
        if time.monotonic() - self.last < 5:
            return self.data
        self.last = time.monotonic()
        readings = []
        if self.embedded is not None:
            try:
                readings = self.embedded.snapshot()
                self.embedded_error = None
            except Exception as exc:
                message = str(exc)
                if message != self.embedded_error:
                    print('Embedded sensors unavailable:', message)
                self.embedded_error = message
                self.embedded.close()
            if readings:
                self.data = readings
                return readings
        try:
            readings = http_sensors()
        except (OSError, ValueError, TypeError, AttributeError, RecursionError):
            pass
        if readings:
            self.data = readings
            return readings
        if sys.platform == 'win32':
            script = r"Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor -ErrorAction SilentlyContinue | Select-Object Name,SensorType,Value,Identifier | ConvertTo-Json -Compress"
            try:
                raw = json.loads(_ps(script, 4) or '[]')
                for s in (raw if isinstance(raw, list) else [raw]):
                    if s.get('Value') is not None:
                        readings.append({'name': str(s.get('Name','')), 'type': str(s.get('SensorType','')),
                                         'value': round(float(s['Value']), 2), 'id': str(s.get('Identifier',''))})
            except (ValueError, TypeError, AttributeError):
                pass
        else:
            try:
                for group, entries in psutil.sensors_temperatures().items():
                    for i, s in enumerate(entries):
                        readings.append({'name': s.label or group, 'type': 'Temperature',
                                         'value': round(s.current, 2), 'id': f'{group}/{i}'})
            except (AttributeError, OSError):
                pass
        self.data = readings
        return readings


def max_temperature(sensors, component):
    candidates = []
    for s in sensors:
        if s['type'].lower() != 'temperature' or not isinstance(s['value'], (int, float)): continue
        if not math.isfinite(s['value']) or s['value'] <= 0: continue
        identity = (s['id'] + ' ' + s['name']).lower()
        if component == 'cpu' and any(x in identity for x in ('/cpu/', '/amdcpu/', '/intelcpu/', 'cpu package', 'core (tctl', 'k10temp', 'coretemp', 'cpu tctl')):
            candidates.append(s['value'])
        if component == 'gpu' and any(x in identity for x in ('/gpu-', '/gpu/', 'gpu core', 'amdgpu')):
            candidates.append(s['value'])
    return max(candidates) if candidates else None
