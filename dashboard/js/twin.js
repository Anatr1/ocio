// 3D digital twin of the crosswalk, rebuilt live from anonymous trajectories (no video).
// World frame (metres): X along the road, Y across (curb A at -L/2, curb B at +L/2), Z up.
// three.js frame: x = X, y = Z (up), z = -Y.
import * as THREE from "three";
import { OrbitControls } from "three/addons/OrbitControls.js";

import { makeAgent, KIND_COLOR } from "./avatars.js";
import { buildStreetscape, streetSurfaces, daylightEnvironment } from "./streetscape.js";
export { makeAgent, KIND_COLOR };
const KIND_FROM_K = { p: "pedestrian", b: "bicycle", m: "micromobility", v: "vehicle" };
const LEVEL_COLOR = { critical: 0xff4d4f, serious: 0xff9f43, potential: 0xffd166 };

export const v3 = (X, Y, Z = 0) => new THREE.Vector3(X, Z, -Y);

function mat(color, opts = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0.05, ...opts });
}

function textSprite(text, color = "#e8ecf3") {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 64;
  const g = c.getContext("2d");
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  sp.scale.set(2.4, 0.6, 1);
  sp.renderOrder = 10;
  sp.userData.set = (t, col = color) => {
    if (sp.userData.text === t) return;
    sp.userData.text = t;
    g.clearRect(0, 0, 256, 64);
    g.font = "600 30px Inter, Segoe UI, sans-serif";
    const w = Math.min(250, g.measureText(t).width + 24);
    g.fillStyle = "rgba(11,14,19,0.78)";
    g.beginPath(); g.roundRect((256 - w) / 2, 8, w, 46, 12); g.fill();
    g.fillStyle = col; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(t, 128, 32);
    tex.needsUpdate = true;
  };
  sp.userData.set(text);
  return sp;
}

export class Twin {
  constructor(el) {
    this.el = el;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 0.98;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    el.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xcbdde2);
    this.scene.fog = new THREE.Fog(0xcbdde2, 65, 160);
    this.scene.environment = daylightEnvironment(this.renderer);
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 500);
    this.camera.position.set(-16, 13, 17);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.target.set(0, 0, 0);
    this.controls.maxPolarAngle = Math.PI * 0.495;
    this.scene.add(new THREE.HemisphereLight(0xe6f1f4, 0xb0a489, 1.35));
    const sun = new THREE.DirectionalLight(0xfff2db, 2.4);
    sun.position.set(-25, 40, 25);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    Object.assign(sun.shadow.camera, { left: -38, right: 38, top: 38, bottom: -38, near: 1, far: 110 });
    sun.shadow.camera.updateProjectionMatrix();
    sun.shadow.bias = -0.0003;
    sun.shadow.normalBias = 0.045;
    this.scene.add(sun);
    this.static = new THREE.Group();
    this.agentsG = new THREE.Group();
    this.trailsG = new THREE.Group();
    this.fxG = new THREE.Group();
    this.scene.add(this.static, this.agentsG, this.trailsG, this.fxG);
    this.agents = new Map();
    this.layers = { trails: true, labels: true, heat: false, ground: true, fov: true };
    this.view = "orbit";
    this.replay = null;
    this.clock = new THREE.Clock();
    this.lamps = null;
    this.beacons = [];
    this.flashes = [];
    this.conflictObjs = [];
    this.heat = null;
    new ResizeObserver(() => this.resize()).observe(el);
    this.resize();
    this.renderer.setAnimationLoop(() => this.frame());
  }

  resize() {
    const w = this.el.clientWidth || 800, h = this.el.clientHeight || 600;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  // ---------------------------------------------------------------- static scene
  setScene(cfg) {
    this.cfg = cfg;
    const sc = cfg.scene;
    // Release visual assets when calibration rebuilds the scene.
    const geometries = new Set(), materials = new Set(), textures = new Set();
    this.static.traverse((object) => {
      if (object.geometry) geometries.add(object.geometry);
      const surfaces = Array.isArray(object.material) ? object.material : [object.material];
      for (const surface of surfaces) if (surface) {
        materials.add(surface);
        if (surface.map) textures.add(surface.map);
      }
    });
    geometries.forEach((geometry) => geometry.dispose());
    materials.forEach((surface) => surface.dispose());
    textures.forEach((texture) => texture.dispose());
    this.static.clear();
    const W = sc.crosswalk.width, L = sc.crosswalk.length, D = sc.curb_depth, SW = sc.sidewalk_width;
    this.W = W; this.L = L;
    const far = 90;
    const plane = (x0, y0, x1, y1, color, z = 0, opts = {}) => {
      const geo = new THREE.PlaneGeometry(x1 - x0, y1 - y0);
      geo.rotateX(-Math.PI / 2);
      const m = new THREE.Mesh(geo, mat(color, opts));
      m.position.copy(v3((x0 + x1) / 2, (y0 + y1) / 2, z));
      m.receiveShadow = true;
      this.static.add(m);
      return m;
    };
    plane(-far * 2, -far * 2, far * 2, far * 2, 0xb8bcac, -0.02);
    const surfaces = streetSurfaces();
    plane(-far, -L / 2, far, L / 2, 0xffffff, 0.0, { map: surfaces.asphalt, roughness: 0.96 });
    const walkW = D + SW + 1.0;
    surfaces.paving.repeat.set(far, walkW / 2);
    for (const s of [-1, 1]) {
      const g = new THREE.BoxGeometry(far * 2, 0.15, walkW);
      const m = new THREE.Mesh(g, mat(0xffffff, { map: surfaces.paving, roughness: 0.94 }));
      m.receiveShadow = true;
      m.position.copy(v3(0, s * (L / 2 + walkW / 2), 0.075));
      this.static.add(m);
      const curb = new THREE.Mesh(new THREE.BoxGeometry(far * 2, 0.17, 0.2), mat(0xd8d5c3));
      curb.position.copy(v3(0, s * (L / 2 + 0.1), 0.085));
      this.static.add(curb);
    }
    // zebra stripes (parallel to the road axis)
    const st = sc.stripe || { width: 0.5, gap: 0.5 };
    for (let y = -L / 2 + 0.25; y + st.width <= L / 2 - 0.1; y += st.width + st.gap) {
      plane(-W / 2, y, W / 2, y + st.width, 0xe9ecef, 0.012, { roughness: 0.6 });
    }
    // lane markings + stop lines
    for (let x = -far; x < far; x += 6) {
      if (Math.abs(x) < W / 2 + 2.5 || Math.abs(x + 3) < W / 2 + 2.5) continue;
      plane(x, -0.07, x + 3, 0.07, 0xd9d9d9, 0.011);
    }
    for (const d of [-1, 1]) {
      const x = -d * (W / 2 + 1.5);
      const yl = -d * L / 4;
      plane(x - 0.25, yl - L / 4 + 0.2, x + 0.25, yl + L / 4 - 0.2, 0xd9d9d9, 0.011);
    }
    this.static.add(buildStreetscape(sc, walkW, far));
    this._buildSignal(sc);
    this._buildFov(sc);
    this._buildGround(cfg);
    this._buildHeat(sc);
    this.setView(this.view);
  }

  _buildSignal(sc) {
    const W = sc.crosswalk.width, L = sc.crosswalk.length;
    const cam = sc.camera;
    const pos = cam ? cam.position : [-W / 2 - 1.0, -L / 2 - 0.6, 4.5];
    const g = new THREE.Group();
    const poleH = Math.max(3.0, Math.min(pos[2], 8));
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.1, poleH, 10), mat(0x50555f, { metalness: 0.6 }));
    pole.position.copy(v3(pos[0], pos[1], poleH / 2));
    g.add(pole);
    // camera (the sensor) on top
    const camBox = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.18, 0.18), mat(0xe9ecef));
    camBox.position.copy(v3(pos[0], pos[1], poleH + 0.1));
    if (cam) {
      const f = cam.forward;
      camBox.lookAt(v3(pos[0] + f[0], pos[1] + f[1], poleH + 0.1 + f[2]));
      camBox.rotateY(Math.PI / 2);
    }
    g.add(camBox);
    // signal heads on a lower pole at the curb
    const sx = -W / 2 - 0.6, sy = -L / 2 - 0.5;
    const pole2 = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.08, 3.2, 10), mat(0x50555f, { metalness: 0.6 }));
    pole2.position.copy(v3(sx, sy, 1.6));
    g.add(pole2);
    const head = new THREE.Mesh(new THREE.BoxGeometry(0.32, 1.0, 0.32), mat(0x111317));
    head.position.copy(v3(sx, sy, 3.0));
    g.add(head);
    const lampGeo = new THREE.SphereGeometry(0.11, 14, 10);
    const mk = (c, z) => {
      const m = new THREE.Mesh(lampGeo, new THREE.MeshStandardMaterial({ color: 0x222222, emissive: c, emissiveIntensity: 0.0 }));
      m.position.copy(v3(sx - 0.17, sy, z));
      g.add(m);
      return m;
    };
    const pedHead = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.62, 0.3), mat(0x111317));
    pedHead.position.copy(v3(sx, sy + 0.17, 2.1));
    g.add(pedHead);
    const mkp = (c, z) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.22, 0.2), new THREE.MeshStandardMaterial({ color: 0x222222, emissive: c, emissiveIntensity: 0.0 }));
      m.position.copy(v3(sx, sy + 0.33, z));
      g.add(m);
      return m;
    };
    this.lamps = { r: mk(0xff2a2a, 3.3), y: mk(0xffc000, 3.0), g: mk(0x22ff66, 2.7), pr: mkp(0xff2a2a, 2.25), pg: mkp(0x22ff66, 1.95) };
    // warning beacons at both ends of the crosswalk
    this.beacons = [];
    for (const s of [-1, 1]) for (const x of [-W / 2 - 0.3, W / 2 + 0.3]) {
      const p = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 2.4, 8), mat(0x50555f));
      p.position.copy(v3(x, s * (L / 2 + 0.35), 1.2));
      const b = new THREE.Mesh(new THREE.SphereGeometry(0.16, 14, 10), new THREE.MeshStandardMaterial({ color: 0x3a2a00, emissive: 0xffb000, emissiveIntensity: 0 }));
      b.position.copy(v3(x, s * (L / 2 + 0.35), 2.5));
      g.add(p, b);
      this.beacons.push(b);
    }
    this.static.add(g);
  }

  _buildFov(sc) {
    this.fovG = new THREE.Group();
    this.static.add(this.fovG);
    if (!sc.H || !sc.camera) return;
    const H = sc.H, cam = sc.camera;
    const w = cam.width, h = cam.height;
    const toW = (u, v) => {
      const d = H[2][0] * u + H[2][1] * v + H[2][2];
      if (d <= 1e-9) return null;
      return [(H[0][0] * u + H[0][1] * v + H[0][2]) / d, (H[1][0] * u + H[1][1] * v + H[1][2]) / d];
    };
    const pts = [];
    const N = 24;
    const edge = (u0, v0, u1, v1) => {
      for (let i = 0; i <= N; i++) {
        const u = u0 + (u1 - u0) * i / N, v = v0 + (v1 - v0) * i / N;
        const p = toW(u, v);
        if (p && Math.hypot(p[0] - cam.position[0], p[1] - cam.position[1]) < 70) pts.push(p);
      }
    };
    edge(0, h, w, h); edge(w, h, w, 0); edge(w, 0, 0, 0); edge(0, 0, 0, h);
    if (pts.length < 3) return;
    const shape = new THREE.Shape(pts.map(([x, y]) => new THREE.Vector2(x, y)));
    const geo = new THREE.ShapeGeometry(shape);
    geo.rotateX(-Math.PI / 2);
    // ShapeGeometry is in (x, y); after rotateX(-90) y -> -z which matches z = -Y
    const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: 0x4ea8ff, transparent: true, opacity: 0.07, depthWrite: false }));
    m.position.y = 0.03;
    this.fovG.add(m);
    const line = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts.map(([x, y]) => v3(x, y, 0.04))),
      new THREE.LineBasicMaterial({ color: 0x4ea8ff, transparent: true, opacity: 0.5 }));
    this.fovG.add(line);
    const apex = v3(cam.position[0], cam.position[1], cam.position[2]);
    const corners = [pts[0], pts[N], pts[Math.min(pts.length - 1, 2 * N + 1)], pts[pts.length - 1]];
    const lp = [];
    corners.forEach((c) => { if (c) lp.push(apex, v3(c[0], c[1], 0.04)); });
    this.fovG.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(lp),
      new THREE.LineBasicMaterial({ color: 0x4ea8ff, transparent: true, opacity: 0.25 })));
    this.fovG.visible = this.layers.fov;
  }

  _buildGround(cfg) {
    if (this.groundMesh) { this.static.remove(this.groundMesh); this.groundMesh = null; }
    const b = cfg.bev;
    if (!b) return;
    const loader = new THREE.TextureLoader();
    loader.load(b.url + "?t=" + Date.now(), (tex) => {
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = 4;
      const geo = new THREE.PlaneGeometry(b.x1 - b.x0, b.y1 - b.y0);
      geo.rotateX(-Math.PI / 2);
      const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, opacity: 0.92 }));
      m.position.copy(v3((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, 0.16));
      m.renderOrder = 1;
      m.visible = this.layers.ground;
      this.groundMesh = m;
      this.static.add(m);
    }, undefined, () => { /* no background yet */ });
  }

  refreshGround() { if (this.cfg) this._buildGround(this.cfg); }

  _buildHeat(sc) {
    const b = sc.bounds;
    const c = document.createElement("canvas");
    c.width = 256; c.height = Math.max(32, Math.round(256 * (b[3] - b[1]) / (b[2] - b[0])));
    const grid = new Float32Array(c.width * c.height);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    const geo = new THREE.PlaneGeometry(b[2] - b[0], b[3] - b[1]);
    geo.rotateX(-Math.PI / 2);
    const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, opacity: 0.85 }));
    m.position.copy(v3((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, 0.2));
    m.renderOrder = 2;
    m.visible = this.layers.heat;
    this.static.add(m);
    this.heat = { c, grid, tex, mesh: m, b, max: 1, tDraw: 0 };
  }

  _heatAdd(X, Y, w = 1) {
    const h = this.heat;
    if (!h) return;
    const [x0, y0, x1, y1] = h.b;
    const gx = Math.round((X - x0) / (x1 - x0) * (h.c.width - 1));
    const gy = Math.round((y1 - Y) / (y1 - y0) * (h.c.height - 1));
    for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
      const x = gx + dx, y = gy + dy;
      if (x < 0 || y < 0 || x >= h.c.width || y >= h.c.height) continue;
      const v = (h.grid[y * h.c.width + x] += w * Math.exp(-(dx * dx + dy * dy) / 2.5));
      if (v > h.max) h.max = v;
    }
  }

  _heatDraw() {
    const h = this.heat;
    if (!h) return;
    const g = h.c.getContext("2d");
    const img = g.createImageData(h.c.width, h.c.height);
    for (let i = 0; i < h.grid.length; i++) {
      const v = Math.min(1, Math.sqrt(h.grid[i] / h.max));
      if (v < 0.02) { img.data[i * 4 + 3] = 0; continue; }
      // inferno-ish ramp
      const r = Math.min(255, 60 + 400 * v), gg = Math.max(0, Math.min(255, 300 * (v - 0.35))), bb = Math.max(0, 160 - 300 * v);
      img.data[i * 4] = r; img.data[i * 4 + 1] = gg; img.data[i * 4 + 2] = bb; img.data[i * 4 + 3] = 40 + 200 * v;
    }
    g.putImageData(img, 0, 0);
    h.tex.needsUpdate = true;
  }

  // ---------------------------------------------------------------- views & layers
  setView(v) {
    this.view = v;
    const sc = this.cfg?.scene;
    this.controls.autoRotate = v === "cinema";
    this.controls.autoRotateSpeed = 0.5;
    this.controls.enabled = v !== "sensor";
    this.camera.fov = 45;
    if (v === "top") {
      this.camera.position.set(0, 46, 0.01);
      this.controls.target.set(0, 0, 0);
    } else if (v === "sensor" && sc?.camera) {
      const c = sc.camera;
      this.camera.fov = c.vfov_deg;
      this.camera.position.copy(v3(c.position[0], c.position[1], c.position[2]));
      const f = c.forward;
      const tgt = v3(c.position[0] + f[0] * 10, c.position[1] + f[1] * 10, c.position[2] + f[2] * 10);
      this.controls.target.copy(tgt);
      this.camera.lookAt(tgt);
    } else if (v === "orbit" || v === "cinema") {
      this.camera.position.set(-16, 13, 17);
      this.controls.target.set(1.5, 0, -1);
    }
    this.camera.updateProjectionMatrix();
  }

  setLayer(name, on) {
    this.layers[name] = on;
    if (name === "trails") this.trailsG.visible = on;
    if (name === "ground" && this.groundMesh) this.groundMesh.visible = on;
    if (name === "heat" && this.heat) this.heat.mesh.visible = on;
    if (name === "fov" && this.fovG) this.fovG.visible = on;
    if (name === "labels") for (const a of this.agents.values()) a.label.visible = on;
  }

  // ---------------------------------------------------------------- live update
  update(state) {
    if (this.replay) return;
    this._applyTracks(state.tracks || [], false);
    this._applySignal(state.signal, state.safety);
    this._applyConflicts(state.safety?.active_conflicts || []);
  }

  _applyTracks(tracks, instant) {
    const now = performance.now() / 1000;
    const seen = new Set();
    for (const t of tracks) {
      seen.add(t.id);
      let a = this.agents.get(t.id);
      const kind = t.kind || KIND_FROM_K[t.k] || "pedestrian";
      const cls = t.cls || t.c || kind;
      if (a && (a.kind !== kind || a.cls !== cls)) { this._remove(t.id); a = null; }
      if (!a) {
        const obj = makeAgent(kind, cls, t.id, t.dims);
        const h = t.height || (t.dims && t.dims[2]);
        if (kind === "pedestrian" && h && h < 1.45) obj.scale.setScalar(Math.max(0.6, h / 1.72)); // children
        obj.position.copy(v3(t.x, t.y, 0.0));
        const label = textSprite("");
        label.visible = this.layers.labels;
        obj.add(label);
        label.position.set(0, kind === "vehicle" ? (cls === "bus" ? 3.9 : 2.4) : 2.25, 0);
        this.agentsG.add(obj);
        const trailGeo = new THREE.BufferGeometry();
        const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: KIND_COLOR[kind], transparent: true, opacity: 0.55 }));
        this.trailsG.add(trail);
        a = { obj, label, kind, cls, trail, pts: [], x: t.x, y: t.y, h: t.heading ?? 0, phase: Math.random() * 6, fade: 1, gone: false };
        this.agents.set(t.id, a);
      }
      a.gone = false;
      a.fade = 1;
      a.tx = t.x; a.ty = t.y; a.vx = t.vx || 0; a.vy = t.vy || 0; a.tRecv = now;
      const hd = t.heading ?? t.h;
      if (kind === "vehicle" || (kind === "bicycle" && Math.abs(a.vx) > 2 * Math.abs(a.vy))) {
        // road vehicles drive along the road axis: snap heading, and only change it when clearly moving
        if (Math.abs(a.vx) > 0.8) a.th = a.vx >= 0 ? 0 : Math.PI;
        else if (a.th === undefined) a.th = hd ?? 0;
      } else if (Math.hypot(a.vx, a.vy) > 0.4) {
        a.th = Math.atan2(a.vy, a.vx);
      } else if (a.th === undefined && hd !== null && hd !== undefined) {
        a.th = hd;
      }
      if (instant) { a.x = t.x; a.y = t.y; if (a.th !== undefined) a.h = a.th; }
      const sp = Math.hypot(a.vx, a.vy) * 3.6;
      const eta = (t.approach === "approaching" && t.eta !== null && t.eta !== undefined && t.eta < 15) ? ` · ${t.eta.toFixed(1)} s` : (t.approach === "waiting" ? " · waiting" : "");
      a.label.userData.set(`${cls === "pedestrian" ? "" : cls + " "}${sp.toFixed(0)} km/h${eta}`, "#" + (KIND_COLOR[kind] || 0xffffff).toString(16).padStart(6, "0"));
      if (!instant && kind !== "vehicle" && Math.random() < 0.5) this._heatAdd(t.x, t.y, 0.5);
    }
    for (const [id, a] of this.agents) if (!seen.has(id)) a.gone = true;
  }

  _remove(id) {
    const a = this.agents.get(id);
    if (!a) return;
    this.agentsG.remove(a.obj);
    this.trailsG.remove(a.trail);
    a.obj.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
    a.trail.geometry.dispose();
    this.agents.delete(id);
  }

  _applySignal(sig, safety) {
    if (!this.lamps || !sig) return;
    const t = performance.now() / 1000;
    const blink = Math.floor(t * 2) % 2 === 0;
    const on = (m, v) => (m.material.emissiveIntensity = v ? 2.2 : 0.0);
    const veh = sig.veh, ped = sig.ped;
    on(this.lamps.r, veh === "red"); on(this.lamps.y, veh === "yellow" || (veh === "flash" && blink) || (veh === "off" && blink && false)); on(this.lamps.g, veh === "green");
    on(this.lamps.pr, ped === "red"); on(this.lamps.pg, ped === "green" || (ped === "flash" && blink));
    this.warning = safety?.warning_level || 0;
  }

  _applyConflicts(list) {
    for (const o of this.conflictObjs) this.fxG.remove(o);
    this.conflictObjs = [];
    for (const c of list) {
      const col = LEVEL_COLOR[c.level] || 0xff4d4f;
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.55, 0.75, 32), new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2;
      ring.position.copy(v3(c.x, c.y, 0.25));
      ring.userData.pulse = true;
      this.fxG.add(ring);
      this.conflictObjs.push(ring);
      const veh = this.agents.get(c.veh);
      if (veh) {
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([v3(veh.x, veh.y, 0.5), v3(c.x, c.y, 0.5)]),
          new THREE.LineDashedMaterial({ color: col, dashSize: 0.4, gapSize: 0.25 }));
        line.computeLineDistances();
        this.fxG.add(line);
        this.conflictObjs.push(line);
      }
    }
  }

  flash(x, y, level = "critical") {
    const col = LEVEL_COLOR[level] || 0xff4d4f;
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.2, 40), new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 1, side: THREE.DoubleSide, depthWrite: false }));
    ring.rotation.x = -Math.PI / 2;
    ring.position.copy(v3(x, y, 0.3));
    this.fxG.add(ring);
    this.flashes.push({ ring, t0: performance.now() / 1000 });
    if (!this.replay) this._heatAdd(x, y, 6);
  }

  // ---------------------------------------------------------------- replay
  startReplay(clip, speed = 0.5) {
    this.clearAgents();
    const frames = clip.frames || [];
    if (!frames.length) return false;
    this.replay = { clip, frames, t0: frames[0].t, t1: frames[frames.length - 1].t, t: frames[0].t, speed, playing: true,
      involved: new Set([clip.event.vru, clip.event.veh, clip.event.track].filter((v) => v !== undefined)) };
    if (clip.event.x !== undefined && clip.event.x !== null) {
      this.controls.target.copy(v3(clip.event.x, clip.event.y || 0, 0));
    }
    return true;
  }

  stopReplay() { this.replay = null; this.clearAgents(); }

  seekReplay(frac) { if (this.replay) this.replay.t = this.replay.t0 + frac * (this.replay.t1 - this.replay.t0); }

  clearAgents() { for (const id of [...this.agents.keys()]) this._remove(id); }

  _replayTick(dt) {
    const r = this.replay;
    if (r.playing) {
      r.t += dt * r.speed;
      if (r.t > r.t1) { r.t = r.t0; this.clearAgents(); }
    }
    const fr = r.frames;
    let i = 0;
    while (i < fr.length - 1 && fr[i + 1].t <= r.t) i++;
    const a = fr[i], b = fr[Math.min(i + 1, fr.length - 1)];
    const k = b.t > a.t ? (r.t - a.t) / (b.t - a.t) : 0;
    const bmap = new Map(b.tracks.map((t) => [t.id, t]));
    const tracks = a.tracks.map((t) => {
      const u = bmap.get(t.id);
      if (!u) return t;
      return { ...t, x: t.x + (u.x - t.x) * k, y: t.y + (u.y - t.y) * k, vx: u.vx, vy: u.vy, h: u.h ?? t.h };
    });
    this._applyTracks(tracks, false);
    if (a.signal) this._applySignal(a.signal, null);
    for (const [id, ag] of this.agents) {
      if (!ag.hl && r.involved.has(id)) {
        const ring = new THREE.Mesh(new THREE.RingGeometry(0.7, 0.95, 32), new THREE.MeshBasicMaterial({ color: 0xff4d4f, transparent: true, opacity: 0.9, side: THREE.DoubleSide }));
        ring.rotation.x = -Math.PI / 2; ring.position.y = 0.2; ring.userData.pulse = true;
        ag.obj.add(ring); ag.hl = ring;
      }
    }
    if (this.onReplayProgress) this.onReplayProgress((r.t - r.t0) / Math.max(1e-6, r.t1 - r.t0));
  }

  // ---------------------------------------------------------------- render loop
  frame() {
    const dt = Math.min(0.1, this.clock.getDelta());
    const now = performance.now() / 1000;
    if (this.replay) this._replayTick(dt);
    const lerp = 1 - Math.exp(-dt * 10);
    for (const [id, a] of this.agents) {
      if (a.gone) {
        a.fade -= dt * 2.0;
        if (a.fade <= 0) { this._remove(id); continue; }
      }
      const ext = this.replay ? 0 : Math.min(0.3, now - (a.tRecv || now));
      const tx = (a.tx ?? a.x) + a.vx * ext, ty = (a.ty ?? a.y) + a.vy * ext;
      const nx = a.x + (tx - a.x) * lerp, ny = a.y + (ty - a.y) * lerp;
      const dist = Math.hypot(nx - a.x, ny - a.y);
      a.x = nx; a.y = ny;
      if (a.th !== undefined) {
        let d = a.th - a.h;
        d = Math.atan2(Math.sin(d), Math.cos(d));
        a.h += d * Math.min(1, dt * 6);
      }
      a.obj.position.copy(v3(a.x, a.y, 0));
      a.obj.rotation.y = a.h;
      const sp = Math.hypot(a.vx, a.vy);
      a.phase += dist * (a.kind === "pedestrian" ? 4.2 : 2.5);
      a.obj.userData.anim?.(a.phase, Math.min(0.55, sp * 0.45));
      a.obj.traverse((o) => {
        if (o.material && !o.isSprite) { o.material.transparent = a.fade < 1; o.material.opacity = Math.max(0, a.fade); }
      });
      // trails
      if (!a.pts.length || Math.hypot(a.x - a.pts[a.pts.length - 1][0], a.y - a.pts[a.pts.length - 1][1]) > 0.25) {
        a.pts.push([a.x, a.y]);
        if (a.pts.length > 80) a.pts.shift();
        a.trail.geometry.setFromPoints(a.pts.map(([x, y]) => v3(x, y, 0.06)));
      }
    }
    // pulses & flashes
    const pulse = 0.75 + 0.25 * Math.sin(now * 8);
    this.fxG.children.forEach((o) => { if (o.userData.pulse) o.scale.setScalar(pulse); });
    for (const ag of this.agents.values()) if (ag.hl) ag.hl.scale.setScalar(pulse);
    this.flashes = this.flashes.filter((f) => {
      const k = now - f.t0;
      if (k > 1.6) { this.fxG.remove(f.ring); return false; }
      f.ring.scale.setScalar(1 + k * 3.5);
      f.ring.material.opacity = 1 - k / 1.6;
      return true;
    });
    // warning beacons
    const w = this.warning || 0;
    const bon = w > 0 && Math.floor(now * (w >= 2 ? 6 : 2.5)) % 2 === 0;
    for (const b of this.beacons) {
      b.material.emissive.setHex(w >= 2 ? 0xff1a1a : 0xffb000);   // B2 danger = red, B1 caution = amber
      b.material.color.setHex(w >= 2 ? 0x3a0000 : 0x3a2a00);
      b.material.emissiveIntensity = bon ? 3.0 : 0.0;
    }
    if (this.heat && this.layers.heat && now - this.heat.tDraw > 1.0) { this.heat.tDraw = now; this._heatDraw(); }
    if (this.view !== "sensor") this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
