"""Device health telemetry (CPU load / temperature / memory) - Linux /proc + /sys, with graceful fallbacks."""
from __future__ import annotations

import glob
import os
import time


class Telemetry:
    def __init__(self):
        self._prev = None
        self.t0 = time.monotonic()
        self._cache = {}
        self._t_cache = -1e9
        self.zones = sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp"))

    def _cpu(self):
        try:
            with open("/proc/stat") as f:
                parts = f.readline().split()[1:]
            vals = list(map(int, parts))
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            total = sum(vals)
            if self._prev is None:
                self._prev = (idle, total)
                return None
            di, dt = idle - self._prev[0], total - self._prev[1]
            self._prev = (idle, total)
            return None if dt <= 0 else round(100.0 * (1 - di / dt), 1)
        except OSError:
            try:
                import psutil  # type: ignore

                return psutil.cpu_percent()
            except ImportError:
                return None

    def _temp(self):
        best = None
        for z in self.zones:
            try:
                with open(z) as f:
                    v = int(f.read().strip()) / 1000.0
                if 0 < v < 150:
                    best = v if best is None else max(best, v)
            except (OSError, ValueError):
                pass
        return None if best is None else round(best, 1)

    def _mem(self):
        try:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":", 1)
                    info[k] = int(v.split()[0])
            return round((info["MemTotal"] - info.get("MemAvailable", 0)) / 1024.0, 0)
        except (OSError, KeyError, ValueError):
            return None

    def snapshot(self):
        now = time.monotonic()
        if now - self._t_cache >= 1.0:
            self._cache = {
                "cpu_pct": self._cpu(),
                "cpu_temp_c": self._temp(),
                "mem_used_mb": self._mem(),
                "load1": round(os.getloadavg()[0], 2) if hasattr(os, "getloadavg") else None,
                "uptime_s": round(now - self.t0, 0),
            }
            self._t_cache = now
        return dict(self._cache)
