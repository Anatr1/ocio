"""Pin local web dependencies so the planner runs without a CDN."""
from pathlib import Path
from urllib.request import urlopen, Request

TARGET = Path(__file__).resolve().parents[1] / "economics" / "web" / "vendor"
FILES = {
    "leaflet.js": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
    "leaflet.css": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
    "LICENSE-leaflet.txt": "https://unpkg.com/leaflet@1.9.4/LICENSE",
    "chart.js": "https://unpkg.com/chart.js@4.4.8/dist/chart.umd.js",
    "LICENSE-chart.txt": "https://unpkg.com/chart.js@4.4.8/LICENSE.md",
    "lucide.js": "https://unpkg.com/lucide@0.468.0/dist/umd/lucide.min.js",
    "LICENSE-lucide.txt": "https://unpkg.com/lucide@0.468.0/LICENSE",
}

if __name__ == "__main__":
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        with urlopen(Request(url, headers={"User-Agent": "OCCHIO-hackathon-data/1.0"}), timeout=60) as response:
            payload = response.read()
        (TARGET / name).write_bytes(payload)
        print(name, len(payload))
