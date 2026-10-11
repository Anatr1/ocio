"""Zero-dependency HTTP server (stdlib): dashboard, Server-Sent-Events live stream, REST API, MJPEG.

Endpoints
---------
GET  /                      dashboard (static files from ./dashboard)
GET  /api/config            scene / node / camera description
GET  /api/state             latest snapshot (tracks, counts, safety, signal, perf, mcu)
GET  /api/stream            SSE: 'config' once, then 'state' at stream_hz + 'event' / 'replay_ready' pushes
GET  /api/events?since=ID   recent events
GET  /api/replays           available 3D replays
GET  /api/replay/<id>       trajectories around an event
GET  /api/background.png    bird's-eye-view ground texture (person-free background, ortho-rectified)
GET  /api/frame.jpg         latest annotated + privacy-blurred frame
GET  /video.mjpg            annotated + privacy-blurred MJPEG stream (encoded only while somebody watches)
GET  /api/health            liveness
GET  /public/               citizen crossing page (read-only, no camera)
GET  /public/api/stats      anonymous persistent aggregates + live status
POST /api/ped_request       pedestrian call (virtual push button)
POST /api/mode              {"mode": "adaptive"|"fixed"|"beacon"}
POST /api/reset             reset counters
"""
from __future__ import annotations

import json
import mimetypes
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(ROOT, "dashboard")


def _default(o):
    try:
        import numpy as np

        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def dumps(o) -> str:
    return json.dumps(o, default=_default, separators=(",", ":"))


_json_cache = {"v": -1, "s": "{}"}
_json_lock = threading.Lock()


def _state_json(node) -> str:
    """Serialise the state once per version, shared by every SSE client (saves CPU on the board)."""
    with _json_lock:
        v = node.state_version
        if _json_cache["v"] != v:
            _json_cache["s"] = dumps(node.state_payload())
            _json_cache["v"] = v
        return _json_cache["s"]


def lan_ip() -> str | None:
    """Best-effort LAN address (no packets are sent: UDP connect only selects a route)."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def qr_svg(text: str) -> str | None:
    try:
        import io

        import segno

        buf = io.BytesIO()
        segno.make(text, error="m").save(buf, kind="svg", scale=8, border=2, dark="#0b0e13", light="#ffffff")
        return buf.getvalue().decode()
    except Exception:  # noqa: BLE001 - segno is optional
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "CrosswalkNode/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet
        pass

    @property
    def node(self):
        return self.server.node

    # ------------------------------------------------------------------ helpers
    def _send(self, code, body: bytes, ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype):
        """Stream a (possibly large) file in chunks instead of loading it into memory."""
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
        self.end_headers()
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                self.wfile.write(chunk)

    def _json(self, obj, code=200):
        self._send(code, dumps(obj).encode())

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode() or "{}")
        except json.JSONDecodeError:
            return {}

    # ------------------------------------------------------------------ routes
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        p = urlparse(self.path).path
        body = self._body()
        n = self.node
        if p == "/public" or p.startswith("/public/"):
            return self._json({"error": "read-only public page"}, 405)  # no actuation on public routes
        if p == "/api/ped_request":
            n.request_crossing()
            return self._json({"ok": True})
        if p == "/api/mode":
            ok = n.set_signal_mode(body.get("mode", "adaptive"))
            return self._json({"ok": ok})
        if p == "/api/reset":
            n.reset_counts()
            return self._json({"ok": True})
        if p == "/api/scenario" and hasattr(n, "inject_scenario"):
            ok = n.inject_scenario(body.get("name", "near_miss"))
            return self._json({"ok": ok})
        if p == "/api/record":
            if body.get("action") == "stop":
                n.recorder.stop()
            else:
                n.recorder.start(body.get("name", "rec"))
            return self._json(n.recorder.status())
        if p == "/api/calibrate":
            pts = body.get("image_points")
            if not pts or len(pts) < 4:
                return self._json({"error": "need 4 image_points"}, 400)
            info = n.calibrate(pts, body.get("width"), body.get("length"), save=body.get("save", True))
            return self._json({"ok": True, "info": info, "config": n.config_payload()})
        return self._json({"error": "not found"}, 404)

    def do_GET(self):
        url = urlparse(self.path)
        p = url.path
        n = self.node
        if p == "/public" or p.startswith("/public/"):
            if not n.cfg.get("public", {}).get("enabled", True):
                return self._json({"error": "public page disabled"}, 404)
            if p == "/public":
                return self._send(301, b"", "text/plain", {"Location": "/public/"})
            if p == "/public/api/stats":
                return self._json(n.public_payload())
            assets = {"/public/": "/citizen.html", "/public/public.js": "/js/public.js",
                      "/public/public.css": "/css/public.css", "/public/theme.css": "/css/style.css",
                      "/public/fonts/manrope-latin.woff2": "/fonts/manrope-latin.woff2"}
            if p in assets:
                return self._static(assets[p])
            return self._json({"error": "not found"}, 404)
        if p == "/api/config":
            return self._json(n.config_payload())
        if p == "/api/state":
            return self._json(n.state_payload())
        if p == "/api/gt":
            return self._json(n.gt_payload or {"error": "no ground truth (not a simulation)"}, 200 if n.gt_payload else 404)
        if p == "/api/health":
            # ok = vision is alive (fresh frames), not merely "the web server answers"
            age = n.mcu.vision_age()
            fresh = n.mcu.vision_fresh()
            body = {"ok": fresh, "t": time.time(), "node": n.node_id,
                    "vision_age_s": None if age is None else round(age, 2),
                    "mcu_connected": n.mcu.state.get("connected"), "failsafe": n.mcu.state.get("failsafe")}
            return self._json(body, 200 if fresh else 503)
        if p == "/api/events":
            q = parse_qs(url.query)
            since = int(q.get("since", ["0"])[0])
            return self._json(n.bus.recent(200, since))
        if p == "/api/replays":
            return self._json([{"id": k, "event": v["event"], "frames": len(v["frames"])} for k, v in n.bus.replays.items()])
        if p.startswith("/api/replay/"):
            try:
                rid = int(p.rsplit("/", 1)[1])
            except ValueError:
                return self._json({"error": "bad id"}, 400)
            clip = n.bus.replays.get(rid)
            return self._json(clip) if clip else self._json({"error": "not ready"}, 404)
        if p == "/api/background.png":
            png = n.background_png()
            if png is None:
                return self._json({"error": "no background yet"}, 404)
            return self._send(200, png, "image/png")
        if p == "/api/frame.jpg":
            jpg = n.frame_jpeg()
            if jpg is None:
                return self._json({"error": "no frame"}, 404)
            return self._send(200, jpg, "image/jpeg")
        if p in ("/api/background.jpg", "/api/calib_preview.jpg"):
            jpg = n.background_jpeg(overlay=p.endswith("preview.jpg"))
            if jpg is None:
                return self._json({"error": "no background yet"}, 404)
            return self._send(200, jpg, "image/jpeg")
        if p == "/api/auto_calibrate":
            r = n.auto_calibration()
            return self._json(r or {"error": "no zebra found"}, 200 if r else 404)
        if p == "/api/share":
            if not n.cfg.get("public", {}).get("enabled", True):
                return self._json({"error": "public page disabled"}, 404)
            host = self.headers.get("Host", "")
            port = self.server.server_address[1]
            configured = n.cfg.get("public", {}).get("url")
            if configured:
                parsed = urlparse(str(configured))
                if (parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password
                        or parsed.query or parsed.fragment or not parsed.path.endswith("/public/")):
                    return self._json({"error": "public.url must be an http(s) URL ending in /public/"}, 400)
                url = str(configured)
            else:
                bind_host = self.server.server_address[0]
                if bind_host == "0.0.0.0":
                    ip = lan_ip()
                    address = f"{ip}:{port}" if ip else host
                else:
                    # A localhost/specific-interface server is not reachable at
                    # an unrelated LAN address selected by the default route.
                    address = host or f"{bind_host}:{port}"
                url = f"http://{address}/public/"
            return self._json({"url": url, "svg": qr_svg(url)})
        if p == "/recordings":
            rows = "".join(f'<li><a href="/recordings/{r["name"]}" download>{r["name"]}</a> ({r["mb"]} MB)</li>'
                           for r in n.recorder.list())
            page = (f"<!doctype html><html lang='en'><meta charset=utf-8>"
                    f"<meta name=viewport content='width=device-width,initial-scale=1'>"
                    f"<title>òcio · Recordings</title><link rel='stylesheet' href='/css/style.css'>"
                    f"<body class='utility-page'><header class='topbar'><div class='brand'>"
                    f"<div class='brand-name'>òcio</div></div></header>"
                    f"<main class='utility-wrap'><div class='card'><h1>Recordings on this node</h1>"
                    f"<p>Raw footage (faces, plates): keep it local, never publish.</p>"
                    f"<ul class='recording-list'>{rows or '<li>none yet</li>'}</ul></div></main></body></html>")
            return self._send(200, page.encode(), "text/html; charset=utf-8")
        if p.startswith("/recordings/"):
            full = n.recorder.path(p.rsplit("/", 1)[1])
            if full is None:
                return self._json({"error": "not found"}, 404)
            return self._send_file(full, "video/mp4")
        if p == "/api/stream":
            return self._sse()
        if p == "/video.mjpg":
            return self._mjpeg()
        return self._static(p)

    def _static(self, p):
        if p in ("", "/"):
            p = "/index.html"
        full = os.path.normpath(os.path.join(DASH, p.lstrip("/")))
        if not full.startswith(os.path.normpath(DASH)) or not os.path.isfile(full):
            return self._json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".js"):
            ctype = "text/javascript"
        with open(full, "rb") as f:
            data = f.read()
        self._send(200, data, ctype, {"Cache-Control": "no-cache"})

    def _sse(self):
        n = self.node
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q: queue.Queue = queue.Queue(maxsize=500)

        def push(msg):
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

        n.bus.subscribe(push)
        period = 1.0 / float(n.cfg.server.get("stream_hz", 10.0))
        last_v = -1
        try:
            self._sse_write("config", n.config_payload())
            t_next = 0.0
            while n.running:
                now = time.monotonic()
                timeout = max(0.0, t_next - now)
                try:
                    msg = q.get(timeout=timeout if timeout > 0 else 0.001)
                    self._sse_write(msg["type"], msg.get("event", msg))
                    continue
                except queue.Empty:
                    pass
                if time.monotonic() >= t_next:
                    t_next = time.monotonic() + period
                    v = n.state_version
                    if v != last_v:
                        last_v = v
                        self._sse_raw("state", _state_json(n))
                        if n.gt_payload is not None:  # simulator ground truth, separate channel
                            self._sse_write("gt", n.gt_payload)
                    else:
                        self.wfile.write(b": ka\n\n")
                        self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            n.bus.unsubscribe(push)

    def _sse_write(self, event, data):
        self._sse_raw(event, dumps(data))

    def _sse_raw(self, event, data_json: str):
        self.wfile.write(f"event: {event}\ndata: {data_json}\n\n".encode())
        self.wfile.flush()

    def _mjpeg(self):
        n = self.node
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        n.mjpeg_clients += 1
        last = None
        try:
            while n.running:
                jpg = n.frame_jpeg()
                if jpg is not None and jpg is not last:
                    last = jpg
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                    self.wfile.flush()
                time.sleep(0.03)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            n.mjpeg_clients -= 1


class Server:
    def __init__(self, node, host="0.0.0.0", port=8000):
        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self.httpd.node = node
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="http")

    def start(self):
        self.th.start()

    def stop(self):
        self.httpd.shutdown()
