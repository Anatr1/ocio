import * as THREE from "three";
import { GLTFLoader } from "./vendor/loaders/GLTFLoader.js";
import { RGBELoader } from "./vendor/loaders/RGBELoader.js";
import { KTX2Loader } from "./vendor/loaders/KTX2Loader.js";
import { FBXLoader } from "./vendor/loaders/FBXLoader.js";
import { TGALoader } from "./vendor/loaders/TGALoader.js";
import { clone } from "./vendor/utils/SkeletonUtils.js";
import { addBuildings, visibleSky } from "./context.js";
import { makeAgent } from "/dashboard/js/twin.js";

const vector = ([X, Y, Z = 0]) => new THREE.Vector3(X, Z, -Y);
const physical = (color, options = {}) => new THREE.MeshPhysicalMaterial({color, roughness: 0.8, ...options});
const actors = new Map();
let renderer, scene, camera, human, car, bikes = [], maskTarget, settings;
// Per-model correction so the front wheel points along the agent heading (+x after fitting).
const BIKE_FLIP = [false, false];
let sun, rain, conditions;
const errors = [];
window.addEventListener("error", (event) => errors.push(event.message));

function box(size, pos, material, parent = scene) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
  mesh.position.copy(vector(pos));
  mesh.castShadow = mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function pavementTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#b9b9b6"; ctx.fillRect(0, 0, 256, 256);
  ctx.strokeStyle = "#989b99"; ctx.lineWidth = 2;
  for (let y = 0; y <= 256; y += 64) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(256, y); ctx.stroke();
    for (let x = y % 128 / 2; x < 256; x += 64) {
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x, y + 64); ctx.stroke();
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(35, 2);
  return texture;
}

function paintTexture(seed) {
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#eeeee8"; ctx.fillRect(0, 0, 128, 128);
  let state = seed + 1;
  const next = () => { state = (Math.imul(state, 1664525) + 1013904223) >>> 0; return state / 4294967296; };
  for (let i = 0; i < 550; i++) {
    ctx.fillStyle = `rgba(56,58,55,${next() * 0.3})`;
    ctx.fillRect(next() * 128, next() * 128, 1 + next() * 4, 1 + next() * 3);
  }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

async function environment(sc, seed) {
  if (sc.intersection) {
    const { buildIntersection } = await import("./intersection-environment.js");
    return buildIntersection(scene, sc.intersection, seed, conditions);
  }
  const W = sc.crosswalk.width, L = sc.crosswalk.length, A = Math.max(sc.approach + 20, 60);
  const textureLoader = new THREE.TextureLoader();
  const [diffuse, normal, rough] = await Promise.all(["asphalt.jpg", "asphalt-normal.jpg", "asphalt-rough.jpg"]
    .map(name => textureLoader.loadAsync(`./assets/${name}`)));
  diffuse.colorSpace = THREE.SRGBColorSpace;
  for (const t of [diffuse, normal, rough]) {
    t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(A / 3, L / 6); t.anisotropy = 8;
  }
  const wet = conditions.weather === "rain";
  box([A * 2, 0.08, L], [0, 0, -0.04], physical(0xc1c1c1, {
    map: diffuse, normalMap: normal, roughnessMap: wet ? null : rough, roughness: wet ? 0.2 : 0.95,
    clearcoat: wet ? 0.6 : 0, clearcoatRoughness: 0.12,
  }));
  const paint = physical(0xffffff, {map: paintTexture(seed), roughness: wet ? 0.35 : 0.8});
  const stripe = sc.stripe || {width: 0.5, gap: 0.5};
  for (let y = -L / 2 + 0.25; y + stripe.width <= L / 2 - 0.1; y += stripe.width + stripe.gap) {
    box([W, 0.004, stripe.width], [0, y + stripe.width / 2, 0.002], paint);
  }
  for (let x = -A; x < A; x += 6) {
    if (Math.abs(x) > W / 2 + 3) box([3, 0.004, 0.1], [x + 1.5, 0, 0.002], paint);
  }
  for (const d of [-1, 1]) {
    box([0.3, 0.004, L / 2 - 0.3], [-d * (W / 2 + 1.5), -d * L / 4, 0.002], paint);
    box([A * 2, 0.15, sc.curb_depth + sc.sidewalk_width],
      [0, d * (L / 2 + (sc.curb_depth + sc.sidewalk_width) / 2), -0.04], physical(0xffffff, {map: pavementTexture()}));
    box([A * 2, 0.18, 0.22], [0, d * (L / 2 + 0.11), 0.02], physical(0xbcbfba));
    const poleY = d * (L / 2 + 1.2);
    box([0.08, 4.5, 0.08], [W / 2 + 1.8, poleY, 2.25], physical(0x727d80, {metalness: 0.8}));
    const lamp = new THREE.PointLight(0xffefcf, conditions.time_of_day === "night" ? 40 : 0, 14, 2);
    lamp.position.copy(vector([W / 2 + 1.8, poleY, 4.5])); scene.add(lamp);
    box([1.2, 0.09, 0.35], [W / 2 + 1.3, poleY, 4.5], physical(0xe4e2dc, {emissive: 0xffffda, emissiveIntensity: lamp.intensity ? 1 : 0}));
    const sign = box([0.55, 0.55, 0.04], [W / 2 + 1.8, poleY, 3], physical(0x2263a0));
    sign.userData.sign = true;
  }
  const context = addBuildings(scene, sc, seed, conditions);
  if (conditions.weather === "rain") {
    const vertices = [];
    for (let i = 0; i < 600; i++) {
      const x = Math.sin(i * 137.5 + seed) * 25, y = Math.cos(i * 17.9 + seed) * 16, z = 1 + (i % 70) / 5;
      vertices.push(x, z, -y, x - 0.06, z - 0.3, -y - 0.02);
    }
    const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
    rain = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({color: 0xb2c2ca, opacity: 0.24, transparent: true}));
    rain.userData.excludeMask = true; scene.add(rain);
  }
  return context;
}

function fitModel(model, dims, uniform = false) {
  model.updateMatrixWorld(true);
  let bounds = new THREE.Box3().setFromObject(model);
  const size = bounds.getSize(new THREE.Vector3());
  if (!uniform && size.z > size.x) { model.rotation.y += Math.PI / 2; model.updateMatrixWorld(true); bounds.setFromObject(model); }
  bounds.getSize(size);
  model.scale.multiply(uniform ? new THREE.Vector3().setScalar(dims[2] / size.y) : new THREE.Vector3(dims[0] / size.x, dims[2] / size.y, dims[1] / size.z));
  model.updateMatrixWorld(true); bounds.setFromObject(model);
  const center = bounds.getCenter(new THREE.Vector3());
  model.position.sub(new THREE.Vector3(center.x, bounds.min.y, center.z));
  model.updateMatrixWorld(true);
}

function person(a, dims = a.dims) {
  const root = new THREE.Group();
  const model = clone(human.scene);
  model.rotation.y = Math.PI / 2;
  fitModel(model, dims, true);
  model.traverse(o => {
    if (!o.isMesh) return;
    const materials = (Array.isArray(o.material) ? o.material : [o.material]).map(m => {
      const copy = m.isMeshPhongMaterial ? new THREE.MeshStandardMaterial({map: m.map, normalMap: m.normalMap,
        color: m.color, roughness: 0.75, metalness: 0, alphaMap: m.alphaMap, transparent: m.transparent,
        opacity: m.opacity, side: m.side}) : m.clone();
      // Rocketbox's Max export stores zero diffuse tint; the colour lives in its map.
      if (settings.human_asset === "rocketbox" && m.map && m.color.r + m.color.g + m.color.b === 0) copy.color.set(0xffffff);
      copy.color.multiplyScalar(0.9 + (a.id % 3) * 0.05);
      copy.envMapIntensity = conditions.time_of_day === "night" ? 0.1 : 1;
      return copy;
    });
    o.material = Array.isArray(o.material) ? materials : materials[0];
  });
  root.add(model);
  const mixer = new THREE.AnimationMixer(model);
  const walk = human.animations.find(clip => /walking|walk/i.test(clip.name)) || human.animations[0];
  if (walk) mixer.clipAction(walk).play();
  const quality = settings.human_asset === "human-scan.glb" ? "scanned_static_no_gait" :
    settings.human_asset === "rocketbox" ? "textured_rigged_rocketbox_not_scanned" : "rigged_sample_not_scanned";
  return {model: root, mixer, quality};
}

function bicycle(a) {
  // Real bicycle mesh, ~1.75 m long, wheels on the ground, front along +x; a rigged rider on the saddle.
  // The walk clip on the rider reads as pedalling; this is an approximation, not a cycling animation.
  const index = a.id % bikes.length;
  const model = clone(bikes[index].scene);
  model.traverse(o => { if (o.isMesh) o.material = Array.isArray(o.material) ? o.material.map(m => m.clone()) : o.material.clone(); });
  model.updateMatrixWorld(true);
  const bounds = new THREE.Box3().setFromObject(model), size = bounds.getSize(new THREE.Vector3());
  if (size.z > size.x) model.rotation.y += Math.PI / 2;
  if (BIKE_FLIP[index]) model.rotation.y += Math.PI;
  model.updateMatrixWorld(true); bounds.setFromObject(model); bounds.getSize(size);
  model.scale.multiplyScalar(1.75 / size.x);
  model.updateMatrixWorld(true); bounds.setFromObject(model);
  const center = bounds.getCenter(new THREE.Vector3());
  model.position.sub(new THREE.Vector3(center.x, bounds.min.y, center.z));
  const root = new THREE.Group();
  root.add(model);
  const rider = person(a, [0.5, 0.5, 1.72]);
  rider.model.position.set(-0.12, 0.12, 0);  // hips over the saddle, feet near the pedals
  rider.model.rotation.z = -0.18;            // leaning towards the handlebar
  root.add(rider.model);
  return {model: root, mixer: rider.mixer, quality: "objaverse_bicycle_with_rigged_walking_rider"};
}

function createActor(a) {
  let root = new THREE.Group(), mixer = null, quality;
  if (a.kind === "pedestrian") {
    ({model: root, mixer, quality} = person(a));
    if (a.cls === "wheelchair" || a.cls === "stroller") {
      // Accessory geometry is provisional and must not be claimed to pass G2.
      for (const z of [-0.3, 0.3]) {
        const wheel = new THREE.Mesh(new THREE.TorusGeometry(0.28, 0.045, 8, 24), physical(0x202526));
        wheel.position.set(0, 0.3, z); root.add(wheel);
      }
      box([0.6, 0.08, 0.6], [0.15, 0, 0.42], physical(0x323b3c), root);
      quality = "rigged_sample_provisional_accessory";
    }
  } else if (a.cls === "bicycle" && bikes.length) {
    ({model: root, mixer, quality} = bicycle(a));
  } else if (a.cls === "car") {
    const model = clone(car.scene);
    fitModel(model, a.dims);
    model.traverse(o => {
      if (!o.isMesh) return;
      const materials = (Array.isArray(o.material) ? o.material : [o.material]).map(m => {
        const copy = m.clone();
        if (/paint|body/i.test(m.name)) copy.color.setRGB(...a.color.map(c => c / 255));
        return copy;
      });
      o.material = Array.isArray(o.material) ? materials : materials[0];
    });
    root.add(model); quality = "detailed_pbr_sample";
  } else {
    root = makeAgent(a.kind, a.cls, a.id, a.dims);
    quality = "schematic_twin_fallback";
  }
  root.userData.instanceId = a.id;
  root.traverse(o => { if (o.isMesh) { o.castShadow = o.receiveShadow = true; o.frustumCulled = false; } });
  scene.add(root);
  return {root, mixer, quality, phase: 0, t: 0};
}

function updateActors(snapshot) {
  const ids = new Set(snapshot.agents.map(a => a.id));
  for (const [id, actor] of actors) if (!ids.has(id)) {
    scene.remove(actor.root);
    actor.root.traverse(o => {
      // Geometry/maps are shared by GLTF clones; only per-instance materials are disposable.
      if (o.isMesh && actor.quality !== "schematic_twin_fallback") {
        (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => m.dispose());
      }
    });
    actor.mixer?.stopAllAction(); actors.delete(id);
  }
  for (const a of snapshot.agents) {
    if (!actors.has(a.id)) actors.set(a.id, createActor(a));
    const actor = actors.get(a.id);
    actor.root.position.copy(vector([a.x, a.y, 0]));
    actor.root.rotation.y = a.heading;
    actor.phase += a.speed * Math.max(0, snapshot.t - actor.t) / 0.35;
    actor.t = snapshot.t;
    if (actor.mixer) actor.mixer.setTime(actor.phase * 0.25);
    actor.root.userData.anim?.(actor.phase, a.speed > 0.2 ? 0.4 : 0);
    if (rain) rain.position.y = -(snapshot.t * 4 % 12);
  }
  scene.updateMatrixWorld(true);
  // r160 caches skeleton uploads by render frame; the previous RGB shadow pass can
  // share that frame number with the next mask pass. Refresh the current pose now.
  const skeletons = new Set();
  for (const actor of actors.values()) actor.root.traverse(o => {
    if (o.isSkinnedMesh) skeletons.add(o.skeleton);
  });
  skeletons.forEach(skeleton => skeleton.update());
}

function pixelsToPNG(bytes) {
  const c = document.createElement("canvas"); c.width = settings.width; c.height = settings.height;
  const image = new ImageData(settings.width, settings.height);
  for (let y = 0; y < settings.height; y++) {
    image.data.set(bytes.subarray((settings.height - 1 - y) * settings.width * 4, (settings.height - y) * settings.width * 4), y * settings.width * 4);
  }
  c.getContext("2d").putImageData(image, 0, 0);
  return {png: c.toDataURL("image/png"), bytes: image.data};
}

function instancePass(snapshot) {
  const saved = [], flat = new Map();
  const bg = scene.background, env = scene.environment, fog = scene.fog;
  const tone = renderer.toneMapping, shadows = renderer.shadowMap.enabled;
  const black = new THREE.MeshBasicMaterial({color: 0});
  scene.background = new THREE.Color(0); scene.environment = scene.fog = null;
  renderer.toneMapping = THREE.NoToneMapping; renderer.shadowMap.enabled = false;
  scene.traverse(o => {
    if (o.userData.excludeMask) { saved.push([o, null, o.visible]); o.visible = false; return; }
    if (!o.isMesh) return;
    let p = o, id = 0;
    while (p) { if (p.userData.instanceId) { id = p.userData.instanceId; break; } p = p.parent; }
    if (id && !flat.has(id)) {
      const color = new THREE.Color().setRGB((id & 255) / 255, ((id >> 8) & 255) / 255, ((id >> 16) & 255) / 255, THREE.LinearSRGBColorSpace);
      flat.set(id, new THREE.MeshBasicMaterial({color, side: THREE.DoubleSide}));
    }
    saved.push([o, o.material, o.visible]); o.material = flat.get(id) || black;
  });
  renderer.setRenderTarget(maskTarget); renderer.render(scene, camera);
  const data = new Uint8Array(settings.width * settings.height * 4);
  renderer.readRenderTargetPixels(maskTarget, 0, 0, settings.width, settings.height, data);
  renderer.setRenderTarget(null);
  for (const [o, mat, visible] of saved) { if (mat) o.material = mat; o.visible = visible; }
  scene.background = bg; scene.environment = env; scene.fog = fog;
  renderer.toneMapping = tone; renderer.shadowMap.enabled = shadows;
  black.dispose(); flat.forEach(m => m.dispose());
  const {png, bytes} = pixelsToPNG(data), boxes = new Map();
  for (let y = 0; y < settings.height; y++) for (let x = 0; x < settings.width; x++) {
    const offset = (y * settings.width + x) * 4;
    const id = bytes[offset] + (bytes[offset + 1] << 8) + (bytes[offset + 2] << 16);
    if (!actors.has(id)) continue;
    if (!boxes.has(id)) boxes.set(id, {id, box: [x, y, x + 1, y + 1], pixels: 0});
    const item = boxes.get(id); item.pixels++;
    item.box = [Math.min(item.box[0], x), Math.min(item.box[1], y), Math.max(item.box[2], x + 1), Math.max(item.box[3], y + 1)];
  }
  return {mask: png, boxes: snapshot.agents.map(a => ({id: a.id, cls: a.det_class, kind: a.kind,
    box: boxes.get(a.id)?.box || null, pixels: boxes.get(a.id)?.pixels || 0, asset_quality: actors.get(a.id).quality}))};
}

async function initialize(options) {
  settings = options; conditions = options.conditions;
  renderer = new THREE.WebGLRenderer({canvas: document.querySelector("canvas"), antialias: false, preserveDrawingBuffer: true, powerPreference: "high-performance"});
  renderer.setPixelRatio(1); renderer.setSize(options.width, options.height, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = conditions.time_of_day === "night" ? 0.35 : conditions.time_of_day === "dusk" ? 0.65 : 1.0;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  scene = new THREE.Scene();
  const K = options.K, n = 0.1, f = 250;
  camera = new THREE.PerspectiveCamera(45, options.width / options.height, n, f);
  camera.position.copy(vector(options.camera.position));
  camera.up.copy(vector(options.camera.up));
  camera.lookAt(camera.position.clone().add(vector(options.camera.forward)));
  // Off-axis projection supports fx/fy and principal point, not just a guessed FOV.
  camera.projectionMatrix.makePerspective(-K[0][2] * n / K[0][0], (options.width - K[0][2]) * n / K[0][0],
    K[1][2] * n / K[1][1], -(options.height - K[1][2]) * n / K[1][1], n, f);
  camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
  camera.updateMatrixWorld(true);
  maskTarget = new THREE.WebGLRenderTarget(options.width, options.height, {minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, colorSpace: THREE.NoColorSpace, samples: 0});
  const loader = new GLTFLoader();
  const ktx = new KTX2Loader().setTranscoderPath("./vendor/libs/basis/").setWorkerLimit(1).detectSupport(renderer);
  loader.setKTX2Loader(ktx);
  const loadHuman = async () => {
    if (options.human_asset !== "rocketbox") return loader.loadAsync(`./assets/${options.human_asset}`);
    const manager = new THREE.LoadingManager();
    const texturesLoaded = new Promise((resolve, reject) => {
      manager.onLoad = resolve;
      manager.onError = url => reject(new Error(`Rocketbox texture missing: ${url}`));
    });
    manager.addHandler(/\.tga$/i, new TGALoader());
    const fbx = new FBXLoader(manager).setResourcePath("./assets/rocketbox/");
    const [model, motion] = await Promise.all([fbx.loadAsync("./assets/rocketbox/human.fbx"), fbx.loadAsync("./assets/rocketbox/walk.fbx")]);
    await texturesLoaded;
    const clip = motion.animations[0];
    if (!clip) throw new Error("Rocketbox walk animation is missing");
    // Same Rocketbox bone names: retain joint rotations, discard source-body lengths/root travel.
    const tracks = clip.tracks.filter(t => t.name.endsWith(".quaternion") && model.getObjectByName(t.name.slice(0, -11)));
    if (tracks.length < 15) throw new Error(`Rocketbox animation cannot bind: ${tracks.length} joints`);
    return {scene: model, animations: [new THREE.AnimationClip("walk", clip.duration, tracks)]};
  };
  [human, car, ...bikes] = await Promise.all([loadHuman(), loader.loadAsync("./assets/car.glb"),
    loader.loadAsync("./assets/bicycle-1.glb"), loader.loadAsync("./assets/bicycle-2.glb")]);
  ktx.dispose();
  const hdr = await new RGBELoader().loadAsync("./assets/sky.hdr");
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromEquirectangular(hdr).texture;
  scene.background = visibleSky(hdr, conditions);
  scene.backgroundIntensity = conditions.time_of_day === "day" && conditions.weather === "clear" ? .8 : 1;
  if (scene.background !== hdr) hdr.dispose();
  pmrem.dispose();
  const night = conditions.time_of_day === "night";
  const hemi = new THREE.HemisphereLight(0xdfefff, 0x77745f, night ? 0.12 : 1.2); scene.add(hemi);
  sun = new THREE.DirectionalLight(conditions.time_of_day === "dusk" ? 0xffce96 : 0xfff6ea, night ? 0.05 : 2.5);
  sun.position.set(-12, conditions.time_of_day === "low_sun" ? 3 : 30, -18); sun.castShadow = !night;
  sun.shadow.mapSize.set(1024, 1024);
  Object.assign(sun.shadow.camera, {left: -35, right: 35, top: 35, bottom: -35, near: 1, far: 80});
  sun.shadow.bias = -0.001; sun.shadow.normalBias = 0.025; scene.add(sun);
  if (conditions.weather === "fog") scene.fog = new THREE.FogExp2(0xbfc9ce, 0.045);
  if (conditions.weather === "rain") { scene.fog = new THREE.FogExp2(0x969fa5, 0.012); sun.intensity *= 0.4; }
  const context = await environment(options.scene, options.seed);
  if (night) scene.traverse(o => {
    if (o.isMesh) (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => { m.envMapIntensity = 0.1; });
  });
  const gl = renderer.getContext(), info = gl.getExtension("WEBGL_debug_renderer_info");
  const humanMaterials = new Map();
  human.scene.traverse(o => {
    if (o.isMesh) (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => humanMaterials.set(m.name,
      {name: m.name, color: m.color.toArray(), texture_size: m.map?.image ? [m.map.image.width, m.map.image.height] : null}));
  });
  return {three: THREE.REVISION, gpu: info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
    webgl2: renderer.capabilities.isWebGL2, human_animations: human.animations.map(a => a.name),
    human_materials: [...humanMaterials.values()], context, errors};
}

function project(points) {
  return points.map(point => {
    const v = vector(point).project(camera);
    return [(v.x + 1) * settings.width / 2, (1 - v.y) * settings.height / 2];
  });
}

function render(snapshot) {
  scene.userData.updateIntersectionSignals?.(snapshot.signal);
  updateActors(snapshot);
  const labels = instancePass(snapshot);
  renderer.render(scene, camera);
  return {rgb: renderer.domElement.toDataURL("image/png"), ...labels, errors: [...errors]};
}

window.provingGround = {initialize, render, project, errors};

// Optional intersection cameras; the original crosswalk camera stays unchanged.
window.provingGround.setCamera = options => {
  camera.position.copy(vector(options.camera.position));
  camera.up.copy(vector(options.camera.up));
  camera.lookAt(camera.position.clone().add(vector(options.camera.forward)));
  const K = options.K, n = camera.near, f = camera.far;
  camera.projectionMatrix.makePerspective(-K[0][2]*n/K[0][0], (settings.width-K[0][2])*n/K[0][0],
    K[1][2]*n/K[1][1], -(settings.height-K[1][2])*n/K[1][1], n, f);
  camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
  camera.updateMatrixWorld(true);
};
