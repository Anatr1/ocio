// Anonymous, stylised avatars. Their roots retain the tracker coordinate frame and dimensions.
import * as THREE from "three";
import { material, mesh, bevelBox, link, coachwork, batchScenery } from "./visual-geometry.js";

export const KIND_COLOR = { pedestrian: 0xffb020, bicycle: 0x3ddc84, micromobility: 0xff6ad5, vehicle: 0x4ea8ff };
const PAINT = [0x42718a, 0xa54439, 0xe5e4d8, 0x394951, 0x7a8b87, 0x366859, 0xc2a166, 0x79728b, 0xa4afb2];
const SKIN = [0xdfaa83, 0xbd825e, 0x88563f, 0xe9bc99, 0xab7453];
const HAIR = [0x3c2c25, 0x5c4030, 0x342d2a, 0x9b7650, 0x686460];

function person(color, id = 0) {
  const g = new THREE.Group();
  const skin = material(SKIN[id % SKIN.length]);
  const hair = material(HAIR[id % HAIR.length]);
  const fabric = material(color, { roughness: 0.94 });
  const trousers = material(id % 3 === 0 ? 0x686653 : 0x344858, { roughness: 0.96 });
  const shoe = material(0x303837);
  const sole = material(0xc4c6bc);
  // Tailored shoulder / waist silhouette instead of a cylinder.
  const torso = mesh(g, bevelBox(0.30, 0.49, 0.43, 0.08), fabric, 0, 1.17);
  const hips = mesh(g, bevelBox(0.27, 0.20, 0.32, 0.055), trousers, 0, 0.88);
  mesh(g, new THREE.CylinderGeometry(0.065, 0.07, 0.13, 10), skin, 0, 1.46);
  const head = mesh(g, new THREE.SphereGeometry(1, 16, 12), skin, 0.01, 1.60);
  head.scale.set(0.115, 0.145, 0.108);
  const cap = mesh(g, new THREE.SphereGeometry(1, 16, 10, 0, Math.PI * 2, 0, Math.PI * 0.57), hair, -0.012, 1.63);
  cap.scale.set(0.118, 0.13, 0.112);
  const nose = mesh(g, new THREE.SphereGeometry(0.028, 8, 6), skin, 0.118, 1.60);
  nose.scale.set(1, 0.9, 0.7);
  // A small collar and zip make the body read as clothing at street scale.
  mesh(g, bevelBox(0.022, 0.37, 0.018, 0.005), material(0xe4d3ab), 0.157, 1.18);
  const legs = [], knees = [], arms = [], elbows = [];
  for (const s of [-1, 1]) {
    const hip = new THREE.Group(); hip.position.set(0, 0.85, s * 0.10); g.add(hip);
    mesh(hip, new THREE.CapsuleGeometry(0.073, 0.25, 4, 10), trousers, 0, -0.18);
    const knee = new THREE.Group(); knee.position.y = -0.36; hip.add(knee);
    mesh(knee, new THREE.CapsuleGeometry(0.057, 0.25, 4, 10), trousers, 0.006, -0.18);
    mesh(knee, bevelBox(0.25, 0.10, 0.135, 0.03), shoe, 0.055, -0.425);
    mesh(knee, bevelBox(0.25, 0.024, 0.14, 0.006), sole, 0.055, -0.465);
    legs.push(hip); knees.push(knee);
    const shoulder = new THREE.Group(); shoulder.position.set(0, 1.36, s * 0.25); g.add(shoulder);
    mesh(shoulder, new THREE.CapsuleGeometry(0.065, 0.16, 4, 10), fabric, 0, -0.14);
    const elbow = new THREE.Group(); elbow.position.y = -0.27; shoulder.add(elbow);
    mesh(elbow, new THREE.CapsuleGeometry(0.047, 0.17, 4, 10), fabric, 0, -0.12);
    const hand = mesh(elbow, new THREE.SphereGeometry(0.057, 10, 8), skin, 0, -0.275);
    hand.scale.set(0.8, 1.2, 0.8);
    arms.push(shoulder); elbows.push(elbow);
  }
  g.userData.anim = (phase, amp) => {
    const swing = Math.sin(phase) * amp;
    for (let i = 0; i < 2; i++) {
      const sign = i === 0 ? 1 : -1;
      legs[i].rotation.z = swing * sign;
      knees[i].rotation.z = Math.max(0, -Math.sin(phase) * sign) * amp * 0.65;
      arms[i].rotation.z = -swing * sign * 0.7;
      elbows[i].rotation.z = -0.12 - Math.max(0, swing * sign) * 0.35;
    }
    torso.position.y = 1.17 + Math.abs(Math.cos(phase)) * amp * 0.015;
    hips.rotation.x = Math.sin(phase) * amp * 0.035;
  };
  return g;
}

function rider(g, color, id, motor = false) {
  const skin = material(SKIN[id % SKIN.length]), clothes = material(color), pants = material(0x344858);
  const torso = mesh(g, bevelBox(0.30, 0.46, 0.40, 0.065), clothes, -0.08, 1.20);
  torso.rotation.z = -0.38;
  const head = mesh(g, new THREE.SphereGeometry(1, 14, 10), skin, 0.10, 1.57);
  head.scale.set(0.11, 0.14, 0.105);
  const helmet = mesh(g, new THREE.SphereGeometry(1, 14, 10, 0, Math.PI * 2, 0, Math.PI * 0.56), material(motor ? 0x283536 : 0xe8e8d9), 0.09, 1.61);
  helmet.scale.set(0.137, 0.13, 0.129);
  const legs = [];
  for (const s of [-1, 1]) {
    link(g, [0.01, 1.36, s * .21], [.26, 1.10, s * .22], .056, clothes);
    link(g, [.26, 1.10, s * .22], [.58, 1.03, s * .23], .045, skin);
    const upper = link(g, [-.19, .96, s * .15], [.19, .70, s * .15], .075, pants);
    const shin = link(g, [.19, .70, s * .15], [.04, .40, s * .15], .058, pants);
    const foot = mesh(g, bevelBox(.24, .08, .12, .025), material(0x333b39), .10, .40, s * .15);
    legs.push({ upper, shin, foot, s });
  }
  const up = new THREE.Vector3(0, 1, 0), a = new THREE.Vector3(), b = new THREE.Vector3();
  const poseLink = (object, start, end, rest) => {
    a.set(...start); b.set(...end); object.position.copy(a).add(b).multiplyScalar(.5);
    const length = a.distanceTo(b); object.scale.y = length / rest;
    object.quaternion.setFromUnitVectors(up, b.sub(a).normalize());
  };
  return (phase) => {
    if (motor) return;
    for (const leg of legs) {
      const p = phase * 1.5 + (leg.s === 1 ? Math.PI : 0);
      const x = .04 + Math.sin(p) * .14, y = .40 + Math.cos(p) * .14;
      const knee = [.22 + Math.sin(p) * .045, .69 + Math.cos(p) * .035, leg.s * .15];
      poseLink(leg.upper, [-.19, .96, leg.s * .15], knee, Math.hypot(.38, .26));
      poseLink(leg.shin, knee, [x, y, leg.s * .15], Math.hypot(.15, .30));
      leg.foot.position.set(x + .06, y, leg.s * .15);
    }
  };
}

function bicycle(color, id, motor = false) {
  const g = new THREE.Group(), wheels = [];
  const rubber = material(0x28302e, { roughness: .92 });
  const metal = material(0xb9c4c2, { metalness: .65, roughness: .32 });
  const frame = material(motor ? 0x3e5053 : 0x348b73, { metalness: .25, roughness: .5 });
  for (const x of [-.56, .56]) {
    const wheel = new THREE.Group(); wheel.position.set(x, .35, 0); g.add(wheel);
    mesh(wheel, new THREE.TorusGeometry(.32, motor ? .08 : .032, 8, 24), rubber);
    mesh(wheel, new THREE.TorusGeometry(.28, .015, 6, 24), metal);
    for (let i = 0; i < 6; i++) {
      const p = i * Math.PI / 6;
      link(wheel, [-Math.cos(p) * .28, -Math.sin(p) * .28, 0], [Math.cos(p) * .28, Math.sin(p) * .28, 0], .005, metal, false);
    }
    wheels.push(wheel);
  }
  const axle = [-.02, .35, 0], saddle = [-.24, .87, 0], stem = [.40, .82, 0];
  for (const [a, b] of [[[-.56,.35,0],saddle],[saddle,axle],[axle,[-.56,.35,0]],[saddle,stem],[stem,axle],[stem,[.56,.35,0]]]) link(g,a,b,motor?.055:.026,frame);
  link(g, saddle, [-.24,.96,0], .022, metal);
  mesh(g, bevelBox(.28,.065,.18,.025), rubber, -.24,.96);
  link(g, stem, [.54,1.03,0], .022, metal);
  link(g, [.54,1.03,-.25], [.54,1.03,.25], .022, rubber);
  if (motor) mesh(g, bevelBox(.65,.28,.30,.07), frame, 0,.64);
  const pedal = rider(g, color, id, motor);
  g.userData.anim = (phase) => { wheels.forEach((w) => { w.rotation.z = -phase * .8; }); pedal(phase); };
  return g;
}

function scooter(color, id) {
  const g = new THREE.Group(), metal = material(0x53635f, { metalness:.5 });
  mesh(g, bevelBox(.85,.07,.17,.025), metal, 0,.14);
  link(g,[.38,.16,0],[.32,1.12,0],.025,metal);
  link(g,[.32,1.12,-.23],[.32,1.12,.23],.025,material(0x333c37));
  for(const x of [-.34,.38]) mesh(g,new THREE.TorusGeometry(.09,.026,8,16),material(0x29342e),x,.105);
  const avatar = person(color,id); avatar.position.set(-.08,.15,0); g.add(avatar);
  g.userData.anim = () => {};
  return g;
}

function wheels(g, L, W, radius, y, surface) {
  const tire = material(0x252d2d, { roughness:.94 }), rim = material(0xc1c9c7,{metalness:.65,roughness:.32});
  const wheelGeo = new THREE.CylinderGeometry(radius,radius,.22,24); wheelGeo.rotateX(Math.PI/2);
  const hubGeo = new THREE.CylinderGeometry(radius*.62,radius*.62,.025,16); hubGeo.rotateX(Math.PI/2);
  for(const x of [-L*.30,L*.30]) for(const s of [-1,1]) {
    mesh(g,wheelGeo,tire,x,y,s*(W/2-.055));
    mesh(g,hubGeo,material(0x52605e),x,y,s*(W/2+.061));
    for(let i=0;i<5;i++) {
      const angle=i*Math.PI*2/5;
      const spoke=mesh(g,bevelBox(radius*.46,.045,.028,.01),rim,
        x+Math.cos(angle)*radius*.32,y+Math.sin(angle)*radius*.32,s*(W/2+.078));
      spoke.rotation.z=angle;
    }
    const hub = mesh(g,new THREE.CylinderGeometry(radius*.22,radius*.22,.031,12),surface,x,y,s*(W/2+.076));
    hub.rotation.x=Math.PI/2;
  }
}

function car(color, L = 4.4, W = 1.8, H = 1.5) {
  const g = new THREE.Group();
  const paint = material(color,{metalness:.30,roughness:.36});
  const glass = material(0x506e78,{metalness:.30,roughness:.22});
  const trim = material(0x38474a,{roughness:.65});
  const chrome = material(0xaebcbb,{metalness:.65,roughness:.30});
  const bodyBottom = H*.20, shoulder = H*.60;
  mesh(g,coachwork([
    [-L*.50,bodyBottom,shoulder*.90,W*.40],[-L*.40,bodyBottom,shoulder,W*.49],
    [-L*.24,bodyBottom,shoulder*1.04,W*.50],[L*.25,bodyBottom,shoulder,W*.50],
    [L*.43,bodyBottom,shoulder*.90,W*.47],[L*.50,bodyBottom*1.1,shoulder*.79,W*.40],
  ]),paint);
  mesh(g,coachwork([
    [-L*.32,shoulder-.025,shoulder+.03,W*.43],[-L*.19,shoulder-.025,H*.96,W*.38],
    [L*.12,shoulder-.025,H*.96,W*.38],[L*.30,shoulder-.025,shoulder+.03,W*.43],
  ]),glass);
  mesh(g,bevelBox(L*.32,.065,W*.78,.025),paint,-L*.035,H*.97);
  for(const s of [-1,1]) {
    // B-pillars, mirrors, chrome belt line and door handles.
    mesh(g,bevelBox(.065,H*.34,.025,.008),trim,-L*.02,H*.77,s*W*.395);
    mesh(g,bevelBox(L*.58,.027,.023,.008),chrome,-L*.015,shoulder+.025,s*W*.445);
    mesh(g,bevelBox(.25,.13,.14,.045),paint,L*.22,shoulder+.11,s*W*.53);
    for(const x of [-L*.20,L*.09]) mesh(g,bevelBox(.16,.028,.025,.008),chrome,x,shoulder-.10,s*W*.497);
  }
  wheels(g,L,W,Math.min(.33,H*.23),Math.min(.33,H*.23),trim);
  mesh(g,bevelBox(.09,.15,W*.65,.027),trim,L*.49,H*.32);
  mesh(g,bevelBox(.07,.065,W*.67,.018),chrome,-L*.495,H*.32);
  const headlight=material(0xf2eee0,{emissive:0xe8dcac,emissiveIntensity:.20,roughness:.24});
  const taillight=material(0xb53e36,{emissive:0x9c221a,emissiveIntensity:.12});
  for(const s of [-1,1]) {
    const head=mesh(g,bevelBox(.10,.13,W*.24,.032),headlight,L*.475,H*.49,s*W*.31);head.rotation.y=s*.12;
    mesh(g,bevelBox(.06,.13,W*.22,.025),taillight,-L*.497,H*.50,s*W*.29);
  }
  const plate=material(0xe9eade);
  for(const s of [-1,1]) {
    mesh(g,bevelBox(.022,.10,.38,.008),plate,s*L*.503,H*.38);
    mesh(g,new THREE.BoxGeometry(.026,.085,.04),material(0x35649a),s*L*.506,H*.38,-.16);
  }
  g.userData.anim=()=>{};
  return batchScenery(g);
}

function largeVehicle(cls) {
  const g = new THREE.Group(), bus = cls === 'bus';
  const L=bus?12:8,W=bus?2.55:2.5,H=bus?3.1:3.3;
  const paint=material(bus?0xc88945:0xc0c8c3,{metalness:.15,roughness:.55});
  const glass=material(0x47626b,{metalness:.3,roughness:.25});
  if(bus) {
    mesh(g,bevelBox(L,H-.42,W,.16),paint,0,.42+(H-.42)/2);
    for(const s of [-1,1]) {
      for(let x=-L*.40;x<L*.45;x+=1.15) mesh(g,bevelBox(1.01,.86,.035,.01),glass,x,H*.67,s*(W/2+.01));
      mesh(g,new THREE.BoxGeometry(L*.95,.09,.025),material(0xe4dac4),0,.75,s*(W/2+.015));
    }
    mesh(g,bevelBox(.05,1.1,W*.85,.018),glass,L/2+.01,H*.67);
  } else {
    mesh(g,bevelBox(L-2.2,H-.65,W,.09),paint,-1.1,.65+(H-.65)/2);
    mesh(g,bevelBox(2,2.25,W,.13),material(0xe4dfcf),L/2-1,1.56);
    mesh(g,bevelBox(.05,.80,W*.86,.01),glass,L/2+.01,2.07);
    for(const s of [-1,1]) mesh(g,bevelBox(1.2,.75,.035,.01),glass,L/2-1,2.05,s*(W/2+.01));
  }
  wheels(g,L,W,bus?.46:.44,bus?.46:.44,material(0x53635f));
  for(const s of [-1,1]) mesh(g,bevelBox(.045,.18,.35,.012),material(0xece8d5),L/2+.015,.70,s*W*.30);
  g.userData.anim=()=>{};
  return batchScenery(g);
}

export function makeAgent(kind, cls, id, dims) {
  const color = KIND_COLOR[kind] ?? 0xcccccc;
  if(kind==='vehicle') {
    if(cls==='bus'||cls==='truck') return largeVehicle(cls);
    if(cls==='motorcycle') return bicycle(0x46585b,id,true);
    const [L,W,H]=dims||[4.4,1.8,1.5];
    return car(PAINT[id%PAINT.length],L,W,Math.min(H,1.7));
  }
  if(kind==='bicycle') return bicycle(color,id);
  if(kind==='micromobility') return scooter(color,id);
  return person(color,id);
}
