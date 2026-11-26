"""Optional in-process LibreHardwareMonitor provider (Windows)."""
import math
import pathlib
import sys
import threading
import atexit

UNITS = {'Temperature':'°C','Voltage':'V','Power':'W','Clock':'MHz','Load':'%', 'Fan':'RPM','Control':'%', 'Level':'%', 'Data':'GB','SmallData':'MB','Throughput':'B/s','Current':'A','Energy':'mWh','Timing':'ns','Frequency':'Hz','TimeSpan':'s','Flow':'L/h','Humidity':'%','Noise':'dBA'}

class EmbeddedSensors:
    def __init__(self):
        self.computer = None
        self.lock = threading.RLock()
        atexit.register(self.close)

    def open(self):
        folder = pathlib.Path(getattr(sys, '_MEIPASS', pathlib.Path(__file__).resolve().parent)) / 'libs'
        dll = folder / 'LibreHardwareMonitorLib.dll'
        if not dll.is_file():
            raise FileNotFoundError(str(dll))
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
        import clr
        clr.AddReference(str(dll))
        from LibreHardwareMonitor.Hardware import Computer
        computer = Computer()
        try:
            for name in ('IsCpuEnabled','IsGpuEnabled','IsMemoryEnabled','IsMotherboardEnabled','IsStorageEnabled','IsBatteryEnabled','IsNetworkEnabled','IsControllerEnabled'):
                if hasattr(computer, name):
                    setattr(computer, name, True)
            computer.Open()
        except Exception:
            computer.Close()
            raise
        self.computer = computer

    def snapshot(self):
        with self.lock:
            if self.computer is None:
                self.open()
            rows = []
            def number(v):
                if v is None: return None
                v = float(v)
                return v if math.isfinite(v) else None
            def visit(hw):
                hw.Update()
                for s in hw.Sensors:
                    kind = str(s.SensorType)
                    unit = UNITS.get(kind, '')
                    value = number(s.Value)
                    def fmt(v):
                        v = number(v)
                        return 'N/A' if v is None else f'{v:.3f} {unit}'.strip()
                    rows.append(dict(name=str(s.Name), type=kind, id=str(s.Identifier), value=value, unit=unit, hardware=str(hw.Name), hardware_id=str(hw.Identifier), display=fmt(s.Value), min=fmt(s.Min), max=fmt(s.Max), source='Embedded DLL'))
                for child in hw.SubHardware:
                    visit(child)
            for hw in self.computer.Hardware:
                visit(hw)
            return rows

    def close(self):
        with self.lock:
            if self.computer is not None:
                try: self.computer.Close()
                except Exception: pass
                self.computer = None
