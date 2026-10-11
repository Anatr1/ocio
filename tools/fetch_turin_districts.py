"""Recreate Torino's eight official districts and 2025 registry population.

Build-time dependencies: pyshp, shapely, pyproj. Uses the existing real OSM
crossing and 5T snapshot files, without synthesizing district traffic counts.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import statistics
from urllib.request import Request, urlopen
import zipfile

DATA = Path(__file__).resolve().parents[1] / "economics" / "data"
BOUNDARIES = "http://geoportale.comune.torino.it/geodati/zip/circoscrizioni_geo.zip"
POPULATION = "https://www.comune.torino.it/media/9692"
NAMES_URL = "https://decentramento.comune.torino.it/"
METADATA_URL = "https://geodati.gov.it/geoportale/visualizzazione-metadati/scheda-metadati?metadataid=c_l219%3A69a50017-e6b4-4b00-b06b-c4507c1afc15"
NAMES = {
    1: "Centro - Crocetta",
    2: "Santa Rita - Mirafiori Nord - Mirafiori Sud",
    3: "San Paolo - Cenisia - Pozzo Strada - Cit Turin - Borgata Lesna",
    4: "San Donato - Campidoglio - Parella",
    5: "Borgo Vittoria - Madonna di Campagna - Lucento - Vallette",
    6: "Barriera di Milano - Regio Parco - Barca - Bertolla - Falchera - Rebaudengo - Villaretto",
    7: "Aurora - Vanchiglia - Sassi Superga - Madonna del Pilone",
    8: "San Salvario - Cavoretto - Borgo Po - Nizza Millefonti - Lingotto - Filadelfia",
}


def download(url):
    with urlopen(Request(url, headers={"User-Agent": "OCCHIO-public-statistics-research/1.0"}), timeout=90) as response:
        return response.read()


def inspect():
    import shapefile

    content = download(BOUNDARIES)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        print(archive.namelist())
        shp = next(name for name in archive.namelist() if name.endswith(".shp"))
        reader = shapefile.Reader(shp=io.BytesIO(archive.read(shp)), dbf=io.BytesIO(archive.read(shp[:-4]+".dbf")))
        print(reader.fields)
        print(reader.records())
        print(archive.read(shp[:-4]+".prj"))
    print(download(POPULATION).decode("utf-8-sig"))


def build():
    import shapefile
    from pyproj import CRS, Transformer
    from shapely import STRtree
    from shapely.geometry import Point, shape, mapping
    from shapely.ops import transform

    boundaries = download(BOUNDARIES)
    population = download(POPULATION)
    properties = {}
    virtual = 0
    rows = csv.DictReader(io.StringIO(population.decode("utf-8-sig")), delimiter=";")
    for row in rows:
        row = {key.strip(): value for key, value in row.items()}
        number = row["circoscrizione"].strip()
        female, male = int(row["femmine"]), int(row["maschi"])
        if number == "Residenza virtuale":
            virtual = female + male
            continue
        n = int(number)
        properties[n] = {
            "id": f"C{n}", "name": f"Circoscrizione {n}", "zone": n,
            "zone_name": NAMES[n], "population": female+male,
            "population_female": female, "population_male": male,
            "population_year": 2025, "population_date": "2025-12-31",
            "population_source": "Archivio Anagrafico della Citta di Torino",
            "mapped_crossings": 0, "signalized_crossings": 0,
            "traffic_vph": None, "traffic_counter_count": 0, "traffic_source": None,
        }
    assert set(properties) == set(range(1, 9))
    assert sum(p["population"] for p in properties.values()) == 858874
    assert virtual == 4375
    polygons = {}
    with zipfile.ZipFile(io.BytesIO(boundaries)) as archive:
        shp = next(name for name in archive.namelist() if name.endswith(".shp"))
        reader = shapefile.Reader(shp=io.BytesIO(archive.read(shp)), dbf=io.BytesIO(archive.read(shp[:-4]+".dbf")), encoding="utf-8")
        crs = CRS.from_wkt(archive.read(shp[:-4]+".prj").decode())
        converter = Transformer.from_crs(crs, 4326, always_xy=True)
        for item in reader.iterShapeRecords():
            n = int(item.record["NCIRCO"])
            geometry = shape(item.shape.__geo_interface__)
            if not geometry.is_valid:
                geometry = geometry.buffer(0)
            properties[n]["area_km2"] = round(geometry.area / 1_000_000, 4)
            properties[n]["density_per_km2"] = round(properties[n]["population"] / properties[n]["area_km2"], 2)
            polygons[n] = transform(converter.transform, geometry)
            center = polygons[n].representative_point()
            properties[n]["center"] = [round(center.x, 6), round(center.y, 6)]
    assert set(polygons) == set(properties)
    ordered = sorted(polygons)
    tree = STRtree([polygons[n] for n in ordered])

    def assign(longitude, latitude):
        indices = tree.query(Point(longitude, latitude), predicate="intersects")
        return ordered[int(indices[0])] if len(indices) else None

    crossings_path = DATA / "crossings.json"
    crossings_bytes = crossings_path.read_bytes()
    crossings = json.loads(crossings_bytes)
    city_crossings, unassigned_crossings = 0, 0
    for crossing in crossings["records"]:
        if crossing["municipality_id"] != "001272":
            continue
        city_crossings += 1
        n = assign(crossing["longitude"], crossing["latitude"])
        if n is None:
            unassigned_crossings += 1
            continue
        properties[n]["mapped_crossings"] += 1
        properties[n]["signalized_crossings"] += int(crossing["signalized"])
    assert sum(p["mapped_crossings"] for p in properties.values()) + unassigned_crossings == city_crossings
    traffic_path = DATA / "traffic_snapshot.json"
    traffic_bytes = traffic_path.read_bytes()
    traffic = json.loads(traffic_bytes)
    grouped = {}
    unassigned_traffic = 0
    for counter in traffic["records"]:
        if counter["municipality_id"] != "001272" or not counter["used_local_benchmark"]:
            continue
        n = assign(counter["longitude"], counter["latitude"])
        if n is None:
            unassigned_traffic += 1
            continue
        grouped.setdefault(n, []).append(counter["flow_vph"])
    for n, values in grouped.items():
        properties[n]["traffic_vph"] = round(statistics.median(values), 1)
        properties[n]["traffic_counter_count"] = len(values)
        properties[n]["traffic_source"] = "5T single 5-minute directional local-road section median"
    features = [{"type": "Feature", "id": f"C{n}", "properties": properties[n],
                 "geometry": mapping(polygons[n].simplify(0.000025, preserve_topology=True))}
                for n in ordered]
    output = {"type": "FeatureCollection", "name": "Torino - eight circoscrizioni", "features": features}
    (DATA / "districts.geojson").write_text(json.dumps(output, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat()
    sources = [
        {"id": "district_boundaries", "title": "Comune di Torino Geoportale - Azzonamenti Statistici Circoscrizioni",
         "url": BOUNDARIES, "reference": "8-district boundaries introduced2016; RNDT metadata updated2023-05-24",
         "metadata_url": METADATA_URL, "license": "Official municipal open geodata; retain Comune di Torino attribution",
         "sha256": hashlib.sha256(boundaries).hexdigest(), "retrieved_at": now,
         "caveat": "Published HTTP download used because source HTTPS endpoint has TLS handshake failure. ZIP CRS EPSG3003, transformed to WGS84; map simplified0.000025degrees. Exact dataset licence identifier not established; attribution retained."},
        {"id": "district_population", "title": "Comune di Torino - Population by sex and circoscrizione2025",
         "url": POPULATION, "reference": "2025-12-31", "pdf_url": "https://www.comune.torino.it/media/9695",
         "license": "Municipal statistical open data; retain Ufficio Statistica and Archivio Anagrafico attribution",
         "sha256": hashlib.sha256(population).hexdigest(), "retrieved_at": now,
         "caveat": "Anagrafe registration, not ISTAT resident population.4,375 virtual-address residents excluded from mapped district denominator; not assigned to district1. Exact dataset licence identifier not established; attribution retained."},
        {"id": "district_names", "title": "Comune di Torino - Current circoscrizioni names", "url": NAMES_URL,
         "reference": "Current official names inspected2026-10-10", "license": "Official administrative names; attribute Comune di Torino"},
        {"id": "osm", "title": "OpenStreetMap crossing-node snapshot", "url": "https://www.openstreetmap.org/copyright",
         "reference": crossings["timestamp"], "license": "ODbL1.0; OpenStreetMap contributors",
         "sha256": hashlib.sha256(crossings_bytes).hexdigest(), "caveat": crossings["caveat"]},
        {"id": "traffic", "title": "5T measured traffic snapshot", "url": traffic["source"],
         "reference": traffic["generation_time"], "license": "IODL2.0; Citta di Torino /5T",
         "sha256": hashlib.sha256(traffic_bytes).hexdigest(), "caveat": traffic["caveat"]},
    ]
    manifest = {
        "dataset_version": "torino-8-circoscrizioni-2025-anagrafe-v1", "scope": "Torino city only",
        "retrieved_at": now, "districts": 8, "population": 858874,
        "virtual_address_population": virtual, "city_registry_population": 858874+virtual,
        "population_date": "2025-12-31", "population_definition": "Municipal anagrafe registration",
        "sources": sources, "mapped_crossings": sum(p["mapped_crossings"] for p in properties.values()),
        "signalized_crossings": sum(p["signalized_crossings"] for p in properties.values()),
        "city_crossing_nodes_before_district_assignment": city_crossings,
        "unassigned_crossing_nodes": unassigned_crossings, "unassigned_valid_traffic_counters": unassigned_traffic,
        "traffic_counter_count": sum(p["traffic_counter_count"] for p in properties.values()),
        "caveats": [
            "All mapped district population uses the same2025 anagrafe source; never combine with2024 ISTAT municipal population.",
            "Virtual-address registration is reported separately and not placed arbitrarily in a mapped district.",
            "Crossing inventory is OSM nodes, not installation complexes or a complete certified asset inventory.",
            "Only cached OSM /traffic points already inside ISTAT Torino municipality001272 are considered; no surrounding municipalities included.",
            "Municipal district geometry and ISTAT municipality geometry are different reference datasets. Unassigned edge nodes are reported, not allocated to the nearest district.",
            "Traffic snapshot is a single Saturday five-minute observation, not annual district demand; uncovered districts have null traffic benchmark.",
            "No district commuter distribution available in these sources; none is fabricated."
        ]
    }
    (DATA / "districts_manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({"population": manifest["population"], "registry_total": manifest["city_registry_population"],
                      "mapped_crossings": manifest["mapped_crossings"], "signals": manifest["signalized_crossings"],
                      "unassigned_crossings": unassigned_crossings,
                      "districts": [{"id":p["id"], "population":p["population"], "crossings":p["mapped_crossings"],
                                     "signals":p["signalized_crossings"], "traffic_vph":p["traffic_vph"],
                                     "counters":p["traffic_counter_count"]} for p in properties.values()]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true")
    args = parser.parse_args()
    if args.inspect:
        inspect()
    else:
        build()
