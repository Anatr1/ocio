import { GroundTruthLayer } from "./ghosts.js";
import { Twin } from "./twin.js";

const $ = (id) => document.getElementById(id);
const theme = getComputedStyle(document.documentElement);
const ink = (name) => theme.getPropertyValue(`--${name}`).trim();
if (new URLSearchParams(location.search).has("viewer")) document.body.classList.add("viewer"); // judges' phones
const twin = new Twin($("twin"));
const gtLayer = new GroundTruthLayer(twin);
let gtOn = false;
let config = null;
let lastCounts = {};
let feedFilter = "safety";
const events = [];
const replayable = new Set();

// ------------------------------------------------------------------------------------------ helpers
const fmt = (v, d = 0, unit = "") => (v === null || v === undefined || Number.isNaN(v) ? "–" : `${Number(v).toFixed(d)}${unit}`);
async function post(url, body = {}) {
  try {
    await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch (e) { console.warn(e); }
}

function toast(title, text, cls = "") {
  const el = document.createElement("div");
  el.className = "toast " + cls;
  el.innerHTML = `<b>${title}</b>${text}`;
  $("toasts").prepend(el);
  setTimeout(() => el.remove(), 6000);
  while ($("toasts").children.length > 4) $("toasts").lastChild.remove();
}

// ------------------------------------------------------------------------------------------ config
function applyConfig(cfg) {
  config = cfg;
  $("brand").textContent = (!cfg.node.brand || cfg.node.brand.toLowerCase() === "occhio") ? "\u00f2cio" : cfg.node.brand;
  $("node-name").textContent = `${cfg.node.name} · ${cfg.node.tagline || ""}`;
  const sim = cfg.source.type === "sim" || cfg.source.type === "render"; // render = photoreal simulator (L2)
  // be explicit: in the simulator no neural network runs (detections are synthesised from ground truth + noise)
  const fakeDet = cfg.detector.model === "simulated";
  $("p-model").textContent = fakeDet ? "simulated detector (GT + noise model, no NN)" : `${cfg.detector.model || cfg.detector.backend} @${cfg.detector.imgsz || ""}`;
  const od = document.querySelector(".chip.ondevice");
  od.textContent = sim ? (fakeDet ? "SIMULATION" : "SIMULATED SCENE · real NN") : "100% on-device";
  od.classList.toggle("simbadge", sim);
  document.body.classList.toggle("is-sim", sim);
  $("mode").value = cfg.signal.mode;
  document.querySelectorAll(".sim-only").forEach((b) => b.classList.toggle("hidden", !sim));
  twin.setScene(cfg);
  setTimeout(() => twin.refreshGround(), 4000);
}

// ------------------------------------------------------------------------------------------ widgets
function drawSpark(timeline) {
  const c = $("spark");
  const w = (c.width = c.clientWidth * devicePixelRatio), h = (c.height = 56 * devicePixelRatio);
  const g = c.getContext("2d");
  g.clearRect(0, 0, w, h);
  if (!timeline || !timeline.length) return;
  const keys = [["pedestrian", ink("ped")], ["bicycle", ink("bike")], ["micromobility", ink("micro")], ["vehicle", ink("veh")]];
  const n = Math.max(timeline.length, 10);
  const max = Math.max(4, ...timeline.map((b) => keys.reduce((s, [k]) => s + (b[k] || 0), 0)));
  const bw = w / n;
  timeline.forEach((b, i) => {
    let y = h;
    for (const [k, col] of keys) {
      const v = b[k] || 0;
      const bh = (v / max) * (h - 4);
      g.fillStyle = col;
      g.fillRect(i * bw + 1, y - bh, Math.max(1, bw - 2), bh);
      y -= bh;
    }
  });
  g.fillStyle = ink("muted");
  g.font = `${10 * devicePixelRatio}px sans-serif`;
  g.fillText("per minute", 4, 12 * devicePixelRatio);
}

function drawGauge(score) {
  const c = $("gauge");
  const g = c.getContext("2d");
  g.clearRect(0, 0, c.width, c.height);
  const cx = 60, cy = 64, r = 50;
  g.lineWidth = 10; g.lineCap = "round";
  g.strokeStyle = ink("line");
  g.beginPath(); g.arc(cx, cy, r, Math.PI, 2 * Math.PI); g.stroke();
  const v = Math.max(0, Math.min(100, score ?? 100)) / 100;
  g.strokeStyle = v > 0.75 ? ink("ok") : v > 0.5 ? ink("pot") : v > 0.25 ? ink("ser") : ink("crit");
  g.beginPath(); g.arc(cx, cy, r, Math.PI, Math.PI + Math.PI * v); g.stroke();
  g.fillStyle = ink("text"); g.font = "700 22px Manrope, Segoe UI, sans-serif"; g.textAlign = "center";
  g.fillText(score === undefined ? "–" : Math.round(score), cx, cy - 8);
}

function drawMatrix(m) {
  const c = $("matrix");
  const g = c.getContext("2d");
  g.fillStyle = "#27372e"; g.fillRect(0, 0, c.width, c.height);
  for (let r = 0; r < 8; r++) for (let col = 0; col < 13; col++) {
    const v = m ? m[r * 13 + col] || 0 : 0;
    g.fillStyle = v ? `rgba(255, ${80 + v * 10}, 40, ${0.25 + v / 7 * 0.75})` : "#405044";
    g.beginPath(); g.arc(8 + col * 11.6, 8 + r * 11.4, 4.2, 0, Math.PI * 2); g.fill();
  }
}

function setLamps(sig) {
  const veh = sig?.veh || "off", ped = sig?.ped || "off";
  const tv = $("tl-veh").children, tp = $("tl-ped").children;
  tv[0].className = "r" + (veh === "red" ? " on" : "");
  tv[1].className = "y" + (veh === "yellow" ? " on" : veh === "flash" || veh === "off" ? " on blink" : "");
  tv[2].className = "g" + (veh === "green" ? " on" : "");
  tp[0].className = "r" + (ped === "red" ? " on" : "");
  tp[1].className = "g" + (ped === "green" ? " on" : ped === "flash" ? " on blink" : "");
  const names = { veh_green: "Vehicles: green", veh_yellow: "Vehicles: amber", all_red_1: "All red", ped_green: "Pedestrians: walk",
    ped_clear: "Pedestrians: clearance", all_red_2: "All red" };
  let txt = sig?.mode === "beacon" ? "<b>Unsignalised zebra</b> · warning beacon driven by the camera" :
    `<b>${names[sig?.state] || "–"}</b> ${fmt(sig?.t_in_state, 0, " s")}` + (sig?.demand ? " · pedestrian waiting" : "");
  if (sig?.extension_s > 0) txt += ` · <span class="ser">Green Man+ +${sig.extension_s} s</span>`;
  if (sig?.mean_ped_wait_s !== null && sig?.mean_ped_wait_s !== undefined) txt += ` · avg wait ${sig.mean_ped_wait_s} s`;
  $("sig-text").innerHTML = txt;
}

function renderDirections(dirs, names) {
  const map = [["pedestrian", "d-ped"], ["bicycle", "d-bike"], ["micromobility", "d-micro"], ["vehicle", "d-veh"]];
  for (const [k, id] of map) {
    const d = (dirs || {})[k] || {};
    const parts = Object.entries(d).filter(([, v]) => v > 0).map(([dk, v]) => `${(names || {})[dk] || dk} <b>${v}</b>`);
    $(id).innerHTML = parts.join("<br>");
  }
}

function renderApproach(a) {
  if (!a) return;
  const map = [["pedestrian", "a-ped", "as-ped"], ["cyclist", "a-cyc", "as-cyc"], ["vehicle", "a-veh", "as-veh"]];
  for (const [k, n, sub] of map) {
    const v = a[k] || {};
    const now = (v.approaching || 0) + (v.waiting || 0);
    $(n).textContent = now;
    $(n).parentElement.classList.toggle("hot", now > 0);
    const bits = [];
    if (v.waiting) bits.push(`${v.waiting} waiting`);
    if (v.next_eta !== null && v.next_eta !== undefined) bits.push(`next in ${v.next_eta.toFixed(1)} s`);
    if (v.crossing) bits.push(`${v.crossing} on crossing`);
    $(sub).innerHTML = (bits.join(" · ") || "none") + `<br>seen: ${v.seen ?? 0}`;
  }
}

let rulesShown = null;
function renderRules(s) {
  const rules = config?.rules || [];
  const mode = s.signal?.mode;
  const br = s.safety?.beacon_rule || {}, sr = s.signal?.rule || {};
  const active = new Set([br.id, mode === "beacon" ? null : sr.id].filter(Boolean));
  const key = [...active].join(",") + mode;
  if (key !== rulesShown) {
    rulesShown = key;
    const groups = [["beacon", "Driver warning beacon"], ["signal", mode === "beacon" ? "Traffic light (inactive in zebra mode)" : "Traffic light"], ["mcu", "Microcontroller (independent of Linux)"]];
    let h = "";
    for (const [g, title] of groups) {
      h += `<div class="rule-group">${title}</div>`;
      for (const r of rules.filter((r) => r.group === g)) {
        if (g === "signal" && ((mode === "fixed") !== (r.id === "SF"))) continue;
        const on = active.has(r.id);
        h += `<div class="rule-row ${on ? "on" : ""} ${on && r.id === "B2" ? "danger" : ""}" title="WHEN ${r.when}
THEN ${r.then}"><span class="id">${r.id}</span><span><b>${r.name}</b>${on ? `<br>WHEN ${r.when}<br>THEN ${r.then}` : ""}</span></div>`;
      }
    }
    $("rule-list").innerHTML = h;
  }
  const act = [];
  if (br.id) act.push(`<div class="why"><b>${br.id}</b> ${br.why || ""}</div>`);
  if (mode !== "beacon" && sr.id) act.push(`<div class="why"><b>${sr.id}</b> ${sr.why || ""}</div>`);
  $("rule-active").innerHTML = act.join("");
  const log = [...(s.signal?.history || []), ...(s.safety?.beacon_history || [])].sort((a, b) => b.t - a.t).slice(0, 8);
  $("rule-log").innerHTML = log.map((e) => `<li>t=${e.t.toFixed(1)}s <b>${e.id}</b> ${e.why || ""}</li>`).join("");
  const p = s.perf || {};
  $("rule-lat").textContent = `frame → lamp command ${fmt(p.decision_ms, 1)} ms` + (s.mcu?.rtt_ms ? ` · MCU ${s.mcu.rtt_ms} ms` : "");
}

function bump(id, cardCls) {
  const el = document.querySelector(`.count.${cardCls}`);
  el.classList.remove("bump"); void el.offsetWidth; el.classList.add("bump");
}

// ------------------------------------------------------------------------------------------ state
function applyState(s) {
  showRecording(s.record);
  twin.update(s);
  const c = s.counts?.counts || {};
  const map = [["pedestrian", "c-ped", "ped"], ["bicycle", "c-bike", "bike"], ["micromobility", "c-micro", "micro"], ["vehicle", "c-veh", "veh"]];
  for (const [k, id, cls] of map) {
    const v = c[k] || 0;
    if (lastCounts[k] !== undefined && v > lastCounts[k]) bump(id, cls);
    $(id).textContent = v;
  }
  lastCounts = c;
  const sub = s.counts?.sub_counts || {};
  $("sub-counts").innerHTML = Object.entries(sub).filter(([, v]) => v > 0).map(([k, v]) => `<span>${k} ${v}</span>`).join("");
  drawSpark(s.counts?.timeline);
  renderDirections(s.counts?.directions, s.counts?.direction_names);
  renderApproach(s.approach);
  renderRules(s);
  const sf = s.safety || {};
  drawGauge(sf.safety_score);
  $("nm-c").textContent = sf.near_miss?.critical ?? 0;
  $("nm-s").textContent = sf.near_miss?.serious ?? 0;
  $("nm-p").textContent = sf.near_miss?.potential ?? 0;
  $("yield").textContent = sf.yield_rate === null || sf.yield_rate === undefined ? "–" : `${Math.round(sf.yield_rate * 100)}% (${sf.yield.yielded}/${sf.yield.yielded + sf.yield.not_yielded})`;
  $("v85").textContent = fmt(s.counts?.vehicle_v85_kmh, 0, " km/h");
  $("pet").textContent = fmt(sf.pet_min, 1, " s");
  $("walk").textContent = fmt(s.counts?.ped_mean_speed, 2, " m/s");
  $("alerts").textContent = `${s.counts?.jaywalks ?? 0} · ${sf.alerts ?? 0}`;
  setLamps(s.signal);
  drawMatrix(s.mcu?.matrix);
  $("mcu-status").textContent = s.mcu?.connected ? `STM32 via arduino-router${s.mcu.rtt_ms ? " · " + s.mcu.rtt_ms + " ms" : ""}` : "virtual MCU (no board)";
  const p = s.perf || {};
  $("p-det").textContent = fmt(p.det_hz, 1);
  $("p-inf").textContent = fmt(p.infer_ms || p.det_ms, 0);
  $("p-duty").textContent = p.duty === undefined ? "–" : `${Math.round(p.duty * 100)}%`;
  $("p-temp").textContent = p.cpu_temp_c ? `${p.cpu_temp_c.toFixed(0)}°C` : (p.cpu_pct !== null && p.cpu_pct !== undefined ? `${p.cpu_pct}% cpu` : "–");
}

// ------------------------------------------------------------------------------------------ events
const ICON = { passage: "•", crossing: "🚶", vehicle_pass: "🚗", conflict: "⚠️", pet: "⏱️", yield: "🛑", violation: "🚨",
  alert: "🆘", jaywalk: "↯", ped_extension: "🧓", count_corrected: "↺", mode: "⚙️", reset: "⟲", ped_button: "🔘" };

function describe(e) {
  switch (e.type) {
    case "passage": return [`${e.cls || e.kind} passed ${e.dir_name || ""}`, `#${e.track}${e.corrected ? " (reclassified)" : ""} · total ${e.total}`];
    case "crossing": return [`${e.cls} crossed ${e.dir === "A>B" ? "A→B" : "B→A"}`, `${e.duration}s · ${e.speed} m/s${e.height ? " · " + e.height.toFixed(2) + " m tall" : ""}`];
    case "vehicle_pass": return [`${e.cls} ${e.speed_kmh} km/h${e.speeding ? " — speeding" : ""}`, `direction ${e.dir}`];
    case "conflict": return [`Near-miss (${e.level})`, `TTC ${e.ttc}s · ${e.veh_cls} ${e.veh_speed_kmh} km/h · needs ${e.drac ?? "?"} m/s² braking`];
    case "pet": return [`Post-encroachment ${e.pet}s (${e.level})`, `${e.first === "vehicle" ? "vehicle passed first" : e.first === "vru" ? "vehicle passed right behind" : "paths overlapped"}`];
    case "yield": return [e.outcome === "yielded" ? "Driver yielded" : "Driver did NOT yield", e.outcome === "yielded" ? `stopped ${e.dist_m} m before` : `${e.speed_kmh} km/h through an occupied crosswalk`];
    case "violation": return [e.violation.replaceAll("_", " "), e.speed_kmh ? `${e.speed_kmh} km/h` : ""];
    case "alert": return [e.alert.replaceAll("_", " "), "check the crosswalk"];
    case "jaywalk": return ["Crossing outside the zebra", `${e.offset_m} m away`];
    case "ped_extension": return ["Green Man+ extension", `+${e.seconds}s for ${e.crossing} slow pedestrian(s)`];
    case "count_corrected": return ["Count corrected", e.reason];
    default: return [e.type, ""];
  }
}

function severityOf(e) {
  if (e.type === "conflict" || e.type === "pet") return e.level === "critical" ? "crit" : e.level === "serious" ? "ser" : "";
  if (e.type === "yield" && e.outcome === "not_yielded") return "ser";
  if (e.type === "violation" || e.type === "alert") return "crit";
  return "";
}

function isSafety(e) { return ["conflict", "pet", "yield", "violation", "alert", "jaywalk", "ped_extension"].includes(e.type) || (e.type === "vehicle_pass" && e.speeding); }
function isCount(e) { return ["passage", "crossing", "vehicle_pass", "count_corrected"].includes(e.type); }

function renderFeed() {
  const ul = $("events");
  ul.innerHTML = "";
  const list = events.filter((e) => feedFilter === "all" || (feedFilter === "safety" ? isSafety(e) : isCount(e))).slice(0, 60);
  for (const e of list) {
    const li = document.createElement("li");
    li.className = severityOf(e);
    const [a, b] = describe(e);
    li.innerHTML = `<span>${ICON[e.type] || "·"}</span><span>${a}<span class="d">${b}</span></span><span class="t">${e.wall || ""}</span>`;
    if (replayable.has(e.id)) {
      const btn = document.createElement("button");
      btn.textContent = "3D replay";
      btn.onclick = () => openReplay(e.id, a);
      li.children[2].appendChild(document.createElement("br"));
      li.children[2].appendChild(btn);
    }
    ul.appendChild(li);
  }
}

function onEvent(e) {
  if (e.log_only) return;
  events.unshift(e);
  if (events.length > 300) events.pop();
  if (e.type === "conflict") {
    twin.flash(e.x, e.y, e.level);
    if (e.level !== "potential") toast(`⚠️ Near-miss · ${e.level}`, `TTC ${e.ttc}s · ${e.veh_cls} at ${e.veh_speed_kmh} km/h`, e.level === "critical" ? "" : "ser");
  } else if (e.type === "pet" && e.level === "critical") {
    twin.flash(e.x, e.y, "critical");
    toast("⏱️ Post-encroachment " + e.pet + " s", e.first === "vru" ? "a vehicle passed right behind a pedestrian"
      : e.first === "vehicle" ? "a pedestrian crossed right behind a vehicle" : "paths overlapped - collision course");
  } else if (e.type === "yield" && e.outcome === "not_yielded") {
    toast("🛑 Driver did not yield", `${e.speed_kmh} km/h through an occupied crosswalk`, "ser");
  } else if (e.type === "ped_extension") {
    toast("🧓 Green Man+", `clearance extended by ${e.seconds} s for a slow pedestrian`, "info");
  } else if (e.type === "alert" || e.type === "violation") {
    toast("🚨 " + (e.alert || e.violation).replaceAll("_", " "), "");
  }
  renderFeed();
}

// ------------------------------------------------------------------------------------------ replay
async function openReplay(id, title) {
  const r = await fetch(`/api/replay/${id}`);
  if (!r.ok) return toast("Replay not ready", "try again in a few seconds", "info");
  const clip = await r.json();
  if (!twin.startReplay(clip, parseFloat($("rp-speed").value))) return;
  $("replay-bar").classList.remove("hidden");
  $("rp-title").textContent = "REPLAY · " + title;
  $("rp-play").textContent = "❚❚";
}
twin.onReplayProgress = (f) => { $("rp-slider").value = Math.round(f * 1000); };
$("rp-exit").onclick = () => { twin.stopReplay(); $("replay-bar").classList.add("hidden"); };
$("rp-play").onclick = () => { if (twin.replay) { twin.replay.playing = !twin.replay.playing; $("rp-play").textContent = twin.replay.playing ? "❚❚" : "▶"; } };
$("rp-slider").oninput = (e) => twin.seekReplay(e.target.value / 1000);
$("rp-speed").onchange = (e) => { if (twin.replay) twin.replay.speed = parseFloat(e.target.value); };

// ------------------------------------------------------------------------------------------ controls
$("mode").onchange = (e) => post("/api/mode", { mode: e.target.value });
$("btn-share").onclick = async () => {
  // The browser already reached this origin. A phone's QR destination may use
  // a different LAN/gateway address that this browser cannot access.
  const pageURL = new URL("/public/", location.href).href;
  $("share-url").textContent = pageURL;
  $("share-url").href = pageURL;
  $("share-qr-url").textContent = "";
  $("share-qr-url").classList.add("hidden");
  try {
    const d = await (await fetch("/api/share")).json();
    if (!d.url) throw new Error(d.error || "Share unavailable");
    $("qr").innerHTML = d.svg || "<p class='muted'>(install segno on the node for the QR code)</p>";
    // Keep the generated QR artwork proportional inside the responsive card.
    const qr = $("qr").querySelector("svg");
    if (qr && !qr.hasAttribute("viewBox")) {
      qr.setAttribute("viewBox", `0 0 ${qr.width.baseVal.value} ${qr.height.baseVal.value}`);
    }
    if (d.url !== pageURL) {
      $("share-qr-url").textContent = `QR destination: ${d.url}`;
      $("share-qr-url").classList.remove("hidden");
    }
  } catch (e) {
    $("qr").textContent = e.message;
  }
  $("share-modal").classList.remove("hidden");
};
$("share-close").onclick = () => $("share-modal").classList.add("hidden");
$("share-modal").onclick = (e) => { if (e.target.id === "share-modal") $("share-modal").classList.add("hidden"); };
$("btn-call").onclick = () => post("/api/ped_request");
let recording = false;
$("btn-rec").onclick = () => {
  if (recording) return post("/api/record", { action: "stop" });
  const name = prompt("Recording name (e.g. scripted, traffic_day)", "traffic");
  if (name !== null) post("/api/record", { action: "start", name });
};
function showRecording(r) {
  recording = !!(r && r.recording);
  const b = $("btn-rec");
  const s = recording ? Math.floor(r.seconds || 0) : 0;
  b.textContent = recording ? `■ Stop ${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}` : "● Rec";
  b.style.borderColor = recording ? ink("crit") : "";
  b.style.color = recording ? ink("crit") : "";
}
$("btn-nearmiss").onclick = () => post("/api/scenario", { name: "near_miss" });
$("btn-elderly").onclick = () => post("/api/scenario", { name: "elderly" });
document.querySelectorAll("#views button").forEach((b) => (b.onclick = () => {
  document.querySelectorAll("#views button").forEach((x) => x.classList.toggle("on", x === b));
  twin.setView(b.dataset.view);
}));
let videoRetry = null;
function reconnectVideo() {
  clearTimeout(videoRetry);
  videoRetry = null;
  if (document.querySelector('#layers [data-layer="video"]').classList.contains("on")) {
    // A recovered SSE connection does not revive an interrupted MJPEG image.
    $("video").src = `/video.mjpg?reconnect=${Date.now()}`;
  }
}
$("video").onerror = () => {
  clearTimeout(videoRetry);
  if (document.querySelector('#layers [data-layer="video"]').classList.contains("on")) {
    videoRetry = setTimeout(reconnectVideo, 2000);
  }
};
document.querySelectorAll("#layers button").forEach((b) => (b.onclick = () => {
  b.classList.toggle("on");
  const on = b.classList.contains("on");
  if (b.dataset.layer === "gt") {
    gtOn = on;
    gtLayer.setVisible(on);
    $("gt-stats").classList.toggle("hidden", !on);
  } else if (b.dataset.layer === "video") {
    $("video").classList.toggle("hidden", !on);
    clearTimeout(videoRetry);
    videoRetry = null;
    if (on) reconnectVideo();
    else $("video").removeAttribute("src");
  } else twin.setLayer(b.dataset.layer, on);
}));
document.querySelectorAll("#feed-filter button").forEach((b) => (b.onclick = () => {
  document.querySelectorAll("#feed-filter button").forEach((x) => x.classList.toggle("on", x === b));
  feedFilter = b.dataset.f;
  renderFeed();
}));

// ------------------------------------------------------------------------------------------ stream
function connect() {
  const es = new EventSource("/api/stream");
  es.addEventListener("config", (m) => applyConfig(JSON.parse(m.data)));
  es.addEventListener("state", (m) => applyState(JSON.parse(m.data)));
  es.addEventListener("event", (m) => onEvent(JSON.parse(m.data)));
  es.addEventListener("gt", (m) => {
    gtLayer.update(JSON.parse(m.data));
    if (gtOn) $("gt-stats").innerHTML = gtLayer.statsHtml();
  });
  es.addEventListener("replay_ready", (m) => { const d = JSON.parse(m.data); replayable.add(d.id); renderFeed(); });
  es.onopen = () => {
    $("live").classList.add("on");
    $("live-text").textContent = document.body.classList.contains("is-sim") ? "SIMULATION" : "LIVE · on-device";
    reconnectVideo();
  };
  es.addEventListener("config", () => { if (document.body.classList.contains("is-sim")) $("live-text").textContent = "SIMULATION"; });
  es.onerror = () => { $("live").classList.remove("on"); $("live-text").textContent = "reconnecting…"; };
}

// Connect live controls before fetching optional historical data.
connect();
(async () => {
  try {
    const r = await fetch("/api/replays");
    if (r.ok) (await r.json()).forEach((x) => replayable.add(x.id));
    const ev = await fetch("/api/events?since=0");
    if (ev.ok) (await ev.json()).forEach((e) => { if (!e.log_only) events.unshift(e); });
    renderFeed();
  } catch (e) { /* offline */ }
})();
