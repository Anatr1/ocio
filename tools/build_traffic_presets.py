"""Freeze traffic scenarios from the official 5T hourly Turin series.

The source estimates network arcs, not crossing lanes. The explicit
two-direction conversion below is a scenario assumption, not an observation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import statistics
from urllib.request import Request, urlopen

DATA = Path(__file__).resolve().parents[1] / "economics" / "data"
OUTPUT = DATA / "traffic_presets.json"
SOURCE = "https://www.muoversiatorino.it/it/numeri-mobilita/"
DIRECTIONS = 2


class PortalParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.rows = []
        self._script = None
        self._table = False
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self._script = []
        if tag == "table" and attrs.get("id") == "tablepress-0":
            self._table = True
        if self._table and tag == "tr":
            self._row = []
        if self._row is not None and tag == "td":
            self._cell = []

    def handle_data(self, value):
        if self._script is not None:
            self._script.append(value)
        if self._cell is not None:
            self._cell.append(value)

    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.scripts.append("".join(self._script))
            self._script = None
        if tag == "td" and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        if tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        if tag == "table":
            self._table = False


def numeric_arrays(script):
    # Parse only inert numeric literals. Never evaluate remote JavaScript.
    arrays = re.findall(r"\bdata\s*:\s*\[([\d,\s]+)\]", script)
    return [json.loads("[" + value.rstrip().rstrip(",") + "]") for value in arrays]


def parse_source(content):
    parser = PortalParser()
    parser.feed(content.decode("utf-8"))
    scripts = [script for script in parser.scripts if "var config_flussi" in script]
    if len(scripts) != 1 or len(parser.rows) != 2:
        raise ValueError("5T portal structure changed; inspect before rebuilding.")
    chart = scripts[0].split("var config_flussi", 1)[1].split("var config_ztl", 1)[0]
    labels = re.search(r"\blabels\s*:\s*(\[[^\]]+\])", chart)
    if not labels or json.loads(labels[1]) != [str(i) for i in range(25)]:
        raise ValueError("Unexpected hourly chart labels.")
    arrays = numeric_arrays(chart)
    if len(arrays) != 2:
        raise ValueError("Expected previous-day and previous-week flow series.")
    observations = []
    for row, values in zip(parser.rows, arrays):
        if len(row) != 5 or len(values) != 25 or values[0] != values[24]:
            raise ValueError("Unexpected daily table or repeated-midnight format.")
        match = re.search(r"\((\d{2}/\d{2}/\d{4})\)", row[0])
        if not match:
            raise ValueError("Source lacks an unambiguous observation date.")
        observations.append({
            "date": datetime.strptime(match[1], "%d/%m/%Y").date().isoformat(),
            "daily_mean_arc_vph": int(row[3].replace(".", "")),
            "hourly_mean_arc_vph": values[:24],
            "published_km_travelled": int(row[1].replace(".", "")),
        })
    return observations


def build(content):
    observations = parse_source(content)
    current = observations[0]
    hourly = current["hourly_mean_arc_vph"]
    peak_hour = hourly.index(max(hourly))
    overnight = statistics.mean(hourly[:6])
    weekday = datetime.strptime(current["date"], "%Y-%m-%d").strftime("%A")
    presets = {
        "peak": {
            "label": "Peak-hour traffic",
            "vehicle_vph": DIRECTIONS * max(hourly),
            "source_arc_vph": max(hourly),
            "source_hours": [peak_hour],
            "derivation": "2 x maximum of the 24 published hourly network-arc means",
        },
        "medium": {
            "label": "Medium traffic",
            "vehicle_vph": DIRECTIONS * current["daily_mean_arc_vph"],
            "source_arc_vph": current["daily_mean_arc_vph"],
            "source_hours": list(range(24)),
            "derivation": "2 x the published daily mean hourly network-arc flow",
        },
        "light": {
            "label": "Light traffic",
            "vehicle_vph": round(DIRECTIONS * overnight),
            "source_arc_vph": overnight,
            "source_hours": list(range(6)),
            "derivation": "round(2 x arithmetic mean of hourly network-arc means at 00:00 through 05:00)",
        },
    }
    date_label = datetime.strptime(current["date"], "%Y-%m-%d").strftime("%d %b %Y").lstrip("0")
    caveat = f"Modelled citywide network-arc estimates, not directly measured crossing-lane counts. Two-direction conversion assumes two representative arcs. One {weekday} profile is not an annual traffic distribution."
    result = {
        "schema_version": 1,
        "presets": presets,
        "short_note": f"5T Turin profile, {date_label}. Two-direction crossing proxy.",
        "caveat": caveat,
        "sources": [{
            "title": "5T / Muoversi a Torino: I numeri della mobilita",
            "url": SOURCE,
            "reference": f"Flussi medi hourly chart and daily summary, {current['date']}; Supervisore network-arc estimates",
        }],
        "units": "vehicles per hour across both simulated travel directions",
        "source": {
            "title": "5T / Muoversi a Torino: I numeri della mobilita, Flussi medi",
            "url": SOURCE,
            "provider": "5T Srl for the City of Torino",
            "observation_date": current["date"],
            "observation_weekday": weekday,
            "timezone": "Europe/Rome",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "raw_html_sha256": hashlib.sha256(content).hexdigest(),
            "source_units": "modelled mean vehicles/hour per network arc (road section)",
            "method": "Supervisore mathematical traffic model informed by travel surveys and fixed traffic detectors",
            "update_schedule": "08:00 for the preceding day; same weekday of prior week also published",
            "license": "No dataset-specific open licence verified for this page; numeric facts transformed with attribution",
        },
        "observations": observations,
        "conversion": {
            "directions": DIRECTIONS,
            "direction_split": [0.5, 0.5],
            "assumption": "Represent each of two simulated directions by one city-average network arc; total demand is twice the published arc flow. No source lane-count normalization is claimed.",
            "rounding": "Nearest integer vehicle/hour for light; peak and medium already integer",
        },
        "caveats": [
            "Source-calibrated scenario proxies, not observed demand at an individual pedestrian crossing.",
            "Modelled citywide network-arc averages, not directly measured per-lane flow; local roads differ in lane count and demand.",
            "Peak is a temporal maximum in published hourly estimates for one weekday, not a spatial-counter percentile or annual design peak.",
            f"Levels come from one {weekday}, not a representative annual or multi-day sample.",
            "Hour24 repeats hour0 in the chart. This extra point is excluded from calculations.",
            "Medium uses the separately published rounded daily mean; the mean of rounded hourly values can differ slightly.",
            "Traffic presets do not validate annual operating hours, street-specific demand, benefit attribution, or economic assumptions.",
        ],
    }
    validate(result)
    return result


def validate(result):
    presets = result["presets"]
    current = result["observations"][0]
    hourly = current["hourly_mean_arc_vph"]
    if len(result["observations"]) != 2:
        raise ValueError("Expected two dates in the frozen source.")
    for observation in result["observations"]:
        values = observation["hourly_mean_arc_vph"]
        if len(values) != 24 or any(type(v) is not int or v < 0 for v in values):
            raise ValueError("Expected 24 nonnegative integer source values.")
    dates = [datetime.strptime(o["date"], "%Y-%m-%d") for o in result["observations"]]
    if (dates[0] - dates[1]).days != 7:
        raise ValueError("Expected the previous week comparison date.")
    expected = {
        "peak": DIRECTIONS * max(hourly),
        "medium": DIRECTIONS * current["daily_mean_arc_vph"],
        "light": round(DIRECTIONS * statistics.mean(hourly[:6])),
    }
    if any(presets[key]["vehicle_vph"] != value for key, value in expected.items()):
        raise ValueError("Preset does not match its documented derivation.")
    if presets["peak"]["source_hours"] != [hourly.index(max(hourly))]:
        raise ValueError("Peak hour does not match the published time series.")
    if not 0 < expected["light"] < expected["medium"] < expected["peak"]:
        raise ValueError("Unexpected ordering; review scenario definitions.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify frozen JSON without downloading")
    parser.add_argument("--inspect", action="store_true", help="Print fresh result without updating the frozen file")
    args = parser.parse_args()
    if args.check:
        result = json.loads(OUTPUT.read_text(encoding="utf-8"))
        validate(result)
    else:
        request = Request(SOURCE, headers={"User-Agent": "OCCHIO-public-traffic-research/1.0"})
        with urlopen(request, timeout=90) as response:
            result = build(response.read())
        if args.inspect:
            print(json.dumps(result, indent=2))
            return
        OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(result["source"]["observation_date"], {key: preset["vehicle_vph"] for key, preset in result["presets"].items()})


if __name__ == "__main__":
    main()
