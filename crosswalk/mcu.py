"""Link to the UNO Q's STM32 microcontroller through the arduino-router (MessagePack-RPC over a Unix socket).

The MCU sketch (firmware/crosswalk_mcu/sketch/sketch.ino) provides:
    set_signal(veh:int, ped:int)   veh 0=off 1=red 2=yellow 3=green 4=flash-yellow ; ped 0=off 1=red 2=green 3=flash
    set_warning(level:int)          0 off, 1 caution (slow blink), 2 danger (fast blink + buzzer)
    draw(frame:bytes[104])          8x13 LED matrix, values 0..7
    heartbeat(ms:int) -> int        MCU watchdog: no heartbeat for 2 s -> lamps go to flashing amber
    ping() -> int
and notifies us with:
    ped_button()                    physical pedestrian call button

On the laptop (no socket) everything runs against a virtual MCU whose state is mirrored in the dashboard.
"""
from __future__ import annotations

import itertools
import os
import socket
import threading
import time

try:
    import msgpack  # type: ignore

    def _packb(o):
        return msgpack.packb(o, use_bin_type=True)

    def _unpacker():
        return msgpack.Unpacker(raw=False)

except ImportError:  # pragma: no cover - board without msgpack
    from . import msgpack_lite as msgpack  # type: ignore

    def _packb(o):
        return msgpack.packb(o)

    def _unpacker():
        return msgpack.Unpacker()

VEH_CODE = {"off": 0, "red": 1, "yellow": 2, "green": 3, "flash": 4}
PED_CODE = {"off": 0, "red": 1, "green": 2, "flash": 3}


class RouterClient:
    """Minimal MessagePack-RPC client for /var/run/arduino-router.sock."""

    def __init__(self, path="/var/run/arduino-router.sock", timeout=1.0):
        self.path = path
        self.timeout = timeout
        self.sock = None
        self.lock = threading.Lock()
        self.ids = itertools.count(1)
        self.pending = {}
        self.handlers = {}
        self.reader = None
        self.alive = False

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self.path)
        s.settimeout(None)
        self.sock = s
        self.alive = True
        self.reader = threading.Thread(target=self._read_loop, daemon=True, name="router-reader")
        self.reader.start()
        for name in list(self.handlers):
            self.call("$/register", name)

    def close(self):
        self.alive = False
        try:
            self.sock.close()
        except Exception:  # noqa: BLE001
            pass

    def _send(self, msg):
        data = _packb(msg)
        with self.lock:
            self.sock.sendall(data)

    def call(self, method, *params, timeout=None):
        msgid = next(self.ids) & 0x7FFFFFFF
        ev = threading.Event()
        slot = {"ev": ev}
        self.pending[msgid] = slot
        self._send([0, msgid, method, list(params)])
        if not ev.wait(timeout or self.timeout):
            self.pending.pop(msgid, None)
            raise TimeoutError(f"{method} timed out")
        if slot.get("error"):
            raise RuntimeError(f"{method}: {slot['error']}")
        return slot.get("result")

    def notify(self, method, *params):
        self._send([2, method, list(params)])

    def provide(self, name, fn):
        self.handlers[name] = fn
        if self.alive:
            self.call("$/register", name)

    def _read_loop(self):
        up = _unpacker()
        while self.alive:
            try:
                data = self.sock.recv(4096)
            except OSError:
                break
            if not data:
                break
            up.feed(data)
            for msg in up:
                try:
                    self._dispatch(msg)
                except Exception:  # noqa: BLE001
                    pass
        self.alive = False

    def _dispatch(self, msg):
        typ = msg[0]
        if typ == 1:  # response
            _, msgid, err, res = msg
            slot = self.pending.pop(msgid, None)
            if slot:
                slot["error"], slot["result"] = err, res
                slot["ev"].set()
        elif typ == 0:  # request from MCU
            _, msgid, method, params = msg
            fn = self.handlers.get(method)
            try:
                res = fn(*params) if fn else None
                self._send([1, msgid, None if fn else f"method {method} not available", res])
            except Exception as e:  # noqa: BLE001
                self._send([1, msgid, str(e), None])
        elif typ == 2:  # notification
            _, method, params = msg
            fn = self.handlers.get(method)
            if fn:
                fn(*params)


# ------------------------------------------------------------------------------------------ LED matrix
ROWS, COLS = 8, 13
FONT3x5 = {
    "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"], "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"], "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"], "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"], "9": ["111", "101", "111", "001", "111"],
    "k": ["100", "101", "110", "101", "101"], "+": ["000", "010", "111", "010", "000"],
    "-": ["000", "000", "111", "000", "000"], " ": ["000", "000", "000", "000", "000"],
}
ICONS = {
    "walk": ["0000110000000", "0000110000000", "0001111000000", "0010110100000", "0000110000000",
             "0001001000000", "0010000100000", "0010000100000"],
    "bike": ["0000000110000", "0000001100000", "0000011110000", "0011100010000", "0100010101110",
             "1000101010001", "1000100010001", "0111000001110"],
    "car": ["0000000000000", "0001111110000", "0010000001000", "0100000000100", "1111111111110",
            "1111111111110", "0110000001100", "0110000001100"],
    "warn": ["0000001000000", "0000010100000", "0000110110000", "0001010101000", "0011010101100",
             "0110000000110", "1100010001011", "1111111111111"],
}


def _blank():
    return [[0] * COLS for _ in range(ROWS)]


def render_icon(name, level=7):
    g = _blank()
    for r, row in enumerate(ICONS[name]):
        for c, ch in enumerate(row[:COLS]):
            if ch == "1":
                g[r][c] = level
    return g


def render_number(n, level=7):
    s = str(int(n)) if n < 1000 else f"{min(99, n // 1000)}k"
    s = s[-3:]
    g = _blank()
    width = len(s) * 4 - 1
    x0 = max(0, (COLS - width) // 2)
    for i, ch in enumerate(s):
        glyph = FONT3x5.get(ch, FONT3x5[" "])
        for r, row in enumerate(glyph):
            for c, b in enumerate(row):
                if b == "1" and x0 + i * 4 + c < COLS:
                    g[1 + r][x0 + i * 4 + c] = level
    return g


def to_bytes(grid) -> bytes:
    return bytes(v & 0x07 for row in grid for v in row)


class MCU:
    """High-level MCU interface. The pipeline only sets the *desired* state; a worker thread pushes
    changes to the MCU so a slow / absent MCU can never stall the vision loop. Works without hardware
    (virtual mode - the dashboard mirrors the lamps and the LED matrix)."""

    def __init__(self, cfg, on_button=None):
        self.cfg = cfg
        self.client = None
        self.virtual = True
        self.state = {"veh": "off", "ped": "off", "warning": 0, "matrix": None, "connected": False,
                      "page": None, "error": None, "rtt_ms": None}
        self._desired = {}
        self._sent = {}
        self._lock = threading.Lock()
        self._t_matrix = -1e9
        self._page_i = 0
        self._t_page = 0.0
        self._on_button = on_button
        self._stop = False
        # The heartbeat certifies "vision is working", not just "Linux is up": it is sent only while fresh
        # camera frames keep arriving. A frozen camera or a hung vision loop therefore lets the MCU watchdog
        # put the lamps into flashing amber, exactly like a dead Linux side.
        self._t_vision = None
        self.vision_timeout_s = float(cfg.get("vision_timeout_s", 1.5))
        self.state["vision_age_s"] = None
        self.state["failsafe"] = True
        enabled = cfg.get("enabled", "auto")
        self.path = cfg.get("socket", "/var/run/arduino-router.sock")
        available = hasattr(socket, "AF_UNIX") and os.path.exists(self.path)
        if (enabled is True or enabled == "true") and not available:
            raise RuntimeError(f"MCU required but router socket is unavailable: {self.path}")
        if enabled is not False and enabled != "false" and available:
            self.virtual = False
            self._connect()
            threading.Thread(target=self._worker, daemon=True, name="mcu-worker").start()

    def _connect(self):
        if self.client:
            self.client.close()
        client = None
        try:
            client = RouterClient(self.path, timeout=0.5)
            if self._on_button:
                client.handlers["ped_button"] = lambda *a: self._on_button()
            client.connect()
            client.call("ping")  # router may be alive while the sketch is stopped or a GPIO test is loaded
            self.client = client
            self.state["connected"] = True
            self.state["error"] = None
            self._sent.clear()
        except Exception as e:  # noqa: BLE001
            if client:
                client.close()
            self.state["connected"] = False
            self.state["error"] = f"router: {e}"
            self.client = None

    def _worker(self):
        t_hb = 0.0
        while not self._stop:
            time.sleep(0.03)
            if self.client is None or not self.client.alive:
                time.sleep(1.0)
                self._connect()
                continue
            with self._lock:
                todo = [(k, v) for k, v in self._desired.items() if self._sent.get(k) != v]
            try:
                for k, v in todo:
                    self.client.call(k, *v)
                    self._sent[k] = v
                now = time.monotonic()
                if not self.vision_fresh():
                    self.state["failsafe"] = True  # withhold the heartbeat: MCU watchdog takes over
                elif now - t_hb >= float(self.cfg.get("heartbeat_s", 0.5)):
                    self.state["failsafe"] = False
                    t_hb = now
                    t0 = time.perf_counter()
                    self.client.call("heartbeat", int(now * 1000) & 0x7FFFFFFF)
                    self.state["rtt_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                self.state["error"] = None
            except Exception as e:  # noqa: BLE001
                self.state["error"] = str(e)
                if not self.client.alive:
                    self.state["connected"] = False

    def vision_frame(self):
        """Called by the pipeline for every new camera frame it has processed."""
        self._t_vision = time.monotonic()

    def vision_age(self):
        return None if self._t_vision is None else time.monotonic() - self._t_vision

    def vision_fresh(self):
        age = self.vision_age()
        return age is not None and age <= self.vision_timeout_s

    def _want(self, method, *params):
        with self._lock:
            self._desired[method] = params

    def close(self):
        self._stop = True
        if self.client:
            self.client.close()

    def tick(self, t, signal=None, warning_level=0, counts=None):
        veh = signal.veh_state() if signal else "off"
        ped = signal.ped_state() if signal else "off"
        self.state.update({"veh": veh, "ped": ped, "warning": int(warning_level)})
        age = self.vision_age()
        self.state["vision_age_s"] = None if age is None else round(age, 2)
        if self.virtual:
            self.state["failsafe"] = not self.vision_fresh()
        self._want("set_signal", VEH_CODE.get(veh, 0), PED_CODE.get(ped, 0))
        self._want("set_warning", int(warning_level))
        if t - self._t_matrix >= 1.0 / float(self.cfg.get("matrix_hz", 4.0)) or t < self._t_matrix:
            self._t_matrix = t
            grid, page = self._matrix_page(t, warning_level, counts or {})
            self.state["matrix"] = [v for row in grid for v in row]
            self.state["page"] = page
            self._want("draw", to_bytes(grid))

    def _matrix_page(self, t, warning_level, counts):
        if warning_level >= 2:
            on = int(t * 4) % 2 == 0
            return (render_icon("warn") if on else _blank()), "danger"
        if warning_level == 1:
            on = int(t * 2) % 2 == 0
            return (render_icon("walk") if on else render_icon("walk", 2)), "caution"
        pages = [("walk", "pedestrian"), ("bike", "bicycle"), ("car", "vehicle")]
        if t - self._t_page > 1.5:
            self._t_page = t
            self._page_i = (self._page_i + 1) % (len(pages) * 2)
        icon, kind = pages[self._page_i // 2]
        if self._page_i % 2 == 0:
            return render_icon(icon), f"icon:{kind}"
        n = counts.get(kind, 0) + (counts.get("micromobility", 0) if kind == "bicycle" else 0)
        return render_number(n), f"count:{kind}"
