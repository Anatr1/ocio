/* Citizen view: only anonymous aggregates from the read-only public endpoint. */
"use strict";
const $ = (id) => document.getElementById(id);
const kinds = ["pedestrian", "bicycle", "vehicle", "micromobility"];
const labels = { pedestrian: "Walking", bicycle: "Riding", vehicle: "Vehicles", micromobility: "Other micromobility" };
const number = new Intl.NumberFormat(document.documentElement.lang);
let period = "lifetime", payload = null, inFlight = false;
const fmt = (v) => v === null || v === undefined ? "—" : number.format(v);
const set = (id, text) => { $(id).textContent = text; };

function connection(text, stale) {
  set("connection", text);
  $("connection").classList.toggle("stale", stale);
}

function renderLive(d) {
  const live = d.live, visible = live.visible;
  connection(live.healthy ? "Live observations" : "Monitoring paused", !live.healthy);
  set("live-total", live.healthy && visible ? fmt(kinds.reduce((n, k) => n + visible[k], 0)) : "—");
  set("live-breakdown", live.healthy && visible ? `${fmt(visible.pedestrian)} walking · ${fmt(visible.bicycle + visible.micromobility)} riding · ${fmt(visible.vehicle)} vehicles` : "Fresh camera observations are unavailable");
  const modes = { adaptive: "Adaptive signal", fixed: "Fixed-time signal", beacon: "Warning beacon" };
  const mode = modes[live.signal.mode] || "Crossing monitor";
  set("signal-label", !live.healthy ? "Live status unavailable" : live.signal.mode === "beacon" ? mode : `${mode} · pedestrian ${live.signal.ped || "signal"}`);
  const last = live.last_frame_at ? new Date(live.last_frame_at * 1000).toLocaleTimeString() : "not yet received";
  set("last-updated", `Last camera update: ${last} · refreshes every 2 seconds`);
}

function renderPeriods(s) {
  const data = s[period];
  for (const k of kinds) set(`total-${k}`, fmt(data.counts[k]));
  const names = { today: "Today", week: "Past 7 days", lifetime: "All time" };
  const duration = data.observed_hours >= 1 ? Math.round(data.observed_hours * 10) / 10 : Math.round(data.observed_seconds / 60);
  const unit = data.observed_hours >= 1 ? "hour" : "minute";
  const coverage = `${fmt(duration)} ${unit}${duration === 1 ? "" : "s"}`;
  set("coverage", `${names[period]} · ${fmt(data.total)} detected passages · ${coverage} of camera coverage. Monitoring began ${s.since_local.slice(0, 10)}.`);
  set("safety-score", fmt(data.safety_score));
  set("score-detail", data.safety_score === null ? "Shown after at least 20 vehicle passages and fresh camera coverage." : "Based on flagged conflicts and observed yielding, relative to vehicle passages.");
  const nm = data.near_misses;
  set("near-miss-total", fmt(Object.values(nm).reduce((a, b) => a + b, 0)));
  set("near-miss-detail", `${fmt(nm.critical)} critical · ${fmt(nm.serious)} serious · ${fmt(nm.potential)} potential`);
  set("yield-rate", data.yield_rate === null ? "—" : `${Math.round(data.yield_rate * 100)}%`);
  set("yield-detail", `${fmt(data.yield_observations)} observed yielding opportunities`);
  set("speeding-total", fmt(data.speeding_flags));
  set("speeding-detail", `Above ${fmt(payload.speed_limit_kmh + 5)} km/h (limit + 5 km/h tolerance)`);
  set("alert-total", fmt(data.alerts));
  set("red-total", fmt(data.red_light_flags));
  set("pet-total", fmt(data.pet_flags));
  set("mean-speed", data.vehicle_mean_kmh === null ? "—" : `${fmt(data.vehicle_mean_kmh)} km/h`);
  set("mean-crossing", data.ped_mean_crossing_s === null ? "—" : `${fmt(data.ped_mean_crossing_s)} s`);
  const list = $("directions");
  list.replaceChildren();
  for (const k of kinds) {
    const row = document.createElement("div"); row.className = "direction-row";
    const name = document.createElement("strong"); name.textContent = labels[k];
    const detail = document.createElement("span");
    const entries = Object.entries(data.directions[k]);
    detail.textContent = entries.length ? entries.map(([dir, n]) => `${payload.direction_names[dir] || dir}: ${fmt(n)}`).join(" · ") : "No directional passages observed";
    row.append(name, detail); list.append(row);
  }
}

function renderCharts(s) {
  const hours = s.hourly_profiles[period];
  const periodName = { today: "today", week: "the last seven days", lifetime: "all time" }[period];
  const chart = $("hour-chart"); chart.replaceChildren();
  chart.setAttribute("aria-label", `Detected passages by hour for ${periodName}`);
  const max = Math.max(1, ...hours.map((h) => h.total));
  for (const h of hours) {
    const col = document.createElement("div");
    col.className = `hour-column${h.observed_hours === 0 && !h.total ? " unobserved" : ""}`;
    col.tabIndex = 0;
    const description = `${String(h.hour).padStart(2, "0")}:00 · ${h.total} detected passages · ${h.observed_hours} hours observed. ${kinds.map((k) => `${labels[k]}: ${h.counts[k]}`).join(", ")}`;
    col.title = description; col.setAttribute("aria-label", description);
    for (const k of kinds) {
      const bar = document.createElement("span"); bar.className = k;
      bar.style.height = `${h.counts[k] / max * 100}%`; col.append(bar);
    }
    chart.append(col);
  }
  const best = hours.reduce((a, b) => b.total > a.total ? b : a);
  const peak = best.total ? best : null;
  set("peak-hour", peak ? `${String(peak.hour).padStart(2, "0")}:00–${String(peak.hour + 1).padStart(2, "0")}:00` : "Still getting to know this street");
  set("peak-detail", peak ? `${fmt(peak.total)} passages · busiest hour for ${periodName}` : "No detected passages in this period yet");
  set("hour-note", `Observed volume for ${periodName}, ${s.timezone}. Partial hours are included; hatched hours have no coverage.`);
  const days = $("day-chart"); days.replaceChildren();
  const monthly = !!s.mock_history && s.daily_history?.length;
  const series = monthly ? s.daily_history : s.daily;
  days.classList.toggle("month-chart", !!monthly);
  days.style.setProperty("--days", series.length);
  set("daily-heading", monthly ? "The past month · mock history" : "The past seven days");
  days.setAttribute("aria-label", monthly ? "Generated daily passages over the past calendar month" : "Detected passages over the last seven days");
  const dailyMax = Math.max(1, ...series.map((d) => d.total));
  for (const [index, d] of series.entries()) {
    const col = document.createElement("div"); col.className = `day-column${!d.observed_hours && !d.total ? " unobserved" : ""}`;
    col.tabIndex = 0;
    col.title = `${d.date} · ${d.total} passages · ${d.observed_hours} hours observed`; col.setAttribute("aria-label", col.title);
    const n = document.createElement("strong"); n.textContent = d.observed_hours || d.total ? fmt(d.total) : "—";
    const track = document.createElement("i"), bar = document.createElement("span");
    bar.style.height = `${d.total / dailyMax * 100}%`; track.append(bar);
    const label = document.createElement("span");
    label.textContent = !monthly || index % 5 === 0 || index === series.length - 1 ? d.date.slice(5).replace("-", "/") : "";
    col.append(n, track, label); days.append(col);
  }
}

function renderNotices(s) {
  const list = $("recent-notices"); list.replaceChildren();
  const details = { person_motionless_on_crosswalk: "Person stationary on the crossing", vehicle_blocking_crosswalk: "Vehicle blocking the crossing", pedestrian_on_red: "Possible pedestrian red-light violation", vehicle_on_red: "Possible vehicle red-light violation" };
  for (const e of s.recent_notices) {
    const li = document.createElement("li"); li.className = e.level || "";
    const text = document.createElement("span");
    text.textContent = e.type === "conflict" ? `Possible near-miss · ${e.level}${e.ttc !== null ? ` · TTC ${e.ttc}s` : ""}` : e.type === "pet" ? `Close passage · gap ${e.pet}s` : details[e.detail] || "Crossing safety notice";
    const at = document.createElement("time"); at.dateTime = e.local_time;
    at.textContent = e.local_time.slice(5, 16).replace("T", " "); at.title = `${e.local_time} · node local time`;
    li.append(text, at); list.append(li);
  }
  if (!s.recent_notices.length) {
    const li = document.createElement("li"); li.className = "empty-notice";
    li.textContent = "No safety notices recorded so far."; list.append(li);
  }
}

function render(d) {
  payload = d;
  document.title = `òcio · ${d.node.name}`;
  set("crossing-name", d.node.name); set("node-id", `Crossing ${d.node.id}`);
  $("demo-banner").hidden = d.data_mode !== "demo";
  const mock = d.statistics?.mock_history;
  set("demo-banner", mock ? `Mock history · ${mock.start_local.slice(0, 10)} to ${mock.end_local.slice(0, 10)}. Generated urban traffic, not measured data. Live activity comes from this photoreal simulation.` : "Demonstration data · this is a simulated or replayed crossing. Statistics belong to this run.");
  const geo = d.node.geo;
  if (geo && Number.isFinite(geo.lat) && Number.isFinite(geo.lon) && Math.abs(geo.lat) <= 90 && Math.abs(geo.lon) <= 180) {
    $("map-link").hidden = false;
    $("map-link").href = `https://www.openstreetmap.org/?mlat=${geo.lat}&mlon=${geo.lon}#map=18/${geo.lat}/${geo.lon}`;
  }
  renderLive(d);
  const error = !d.statistics_available ? "Historical statistics are unavailable. Monitoring continues; totals may be incomplete until storage is restored." : !d.live.healthy ? "The camera is not sending fresh observations. Historical data remains available; live activity is paused." : !d.live.calibrated ? "Crossing calibration is missing. Counts and motion-based estimates may be unreliable." : "";
  $("error-banner").hidden = !error; set("error-banner", error);
  if (d.statistics_available && d.statistics) {
    renderPeriods(d.statistics); renderCharts(d.statistics); renderNotices(d.statistics);
  } else {
    for (const id of ["safety-score", "near-miss-total", "yield-rate", "speeding-total", "alert-total", "red-total", "pet-total", "peak-hour", "mean-speed", "mean-crossing", ...kinds.map((k) => `total-${k}`)]) set(id, "—");
    for (const id of ["hour-chart", "day-chart", "directions", "recent-notices"]) $(id).replaceChildren();
    set("coverage", "Statistics storage is unavailable.");
  }
}

for (const button of document.querySelectorAll("[data-period]")) button.addEventListener("click", () => {
  period = button.dataset.period;
  for (const b of document.querySelectorAll("[data-period]")) { b.classList.toggle("selected", b === button); b.setAttribute("aria-pressed", String(b === button)); }
  if (payload?.statistics_available) { renderPeriods(payload.statistics); renderCharts(payload.statistics); }
});

async function refresh() {
  if (inFlight || document.hidden) return;
  inFlight = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4000);
  try {
    const response = await fetch("api/stats", { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error("Crossing unavailable");
    render(await response.json());
  } catch (_) {
    connection("Connection lost", true);
    set("live-total", "—"); set("live-breakdown", "Unable to reach this crossing"); set("signal-label", "Live status unavailable");
    $("error-banner").hidden = false;
    set("error-banner", "Connection lost. Displayed historical data is from the last successful update. Retrying automatically.");
  } finally { clearTimeout(timeout); inFlight = false; }
}
refresh();
setInterval(refresh, 2000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
