# Citizen crossing page

Share now generates a QR code for `/public/`: a lightweight, read-only page matching
òcio's sunlit interface. It refreshes every two seconds, using only
`GET /public/api/stats`. It does not fetch camera frames, trajectories or operational
APIs. The JSON download contains the same public data.

## What citizens can see

- Detected passages by class and direction, for today, the last seven calendar days
  (including today), and all time since this feature began collecting data.
- Hour-of-day traffic profiles for each period, their busiest observed hour, and a
  seven-day volume chart. These are observed totals, not an extrapolation to missing
  hours or a prediction of future traffic.
- Currently tracked road users, signal mode and pedestrian signal, with a fresh-frame
  status. Stale camera observations suppress live counts; stored history remains.
- Mean observed vehicle speed and mean pedestrian crossing duration for each period.
- Possible near-miss episodes, yielding rate and sample size, speeding flags,
  motionless-person/blocking-vehicle alerts, red-light flags, and close-passage flags
  (post-encroachment-time events). The last 20 safety notices are visible.
- A screening score after at least 20 vehicle passages and some camera coverage:
  `100 * exp(-4 * weighted / max(20, vehicle_passages))`, where `weighted` is
  `3 * critical + 1.5 * serious + 0.5 * potential + non_yielding`. It uses the selected
  period's data. It is an indicator derived from detections, not a crash probability,
  a certified safety rating, or proof that a crossing is safe. No accident detector
  has been added. Existing detector precision/recall limitations still apply.

Counts represent journeys, not unique people or vehicles. Returning across the zebra
counts as another passage. E-scooters classified from fast person tracks remain in
the bicycle group, as agreed by the team.

## Persistence and timing

The defaults are:

```yaml
public:
  enabled: true
  stats_dir: data/stats
  url: null
  demo: null
```

Real-camera/network sources store `data/stats/<hash-of-node-id>.sqlite3`, separately
from run logs. Preserve this directory during updates and keep the node ID stable.
SQLite uses WAL transactions; writes run on a dedicated worker, not the vision loop.
The operator's Reset button resets session counters without clearing public history.
Shutdown drains queued writes. Abrupt power loss can lose the newest unflushed writes;
physical power-loss durability and board overhead have not been measured.

Storage contains daily/hourly aggregates, small lifetime/hour-of-day rollups, and at
most 50 anonymous safety notices. It contains no images, bounding boxes or personal
trajectories. Temporary track IDs are kept only in memory for counting corrections
and removed on track retirement. Corrections update the original hour/date; conflict
severity escalation updates one episode instead of adding another incident.

Hours and calendar days use the board's OS timezone. Set the correct timezone and
clock before collecting a deployment's history (e.g. Europe/Rome in Turin), and keep
that timezone stable. Coverage sums fresh-frame intervals; it excludes camera stalls
and shutdown gaps. Zero observed coverage is displayed as a gap. No older JSONL logs
are imported automatically.

Simulation, rendered simulation and video replay use a separate database inside that
run's directory, or memory when run logging is disabled. Their timestamps follow the
source timeline anchored at startup, and the page has a demonstration banner. They
do not update the deployment's lifetime totals. For a simulated MJPEG network input,
explicitly set `public.demo=true`, since the receiver cannot infer the stream's origin.

### Photoreal month of mock history

The live photoreal launcher `tools/sim_run.py` enables `public.mock_month=true` by
default. Each new run generates a calendar month of history for the configured
crosswalk, starting at the same local time one month before startup and ending at
startup (for example, 11 September to 11 October 2026). Month-end dates are clamped
to the preceding month's last day. The first and last hours/days are partial.

The deterministic synthetic model includes weekday commuting peaks, quieter
weekends, day-to-day variation, changes in directional balance, speeds, crossing
times, yielding opportunities, speeding flags, rare close encounters, and small
coverage gaps. Volumes are illustrative urban-crossing assumptions, not fitted to
real traffic. E-scooter riders stay in the bicycle group; no separate mock
micromobility is invented. Speeds and crossing durations use this crossing's speed
limit and length. Generated notices retain the same storage limits as live notices.

The public page and JSON identify the history as synthetic, include its exact date
range, and show a full-month daily chart. Today's/weekly/lifetime totals and hourly
profiles include the appropriate generated history plus subsequent observations
from the photoreal run. Session counters, detector inputs, ground truth, safety
decisions and signal actuation receive no fabricated events.

Seeding runs before the statistics worker starts, once per empty demo database;
reopening the same run cannot duplicate it. It requires both `source.type=render`
and isolated demo storage. Camera, network, video replay, fast simulator and the
default evaluation path do not seed history, even if a real-source configuration
accidentally enables this option. Disable it for a photoreal session with
`--set public.mock_month=false`. `public.enabled=false` also disables collection
and seeding.

If statistics initialization/writes fail, vision continues and the public page reports
that statistics are unavailable. Restore storage and restart the node. Missed events
are not silently reconstructed or assumed to be zero traffic.

## Printed QR codes and city access

The clickable Share link opens `/public/` on the dashboard's current origin in the
same tab. The QR destination is shown separately when it differs from that link.
With `public.url=null`, a server listening on all interfaces uses the node's LAN
address and port for its QR. This works for phones on the same reachable network.
A server bound to localhost or a specific interface instead uses the request's
address; a localhost QR is only usable on that computer. For cellular access and
permanent printed codes, configure the full stable HTTPS address of this crossing's gateway:

```yaml
node:
  id: turin-crossing-001
  name: Via Example crossing
public:
  url: https://crossing-001.city.example/public/
```

This feature supplies the page and data on each node. Public DNS, HTTPS, connectivity
and routing to a fleet of nodes are deployment infrastructure; none is provisioned
by this branch. Use a distinct stable hostname per crossing (or a gateway that rewrites
each crossing's path). Optional map coordinates come from `node.geo`.

Expose only `/public/` through the public gateway. The existing operational dashboard
and its control APIs have no authentication and must remain on a private interface.
For a gateway running on the board, bind `server.host=127.0.0.1` and use a private
SSH tunnel for operations. An illustrative nginx location inside an already-configured
HTTPS server is:

```nginx
location = /public { return 301 /public/; }
location ^~ /public/ {
    limit_except GET { deny all; }
    proxy_pass http://127.0.0.1:8000;
    proxy_read_timeout 10s;
}
location / { return 404; }
```

All page assets, fonts and JSON live under `/public/`; there are no runtime CDN
requests. Opening the optional map link is the only external navigation. The public
endpoint explicitly projects aggregate fields and rejects public POST requests;
it does not publish operational state or raw event/replay data.

## Local verification

```powershell
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m crosswalk --sim dangerous --port 8009 --set signal.mode=beacon --set server.host=127.0.0.1
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m pytest -q tests/test_public_stats.py
```

Open `http://localhost:8009/public/`, or use Share from the operator dashboard.
Tests cover restart persistence, reset independence, reclassification and duplicate
corrections, returning crossings, hourly/day boundaries, incomplete coverage, camera
stalls, severity escalation, notice retention, storage failures, source isolation,
public payload fields, asset access, public POST rejection, and configured QR URLs.

On 2026-10-11, **103 tests passed, 1 skipped** (the existing opt-in GPU test).
Chrome checks covered live updates, period selection, hourly profiles, the phone
layout without horizontal overflow, and Share's QR dialog. OpenCV decoded the QR
from the browser screenshot to the expected `/public/` address. No browser JavaScript
errors were observed. These are laptop checks; board cost, physical-phone scanning
and printed-code readability have not been measured. Existing counting and safety
validation figures have not been remeasured by this feature.

Share-link fix after the simulator/economics merges (2026-10-11): **147 tests passed,
1 skipped**. The new localhost regression failed before the fix, then passed by
following the advertised URL to the citizen page. The all-interface LAN behavior
and configured public URL are covered too. Chrome reproduced the old LAN link's
`ERR_CONNECTION_REFUSED`, then verified Share navigates in the same tab to live
statistics without a `public.url` override. JavaScript syntax and `git diff --check`
passed. Preview evidence: `runs/share-link-fixed.png` (ignored).

Photoreal mock-month/branding update (2026-10-11): **160 tests passed, 1 skipped**.
Tests cover calendar boundaries/leap years, source isolation, repeatability,
idempotence/restart, aggregate and direction consistency, partial-day coverage,
weekday/rush-hour patterns, and subsequent live events. The actual ONNX detector
and GPU photoreal renderer served a 31-date history from 11 September to 11 October.
Chrome verified the `òcio` title/branding, mock banner, full-month chart and weekly
selection; desktop and phone layouts had no horizontal overflow or JavaScript
errors. Preview screenshots: `runs/ocio-mock-month.png` and
`runs/ocio-mock-month-phone.png` (ignored). The temporary preview was stopped.
