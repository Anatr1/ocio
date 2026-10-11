// Simulator-only "Ground truth" layer: the TRUE agents as translucent ghosts next to the perceived avatars.
// Ghost without avatar = miss (red), avatar without ghost = false positive, ghost->avatar line = position error.
// Data comes from the separate 'gt' SSE channel; the pipeline never sees it.
import * as THREE from "three";
import { makeAgent, v3 } from "./twin.js";

const MAT = {
  matched: new THREE.MeshBasicMaterial({ color: 0x386e88, transparent: true, opacity: 0.32, depthWrite: false }),
  missed: new THREE.MeshBasicMaterial({ color: 0xb84236, transparent: true, opacity: 0.55, depthWrite: false }),
  hidden: new THREE.MeshBasicMaterial({ color: 0x9aa5b1, transparent: true, opacity: 0.12, depthWrite: false }),
};

export class GroundTruthLayer {
  constructor(twin) {
    this.twin = twin;
    this.group = new THREE.Group();
    this.links = new THREE.Group();
    this.group.visible = this.links.visible = false;
    twin.scene.add(this.group, this.links);
    this.ghosts = new Map();
    this.last = null;
    const tick = () => { this._animate(); requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  }

  setVisible(on) {
    this.group.visible = this.links.visible = on;
  }

  update(p) {
    if (!p || !p.agents) return;
    this.last = p;
    const m = p.match || {};
    const missed = new Set(m.missed || []);
    const seen = new Set();
    for (const g of p.agents) {
      seen.add(g.id);
      let gh = this.ghosts.get(g.id);
      if (!gh || gh.cls !== g.cls) {
        if (gh) this.group.remove(gh.obj);
        const obj = makeAgent(g.kind, g.cls === "child" ? "pedestrian" : g.cls, g.id, g.dims);
        if (g.cls === "child") obj.scale.setScalar(0.7);
        obj.userData.anim = obj.userData.anim || (() => {});
        this.group.add(obj);
        gh = { obj, cls: g.cls, x: g.x, y: g.y, h: g.heading, mat: null, phase: 0 };
        this.ghosts.set(g.id, gh);
      }
      gh.tx = g.x; gh.ty = g.y; gh.th = g.heading; gh.sp = Math.hypot(g.vx, g.vy);
      const state = g.visible < 0.35 ? "hidden" : missed.has(g.id) ? "missed" : "matched";
      if (gh.mat !== state) {
        gh.mat = state;
        gh.obj.traverse((o) => { if (o.isMesh) o.material = MAT[state]; });
      }
    }
    for (const [id, gh] of this.ghosts) if (!seen.has(id)) { this.group.remove(gh.obj); this.ghosts.delete(id); }
    // links ghost -> perceived avatar, coloured by position error
    this.links.clear();
    for (const lk of m.links || []) {
      const gh = this.ghosts.get(lk.gt), av = this.twin.agents.get(lk.track);
      if (!gh || !av) continue;
      const col = lk.err < 0.5 ? 0x397455 : lk.err < 1.5 ? 0x876915 : 0xb84236;
      this.links.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([v3(gh.tx, gh.ty, 0.15), v3(av.x, av.y, 0.15)]),
        new THREE.LineBasicMaterial({ color: col })));
    }
  }

  _animate() {
    if (!this.group.visible) return;
    for (const gh of this.ghosts.values()) {
      const dx = gh.tx - gh.x, dy = gh.ty - gh.y;
      gh.x += dx * 0.35; gh.y += dy * 0.35;
      gh.h = gh.th;
      gh.phase += Math.hypot(dx, dy) * 1.5;
      gh.obj.position.copy(v3(gh.x, gh.y, 0));
      gh.obj.rotation.y = gh.h;
      gh.obj.userData.anim?.(gh.phase, Math.min(0.55, (gh.sp || 0) * 0.45));
    }
  }

  statsHtml() {
    const s = this.last?.match?.stats;
    if (!s) return "";
    const pct = s.recall === null || s.recall === undefined ? "–" : Math.round(s.recall * 100) + "%";
    return `<b>Ground truth</b> · visible ${s.visible} · tracked ${s.matched} (${pct}) · ` +
      `<span style="color:#b84236">missed ${s.missed}</span> · false pos ${s.false_pos} · ` +
      `pos. error ${s.mean_err_m ?? "–"} m · class ok ${s.class_ok}/${s.matched}`;
  }
}
