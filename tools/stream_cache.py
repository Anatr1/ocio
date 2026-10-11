"""Pace cached camera pixels over timestamped MJPEG for the real board's NetworkSource."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.cache_source import CacheSource


def handler_for(source, loop=False):
    class StreamHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/calibration.json":
                payload = json.dumps({"calibration": source.calibration(), "scene": source.metadata["scene"],
                                      "cache_content_hash": source.content_hash, "control": source.metadata["control"]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path != "/video.mjpg":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            start, seq, offset = time.monotonic(), 0, 0.0
            first = source.entries[0][1]["t"]
            period = source.entries[-1][1]["t"] - first + 1 / source.fps
            try:
                while True:
                    for image, meta in source.entries:
                        t = meta["t"] + offset
                        delay = t - first - (time.monotonic() - start)
                        if delay > 0:
                            time.sleep(delay)
                        seq += 1
                        data = image.read_bytes()
                        headers = (f"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {len(data)}\r\n"
                                   f"X-Timestamp: {t:.9f}\r\nX-Sequence: {seq}\r\n\r\n").encode("ascii")
                        self.wfile.write(headers + data + b"\r\n")
                        self.wfile.flush()
                    if not loop:
                        break
                    offset += period
                self.wfile.write(b"--frame--\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def log_message(self, *args):
            pass
    return StreamHandler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cache", type=Path)
    ap.add_argument("--host", default="127.0.0.1", help="use the laptop LAN address/0.0.0.0 only on a trusted board network")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()
    source = CacheSource(args.cache)
    server = ThreadingHTTPServer((args.host, args.port), handler_for(source, args.loop))
    print(f"MJPEG: http://{args.host}:{server.server_port}/video.mjpg", flush=True)
    print("Open-loop recorded trajectories; this is transport infrastructure, not a completed L3 watchdog test.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        source.close()


if __name__ == "__main__":
    main()
