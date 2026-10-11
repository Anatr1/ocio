# òcio Turin City Deployment Planner

## CO2 / Time Priority Update

The main-page priority toggle compares five vehicle minimum-green timings
(8, 15, 30, 45, 60 seconds) separately in four independent demand periods,
using identical four-seed arrivals. The 625 combinations plus baseline fallback
allow shorter greens in quiet periods instead of one timing all day. Both modes
require no extra aggregate road-user waiting. CO2 maximizes net idle-combustion
savings after device electricity; Time minimizes combined waiting among
CO2-neutral or better schedules. If both constraints cannot be met, the
least-emitting time-safe option is shown with an unmet-target warning. Baseline
fallback has zero time benefit but still incurs device electricity. Identical
mode results are labelled when both objectives share the best tested schedule.
This is in-sample screening, not a validated network optimum; period transitions
are not simulated and the daily profile is provisional. Safety timings are
unchanged; controller changes are confined to the planner's experiment.

The editable compact-car no-load idle assumption is now 0.62 L/engine-on hour,
not a measured Turin fleet average. Fleet and engine-on fractions are applied
once. Results show baseline/system yearly idle fuel across all installed
crossings, plus savings per crossing. Driving and restart fuel are excluded.
Model version: `isolated-queue-1.3`.

## Start

The webapp now covers **Torino city only**, divided into its eight official
circoscrizioni. Surrounding municipalities are not offered or accepted by the
running API. Metropolitan data remains in the repository as research material.

PowerShell, from the repository directory:

```powershell
Set-Location 'C:\Users\Enrico\Desktop\HackTurin\hackturin-task1'
.\.venv\Scripts\python.exe -u tools/economics_app.py --port 8020
```

Open http://127.0.0.1:8020. The camera simulator on port 8001 is independent.
Ctrl+C stops a foreground planner. The service binds only to loopback.

## User Workflow

Select districts on the map, through their checkboxes, or with the district
preset. Search accepts neighbourhood names as well as circoscrizione labels.
The default selection is all eight districts. The main page has district
selection, three traffic choices, a numeric deployment percentage (with a
synchronized slider), and Run. Other inputs are on the separate Settings view;
source definitions and derivations are on Data & methodology.

At the top of Settings, "Installed prototype cost / crossing" is the final
all-in price used for capital costs. Entering EUR300 makes crossing capital
EUR300, not EUR375. The UI converts it to the model's legacy delivery-budget
field using the assumed margin; margin changes do not increase this entered
price. Supplier delivery cost remains an estimate, not a measured cost.
"Shared setup" is one-off deployment-wide commissioning/configuration and is
added once when at least one crossing is equipped. It is editable and can be
zero when there is no separate shared expense; it excludes the separate
supplier product-development budget. Capital = crossings x entered price +
shared setup. "Annual maintenance / crossing" is also a final charge, not a
delivery budget to be marked up. Supplier cost is reverse-derived using the
assumed margin; changing margin does not increase either entered charge.
Electricity and major device replacement are separate.

"Crossings" means estimated locations equipped with one system; older export
fields call them `sites`. Default inventory uses 4,009 mapped signalized nodes
x an explicitly provisional 0.25 crossings/node factor. Coverage is applied
before rounding each district, producing **1,004 estimated crossings at 100%**
city coverage. This is NOT a surveyed crossing count or verified compatible
controller inventory. Percentage covers estimated signalized crossings in
selected districts, not every painted crosswalk. The population quota field
and inventory-mode selector have been removed from the webapp; it always uses
mapped signalized nodes. Legacy population-quota parameters and explicit
count overrides remain supported by the API only for compatibility.

Run returns social time/fuel/carbon value, municipal investment and operating
cost, operational CO2, social NPV/BCR/payback, supplier contribution and
break-even scale, sensitivity bands, four charts, and a district table.
Compare scenarios in browser-local storage; download CSV or full JSON. Old
metropolitan comparisons use a separate storage key and are not shown here.

## Real Inputs

- Official municipal Geoportale eight-district boundaries, not invented map cells.
- Same-source 31 December 2025 municipal anagrafe population: 858,874 residents
  in the mapped districts. The separate 4,375 virtual-address registrations
  are not allocated to a district. Registry total 863,249 differs from ISTAT
  census population; do not mix these denominators.
- OpenStreetMap: 13,424 crossing nodes inside those district polygons, of which
  4,009 explicitly signalized. These are not certified installation sites;
  several nodes can share a crossing or junction controller. 56 edge nodes
  were excluded rather than assigned arbitrarily across differing boundaries.
- 5T: a real Saturday five-minute traffic snapshot, 19 valid local-road
  directional counters in five districts. Uncovered districts remain null.
  This remains contextual provenance, not the selected traffic-rate input.
- Three traffic presets come from the 5T Supervisore city network-arc profile
  for Friday 9 October 2026: peak 1,128 veh/h (2 x 08:00 maximum 564), medium 626
  (2 x published daily mean 313), light 107 (rounded 2 x mean 00:00-05:00).
  These are two-direction crossing proxies, not measured per-crossing rates.
  Source series, date, transformation and caveats are in `traffic_presets.json`.
  Medium is the default; a single Friday is not an annual distribution.
- Dated hardware prices, ACI provincial registered fleet, MIMIT fuel prices,
  ISPRA regional electricity factor, and appraisal references are recorded in
  `economics/data/costs.json` and `docs/ECONOMICS_SOURCES.md`.

Source URLs, dates, licences, hashes and limitations are bundled in
`economics/data/districts_manifest.json` and included in the JSON export.
The app works offline; only the optional road basemap requires internet.

## Cost Basis

The sourced hardware plus outdoor allowances remain EUR455.74; no bulk
discount or lower component quote was invented. `cost_profiles.json` provides
two profiles with reproducible build-up via `tools/build_cost_profiles.py`:

- Default **conditional pilot retrofit**: installation 3h x EUR60, calibration 1h
  x EUR70, commissioning 1h x EUR70 and EUR50 consumables. Hardware plus allowances
  and 10% contingency give EUR908.31 delivery budget; at 20% gross margin the
  estimated sale price is **EUR1,135.39/crossing**. Shared setup EUR2,000; annual
  service delivery EUR80 -> EUR100 fee; electricity additional. Site owner must
  supply an existing pole, power, permits and approved fail-safe controller
  input. No civil works, lane closures, lift hire, new interface, new lamps or
  product certification. This is not unconditional city-rollout pricing.
- **Production rollout** retains the previous full engineering allowances:
  EUR2,646.89 delivery, EUR3,308.61 estimated sale price, EUR150 annual service
  fee and EUR50,000 shared commissioning/platform allowance. Still not a quote.

A separate supplier setup budget of EUR100,000 and 10% supplier discount are hypothetical
business-case inputs, not measured R&D or certification costs. Supplier
contribution is not audited profit. Sales, insurance, taxes, financing, major
certification, new signals, trenching and civil works are not fully budgeted.
Routine maintenance excludes major device replacement. The old production
EUR60/year replacement reserve was removed: production maintenance delivery
is EUR120/year (two labour hours) -> EUR150 final charge at the assumed margin.
Pilot maintenance retains EUR80 delivery -> EUR100 final charge, including
minor consumables but not major devices. Both charges are editable.

The requested lifecycle default replaces **10% of equipped devices cumulatively
across ten years**, spread uniformly as 1% of the original fleet each year.
Each replacement costs the entered installed prototype price. Expected unit
counts can be fractional for budgeting; no annual rounding artificially inflates
small deployments. Replacement appears separately in every year's cash flow,
annual social net, discounted costs/NPV, BCR/payback and scale comparisons.
It is not 10% of devices every year, nor an extra reserve inside maintenance.
For other horizons the same total fraction is spread across the chosen years.
The API retains `replacement_schedule=one_off` plus `replacement_year` for
legacy single-year scenarios; the webapp always selects `spread`.

## Model Boundary

`economics/simulation.py` reuses `crosswalk.signal.SignalController` without
changing production code. Each policy sees identical Poisson vehicle and
pedestrian arrivals, walking speeds, and visibility draws. Two isolated lanes
discharge at an assumed 1,800 vehicles/hour/lane. Four demand periods have
5-minute warm-up and 30-minute measured queue integrals, repeated across four
seeds. Residual queue delay is included. All estimated city crossings share
the selected traffic proxy. A provisional four-period daily profile scales
that proxy; it is not an observed annual distribution.

Settings glossary: `fixed_green_s` is vehicle-green duration in the fixed-cycle
comparator only (default 20s), not an òcio threshold. `button_delay_s` is the
assumed interval from pedestrian arrival to pressing the fallback button
(default 8s), not controller actuation latency. Neither is a surveyed Turin
signal setting. Both policies share the fallback; vision can request earlier.

This is **not a calibrated city network simulation**. There is no road routing,
intersection coordination, measured daily pedestrian demand, detector-frame
processing, acceleration-resolved emissions, or induced-demand model. The
push-button baseline uses the same adaptive controller with delayed manual
calls; this is an assumed comparator, not a survey of Turin controllers.

Time value and fuel savings belong to society/road users, not municipal cash
income. Causal GDP growth remains unidentified. A separate conditional
gross-value-added proxy (`gdp_scenario_eur`) uses signed net road-user hours:

- Work contribution = hours x work allocation x output realization x value
  added per productive hour. The latter is not a wage or gross business revenue.
- Spending contribution = hours x spending allocation x potential spending/hour
  x net-new non-overlapping share x domestic value-added share. Net-new share
  must exclude purchases shifted from elsewhere and output already counted in
  the work channel. Time allocation alone does not prove independent effects.
- Work + spending shares cannot exceed 100%; the remainder has no GDP contribution.
  Default work 15%, realization 25%, EUR25/hour, spending 20%, EUR10/hour,
  domestic value-added 50% are illustrative, unmeasured assumptions. Net-new
  spending defaults to zero without intervention evidence. All are editable.

The proxy is not measured GDP growth, excludes net product taxes/multipliers,
and domestic output need not be in Turin. It is never added to social NPV.
Negative time changes remain negative contributions. Full JSON includes
`gdp_assumptions.json`; district CSV includes the two components and total.
The legacy `gdp_increase_eur` remains null to avoid claiming an identified
causal effect; `productivity_potential_eur` is retained for old export readers.
Safety benefit is zero without field-effect evidence.
CO2 can increase when earlier pedestrian requests add vehicle stops. Negative
results are retained, including fuel, time and NPV losses. Beacon-only installs
have no assumed causal traffic benefit but do incur costs and electricity.

Sensitivity p10-p90 is a scenario envelope, not an empirical confidence interval.
It mixes paired-seed variability with correlated effect +/-50%, delivery/service
cost +/-30%, time value +/-50%, and idling +/-30%. More sites do not magically
remove systematic uncertainty. Gross VAT-inclusive prices are a screening
convention, not a formal net-tax public investment CBA.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_economics.py -q
.\.venv\Scripts\python.exe tools/economics_smoke.py
```

Browser smoke uses installed Chrome, checks actual map/chart pixels, map and
district selection, all eight result rows, comparisons, JSON/CSV downloads,
zero-benefit beacon results, empty-selection guards, and 1440/390/320px layouts.
Screenshots and exported scenarios are in ignored `runs/economics-qa/`.
Full repository tests require localhost network permission and a writable
`--basetemp` below `runs/` on sandboxed Windows.

## Refresh Data

`tools/fetch_turin_data.py` reproduces the larger metropolitan source cache;
`tools/fetch_turin_districts.py` uses its OSM/traffic cache and fetches the city
boundaries/population. GIS/Excel libraries are acquisition-only dependencies;
normal webapp runtime needs only existing NumPy and project code.
Raw metropolitan downloads remain ignored under `economics/data/raw/`.
`tools/build_traffic_presets.py` refreshes the dated 5T primary hourly profile;
`--check` verifies the cached preset derivations without network access.

## Before A Funding Claim

Survey crossing complexes, existing control policies, legal integration and
installation prices. Collect representative weekday/weekend and seasonal
pedestrian/vehicle arrivals plus signal plans. Run paired calibrated crossing
experiments and a network model for corridor-wide claims. Measure actual
device power, detection timing, availability and stopped-engine behaviour.
Use a field pilot to establish efficacy before claiming avoided accidents,
citywide CO2 reduction, GDP increase or a guaranteed financial return.
