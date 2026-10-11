"""Run the local Turin city district planner (no live camera required)."""
from __future__ import annotations

import argparse
import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from threading import Lock
from urllib.parse import urlparse
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from economics.model import DATA, defaults, load_dataset, run_scenario, validate

WEB = ROOT / "economics" / "web"
jobs = {}
lock = Lock()
executor = ThreadPoolExecutor(max_workers=1)
dataset = None


def calculate(job_id, payload):
    def update(fraction, message):
        with lock:
            jobs[job_id].update(progress=fraction, message=message)
    try:
        result = run_scenario(payload, dataset, update)
        result["computed_at"] = datetime.now(timezone.utc).isoformat()
        result["provenance"] = {name: json.loads((DATA / name).read_text(encoding="utf-8"))
                                for name in ("districts_manifest.json", "costs.json", "mobility_context.json", "traffic_presets.json", "cost_profiles.json", "gdp_assumptions.json")
                                if (DATA / name).exists()}
        with lock:
            jobs[job_id].update(status="complete", result=result)
    except Exception as exc:
        with lock:
            jobs[job_id].update(status="error", error=str(exc))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if "api/jobs" not in args[0]:
            super().log_message(fmt, *args)

    def respond(self, value, status=200, kind="application/json; charset=utf-8", filename=None):
        body = json.dumps(value, allow_nan=False).encode() if kind.startswith("application/json") else value
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/data":
            sources = []
            for file in ("districts_manifest.json", "costs.json", "gdp_assumptions.json"):
                candidate = DATA / file
                if candidate.exists():
                    sources.append({"file": "manifest.json" if file == "districts_manifest.json" else file,
                                    "data": json.loads(candidate.read_text(encoding="utf-8"))})
            presets = {name: json.loads((DATA / name).read_text(encoding="utf-8"))
                       for name in ("traffic_presets.json", "cost_profiles.json")}
            return self.respond({"geography": dataset, "defaults": defaults(), "sources": sources,
                                 "traffic_presets": presets["traffic_presets.json"], "cost_profiles": presets["cost_profiles.json"]})
        if path.startswith("/api/jobs/"):
            parts = path.split("/")
            with lock:
                job = jobs.get(parts[3])
                job = dict(job) if job else None
            if not job:
                return self.respond({"error": "Unknown simulation."}, 404)
            if len(parts) == 5 and parts[4] == "export.csv":
                if job["status"] != "complete":
                    return self.respond({"error": "Simulation is not complete."}, 409)
                out = io.StringIO(newline="")
                rows = job["result"]["areas"]
                writer = csv.DictWriter(out, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
                return self.respond(out.getvalue().encode("utf-8-sig"), kind="text/csv; charset=utf-8", filename="ocio-turin-districts.csv")
            return self.respond(job)
        name = "index.html" if path == "/" else path.lstrip("/")
        target = (WEB / name).resolve()
        if not target.is_relative_to(WEB.resolve()) or not target.is_file():
            return self.respond({"error": "Not found."}, 404)
        kinds = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".png": "image/png", ".txt": "text/plain"}
        return self.respond(target.read_bytes(), kind=kinds.get(target.suffix, "application/octet-stream"))

    def do_POST(self):
        if urlparse(self.path).path != "/api/run":
            return self.respond({"error": "Not found."}, 404)
        # JSON-only + loopback binding prevents a website from issuing cross-origin
        # simple form requests to the local modelling service.
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.respond({"error": "JSON required."}, 415)
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            return self.respond({"error": "Cross-origin requests are not accepted."}, 403)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 65536:
                raise ValueError("Scenario request is too large or empty.")
            payload = json.loads(self.rfile.read(size))
            validate(payload, dataset)
        except (ValueError, TypeError) as exc:
            return self.respond({"error": str(exc)}, 400)
        with lock:
            if any(j["status"] == "running" for j in jobs.values()):
                return self.respond({"error": "A simulation is already running."}, 409)
            while len(jobs) >= 20:
                jobs.pop(next(iter(jobs)))
            job_id = uuid4().hex
            jobs[job_id] = {"status": "running", "progress": 0, "message": "Preparing paired arrivals"}
        executor.submit(calculate, job_id, payload)
        self.respond({"job_id": job_id}, 202)


def main():
    global dataset
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8020)
    args = parser.parse_args()
    dataset = load_dataset()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"\u00f2cio deployment planner: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        executor.shutdown(wait=True)


if __name__ == "__main__":
    main()
