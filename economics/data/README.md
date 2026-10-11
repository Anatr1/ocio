# Turin Planner Data

The checked-in JSON is processed public data, not fabricated crossing assets.

* `municipalities.geojson`: all 312 CMTO municipalities, ISTAT six-digit IDs,
  1 January 2026 official statistical boundaries, simplified for display after
  WGS84 UTM32N to longitude/latitude conversion. Point assignment uses the
  unsimplified original geometry.
* Population: definitive ISTAT continuous census, 31 December 2024, distributed
  by Regione Piemonte. Metropolitan total: 2,204,276. Turin: 853,196. Area and
  density fields in the regional workbook use 2021 surface areas.
* Commuting: 2019 resident daily work/study commuters from ISTAT, distributed by
  Regione Piemonte. These are people across all modes, not trips or pedestrian
  crossing arrivals.
* Zones: official 11 homogeneous zones. Source abbreviations are normalized.
  The Torino Nord zone is the eight municipalities remaining after matching
  the other ten zones; the source spokesperson listing omits Leini.
* `traffic_snapshot.json`: one actual 5T measured five-minute XML response.
  `flow` is vehicles/hour, not five-minute vehicle counts, as specified in the
  SIMONE protocol table 8. Zero-accuracy sensors and motorway/raccordo names
  are excluded from municipality local-road median benchmarks. This Saturday
  snapshot is not an annual traffic estimate or crossing-specific calibration.
* OpenStreetMap inventory, when available: `highway=crossing` nodes, with
  explicit `crossing=traffic_signals` or `crossing:signals=yes` signal tags.
  Nodes can describe separate lanes in one crossing complex. Mapping is
  incomplete; counts are not certified installation sites.

`manifest.json` records source URLs, reference years, acquisition timestamps,
hashes, attribution and caveats. ISTAT materials are CC BY 4.0; 5T data is IODL
2.0 in the aperTO municipal catalog. OpenStreetMap-derived data is ODbL 1.0
and must retain OpenStreetMap contributor attribution. Regional data is
publicly distributed ISTAT statistical data; retain both attributions.

Recreate from public sources (build-time dependencies only):

```powershell
.\.venv\Scripts\python.exe -m pip install pyshp shapely pyproj openpyxl xlrd
.\.venv\Scripts\python.exe tools/fetch_turin_data.py --osm
```

Cached raw downloads are intentionally not part of the runtime application.
`--refresh-traffic` replaces the snapshot, changing the scenario input vintage.
Without that flag the same raw bytes reproduce the same municipal values.
