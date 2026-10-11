"""Fleet hub: aggregate several OCCHIO nodes into one city view (scalability demo).

    python tools/hub.py --nodes http://192.168.8.10:8000 http://localhost:8001 http://localhost:8002
    -> open http://localhost:9000/fleet.html

Each node pushes anonymous state over SSE (~2 KB/s); the hub keeps the latest state per node and a merged
event feed. Nodes stay autonomous: if the hub dies, every crosswalk keeps working and actuating.
Launch a whole simulated fleet with: python tools/demo_fleet.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(ROOT, "dashboard")


class NodeLink:
    def __init__(self, url, feed):
        self.url = url.rstrip("/")
        self.config = None
        self.state = None
        self.online = False
        self.t_seen = 0.0
        self.feed = feed
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                with urllib.request.urlopen(self.url + "/api/stream", timeout=15) as r:
                    self.online = True
                    ev, data = None, []
                    for raw in r:
                        line = raw.decode("utf-8", "replace").rstrip("\n").rstrip("\r")
                        if line.startswith("event:"):
                            ev = line[6:].strip()
                        elif line.startswith("data:"):
                            data.append(line[5:].strip())
                        elif line == "":
                            if ev and data:
                                self._handle(ev, json.loads("".join(data)))
                            ev, data = None, []
            except Exception:  # noqa: BLE001
                self.online = False
                time.sleep(2)

    def _handle(self, ev, d):
        self.t_seen = time.time()
        if ev == "config":
            self.config = d
        elif ev == "state":
            self.state = d
        elif ev == "event" and not d.get("log_only"):
            if d.get("type") in ("conflict", "pet", "yield", "violation", "alert", "ped_extension", "jaywalk") or \
                    (d.get("type") == "vehicle_pass" and d.get("speeding")):
                d = dict(d)
                d["node_name"] = (self.config or {}).get("node", {}).get("name", self.url)
                d["node_url"] = self.url
                self.feed.appendleft(d)

    def summary(self):
        c = self.config or {}
        s = self.state or {}
        return {
            "url": self.url,
            "online": self.online and time.time() - self.t_seen < 5,
            "node": c.get("node", {}),
            "scene": {"crosswalk": (c.get("scene") or {}).get("crosswalk")},
            "counts": (s.get("counts") or {}).get("counts", {}),
            "v85": (s.get("counts") or {}).get("vehicle_v85_kmh"),
            "safety": {k: (s.get("safety") or {}).get(k) for k in ("near_miss", "yield_rate", "safety_score", "warning_level", "pet_min")},
            "signal": {k: (s.get("signal") or {}).get(k) for k in ("mode", "veh", "ped")},
            "perf": {k: (s.get("perf") or {}).get(k) for k in ("det_hz", "infer_ms", "cpu_temp_c", "duty")},
            "tracks": len(s.get("tracks") or []),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", nargs="+", required=True)
    ap.add_argument("--port", type=int, default=9000)
    args = ap.parse_args()
    feed = deque(maxlen=200)
    links = [NodeLink(u, feed) for u in args.nodes]

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            p = self.path.split("?")[0]
            if p == "/api/fleet":
                body = json.dumps({"nodes": [lk.summary() for lk in links], "events": list(feed)[:60], "t": time.time()}).encode()
                return self._send(200, body, "application/json")
            if p in ("/", ""):
                p = "/fleet.html"
            full = os.path.normpath(os.path.join(DASH, p.lstrip("/")))
            if not full.startswith(os.path.normpath(DASH)) or not os.path.isfile(full):
                return self._send(404, b"not found", "text/plain")
            ctype = "text/html" if full.endswith(".html") else "text/css" if full.endswith(".css") else \
                "text/javascript" if full.endswith(".js") else "application/octet-stream"
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype)

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), H)
    srv.daemon_threads = True
    print(f"[hub] {len(links)} nodes -> http://localhost:{args.port}/fleet.html")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
