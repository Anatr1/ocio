# Economic Input Provenance

Snapshot: 10 October 2026. Machine-readable assumptions and URLs live in `economics/data/costs.json`. The planner is a conditional, tax-inclusive planning appraisal, not a deployment quote, formal tax-corrected public CBA, validated city-wide traffic forecast, or GDP forecast.

## Hardware And Installation

The [Arduino EU store](https://store.arduino.cc/pages/uno-q) lists UNO Q 4GB at EUR82.90 and 2GB at EUR59.90 including VAT. The default uses 4GB. The official [45W PD supply](https://store.arduino.cc/products/usb-c-power-supply-45w) is EUR16.89 and [24-pin USB-C cable](https://store.arduino.cc/products/usb-c-cable-24-pin) EUR5.97 including VAT. Public product JSON independently returned these prices. Supply wattage is a capacity, not measured power draw.

The [Logitech C920s EU listing](https://www.logitech.com/de-at/shop/p/c920s-pro-hd-webcam) shows EUR99.99 list price and EUR59.99 sale price in its search-index snapshot. We budget the list price; Italian checkout is unconfirmed. The [Anker 341 Italian listing](https://www.ankeritaly.com/products/a8346) lists EUR39.99. Camera outdoor performance and hub/UNO Q compatibility still need testing.

Housing, mount, protection, cooling, and assembly are unquoted allowances. Hardware subtotal is EUR455.74. Existing-controller integration (EUR750), installation (6h x EUR60), calibration (3h x EUR70), commissioning (4h x EUR70), and traffic management (EUR150) add EUR1,750. With 20% contingency, provisional installed cost is **EUR2,646.89 per crossing**, with an editable EUR1,500-6,000 scenario range. This is not a statistical confidence interval.

Production routine maintenance now assumes 2h at EUR60: EUR120 delivery budget, or EUR150 final fee at 20% margin. The previous EUR60 annual replacement reserve has been removed; major replacements are separate. Fixed platform/engineering allowance is EUR50,000, not a subscription or selling price. Certification, controller access, civil works, new signals/poles, trenching, mains connection, major upgrades, and additional cameras can add substantial costs. Do not connect the prototype directly to road signal lamps: only a supplier-approved interface to an existing certified controller is within this cost scenario. No WAN charge is assumed for offline operation.

## Simplified Pilot Budget

The original installation build-up above is the **production reference**, not
the new default pilot price. `cost_profiles.json` and
`tools/build_cost_profiles.py` retain EUR455.74 hardware, but pilot installation
is 3h x EUR60, calibration 1h x EUR70, commissioning 1h x EUR70 and EUR50 consumables.
With 10% contingency the delivery allowance is EUR908.31. At 20% assumed gross
margin the sale price is EUR1,135.39 and annual service fee EUR100 (EUR80
delivery); shared setup is EUR2,000 for reuse of existing software.

These lower figures are **assumptions**, not supplier quotes or proven bulk
discounts. They require the site owner to supply pole, mains, permits and an
approved controller input. Civil works, new signals, lane closures, lift hire,
new controller interface and product certification are excluded. Outdoor
prototype performance still needs validation. Keep the production profile
for scenarios that do not meet these conditions.

## Traffic And Crossing Counts

The [5T city mobility statistics](https://www.muoversiatorino.it/it/numeri-mobilita/)
define mean flow as hourly vehicle transits averaged over urban network arcs.
It is estimated by the Supervisore mathematical model, informed by detector
measurements and travel surveys, not a direct count at every crossing. The
cached Friday 9 October 2026 profile has 08:00 maximum 564 veh/h/arc, published daily
mean 313, and 00:00-05:00 mean 53.333. Assuming two representative directions gives
**peak 1,128, medium 626, light 107 vehicles/hour**, rounded as documented in
`traffic_presets.json`. The midnight endpoint repeating hour0 is excluded.
This one-day profile is not an annual distribution or site-specific demand.

The city district polygons contain 13,424 OSM crossing nodes, 4,009 explicitly
signalized. Default crossing quantity is signalized nodes x 0.25 x coverage%,
rounded per district (1,004 at 100% across all eight). The 0.25 node-to-crossing
conversion is an **unverified grouping assumption**; map nodes are not unique
crossing complexes or approved retrofit sites. The old 258-site default was
population x 3/10,000, an arbitrary planning quota. The app now explains both
and defaults to the mapped estimate; neither substitutes for a field survey.

## Fuel And Fleet

[MIMIT daily Piemonte prices](https://www.mimit.gov.it/it/prezzo-medio-carburanti/regioni), updated 10 October 2026, give self-service petrol EUR2.028/L and diesel EUR2.252/L, excluding motorways. These are tax-inclusive user outlays, not net-tax economic resource costs or future forecasts.

The [ACI Autoritratto 2025 archive](https://aci.gov.it/app/uploads/2026/06/Autoritratto2025_Parco_veicolare.zip) contains `Circolante_Copert_2025.xlsx`, sheet `3 AV per Provincia`. TORINO fuel-total rows give 1,649,645 registered cars: 734,272 petrol, 431,568 diesel, 227,734 petrol-hybrid, 12,735 diesel-hybrid, 17,377 electric, plus gas-fuel/other vehicles. Registered stock is not crossing traffic. Petrol/diesel including hybrids cover 85.249% of stock. The simplified projection excludes LPG/CNG/EV/unknown idle-fuel benefits rather than assigning them petrol consumption. The petrol share within modelled liquid-fuel cars is 68.406%, producing a weighted fuel price of EUR2.09877/L. Applying stock weights to crossing flows remains an assumption.

[ORNL Transportation Energy Data Book 35](https://info.ornl.gov/sites/publications/Files/Pub67767.pdf) gives no-load idle examples of 0.16 USgal/h (2L petrol), 0.17 (2L diesel), 0.39 (4.6L petrol), citing Argonne's calculator accessed in 2014. Converted rates are 0.606, 0.644, 1.476 L/h. Default 0.8 L/h and 70% engine-on fraction are **assumptions**, not Turin measurements. They need on-site fleet/start-stop validation.

[EPA combustion factors](https://www.epa.gov/greenvehicles/greenhouse-gas-emissions-typical-passenger-vehicle), updated 3 June 2026, are 8,887 gCO2/USgal petrol and 10,180 diesel. Dividing by 3.785411784 L/USgal and applying the liquid-fuel stock weights gives 2.455613 kgCO2/L. This is a fuel-combustion proxy, not Italy-specific fuel chemistry or lifecycle CO2e.

## Electricity And Valuation

[ISPRA 430/2026](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/r430-2026-2.pdf), Table 2.2 on printed p65 (PDF p66), reports 2024 electricity-consumption factors of 207.6 gCO2/kWh for Piemonte and 192.6 for Italy. Use the regional factor 0.2076 kg/kWh, including allocated imports/losses. Device demand 8W and marginal electricity tariff EUR0.30/kWh are provisional: the hardware document contains no measured power budget. At 8W continuously, each unit consumes 70.08 kWh/year, costs EUR21.02/year, and emits 14.55 kgCO2/year at the reference grid factor. Heating, additional lamps, and communications equipment are not included.

The [EU-commissioned 2019 external-cost Handbook](https://publications.europa.eu/resource/cellar/e021854b-a451-11e9-9d01-01aa75ed71a1.0001.01/DOC_1), Table 87 printed p256, gives Italy urban car time values of EUR12.8/person-hour for commuting/business and EUR5.9 for personal trips, in **2016 euros**. Section 5.3.2/Table 24 give historical short/medium-term carbon valuations 60/100/189 EUR2016/tCO2e. Planner defaults 10 EUR/hour and 100 EUR/t are editable 2026-money assumptions informed by these references, not official inflation-rebased estimates or credit prices. Pedestrian values are not separately calibrated. The [2021-2027 EC appraisal vademecum](https://ec.europa.eu/regional_policy/sources/guides/vademecum_2127/vademecum_2127_en.pdf) allows 3% real social discounting absent a national approach; this is the editable default, not a borrowing rate. Ten-year horizon is assumed.

## GDP Contribution Scenario

The [OECD national accounts definitions](https://www.oecd.org/en/data/datasets/gdp-and-non-financial-accounts.html)
and [Eurostat annual accounts metadata](https://ec.europa.eu/eurostat/cache/metadata/en/nama_10_gdp_esms.htm)
support the distinction between gross sales, domestic value added and GDP.
They do **not** supply the app's assumed conversion rates or prove that a
crossing intervention increases GDP. Machine-readable formulas, assumptions,
source boundaries and limitations are in `gdp_assumptions.json`.

Work value-added proxy = signed net person-hours x work share x productive
realization x EUR value added/hour. Spending value-added proxy = signed net
person-hours x spending share x EUR spending/hour x net-new non-overlapping
share x domestic value-added share. The two time shares cannot exceed 100%.
Summing contributions assumes distinct production effects; additionality must
remove shifted spending, household budget substitution and overlap with work
output. Domestic value added can occur outside Turin and excludes net taxes
on products. No multipliers or percent-growth estimate is used. All numerical
conversion assumptions are unmeasured; net-new spending defaults to zero.
This signed proxy is reported separately and never added to social NPV.

## Maintenance And Replacement

The Settings maintenance field is the final annual charge per crossing.
Defaults are EUR100 pilot and EUR150 production, excluding electricity and
major device replacements. The user requested a 10% cumulative replacement
budget over 10 years: each year budgets 1% of original equipped units at the
entered installed prototype price. Expected fractional counts are budgeting
values, not fractional physical devices. Total replacements = units x 10%;
total replacement cost = that count x installed price. This is a scenario
assumption, not a measured failure rate. Costs enter every year's discounted
cash flow; no additional major-device reserve remains in routine maintenance.

## Claim Boundaries

Time value, user fuel outlay, and social carbon shadow value are different from municipal budget savings. A social payback is not a municipal cash payback. Avoid adding productivity potential to time-value benefits: that double-counts the same saved time. GDP change cannot be causally inferred from this crossing simulator. No safety efficacy is inferred from simulated conflicts, and safety monetization should remain zero until supported by intervention evidence. Net CO2 accounts only for modelled idling minus device electricity; embodied hardware, fuel upstream emissions, acceleration/restart, routing, electric-vehicle accessory demand, NOx/PM, and induced travel are excluded.
