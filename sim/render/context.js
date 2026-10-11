// Generic contemporary urban context for the pixel simulator, independent of the dashboard twin.
import * as THREE from "three";
import { mergeGeometries } from "./vendor/utils/BufferGeometryUtils.js";

function random(seed) {
  let value = seed >>> 0;
  return () => { value = (Math.imul(value, 1664525) + 1013904223) >>> 0; return value / 4294967296; };
}

function texture(canvas, color = false) {
  const map = new THREE.CanvasTexture(canvas);
  if (color) map.colorSpace = THREE.SRGBColorSpace;
  map.wrapS = map.wrapT = THREE.RepeatWrapping;
  map.anisotropy = 8;
  return map;
}

function masonry(style, seed) {
  const rnd = random(seed), size = 512;
  const canvases = Array.from({length: 3}, () => Object.assign(document.createElement("canvas"), {width: size, height: size}));
  const [g, bump, rough] = canvases.map(c => c.getContext("2d"));
  const base = style === "brick" ? [130, 102, 84] : style === "concrete" ? [177, 175, 166] : [202, 197, 183];
  g.fillStyle = `rgb(${base})`; g.fillRect(0, 0, size, size);
  bump.fillStyle = "#aaa"; bump.fillRect(0, 0, size, size);
  rough.fillStyle = "#d4d4d4"; rough.fillRect(0, 0, size, size);
  const cellW = style === "brick" ? 38 : 256, cellH = style === "brick" ? 17 : 128;
  for (let y = -cellH; y < size; y += cellH) {
    const offset = style === "brick" && Math.round(y / cellH) % 2 ? -cellW / 2 : 0;
    for (let x = offset; x < size; x += cellW) {
      const shade = (rnd() - .5) * (style === "brick" ? 26 : 9);
      g.fillStyle = `rgb(${base.map(c => Math.round(c + shade))})`;
      g.fillRect(x + 1, y + 1, cellW - 2, cellH - 2);
      bump.fillStyle = `rgb(${[0, 0, 0].map(() => Math.round(160 + rnd() * 20))})`;
      bump.fillRect(x + 1, y + 1, cellW - 2, cellH - 2);
      g.strokeStyle = style === "brick" ? "rgba(183,178,160,.6)" : "rgba(94,96,91,.24)";
      g.lineWidth = style === "brick" ? 1.5 : 1;
      g.strokeRect(x, y, cellW, cellH);
    }
  }
  // Fine mineral grain and irregular vertical rain staining; no baked directional lighting.
  for (let i = 0; i < 38000; i++) {
    const x = rnd() * size, y = rnd() * size, light = rnd() > .5;
    g.fillStyle = light ? "rgba(239,232,217,.055)" : "rgba(36,39,35,.045)";
    g.fillRect(x, y, .5 + rnd(), .5 + rnd());
    bump.fillStyle = light ? "rgba(255,255,255,.16)" : "rgba(0,0,0,.12)";
    bump.fillRect(x, y, 1, 1);
  }
  for (let i = 0; i < 24; i++) {
    const x = rnd() * size, y = rnd() * size, w = 1 + rnd() * 9, h = 28 + rnd() * 180;
    const stain = g.createLinearGradient(0, y, 0, y + h);
    stain.addColorStop(0, "rgba(49,54,44,.075)"); stain.addColorStop(1, "rgba(49,54,44,0)");
    g.fillStyle = stain; g.fillRect(x, y, w, h);
  }
  const material = new THREE.MeshStandardMaterial({
    map: texture(canvases[0], true), bumpMap: texture(canvases[1]), roughnessMap: texture(canvases[2]),
    color: 0xffffff, roughness: 1, bumpScale: style === "brick" ? .018 : .009,
  });
  material.userData.metreUV = true;
  return material;
}

function glass(seed, night, lit) {
  const c = Object.assign(document.createElement("canvas"), {width: 128, height: 192});
  const g = c.getContext("2d"), rnd = random(seed);
  const gradient = g.createLinearGradient(0, 0, 100, 192);
  gradient.addColorStop(0, night ? (lit ? "#c5a780" : "#242e34") : "#788e98");
  gradient.addColorStop(.55, night ? (lit ? "#8e7658" : "#172229") : "#3d4d56");
  gradient.addColorStop(1, night ? "#171d22" : "#263a43");
  g.fillStyle = gradient; g.fillRect(0, 0, 128, 192);
  // Rooms vary: half-drawn blinds, curtains, a dark ceiling and a recessed sill.
  const blind = 12 + rnd() * 110;
  g.fillStyle = night && lit ? "rgba(236,210,157,.6)" : "rgba(187,191,179,.32)";
  g.fillRect(0, 0, 128, blind);
  g.strokeStyle = "rgba(22,29,29,.22)"; g.lineWidth = 1;
  for (let y = 4; y < blind; y += 5) { g.beginPath(); g.moveTo(0, y); g.lineTo(128, y); g.stroke(); }
  if (rnd() > .45) {
    const curtain = g.createLinearGradient(0, 0, 30, 0);
    curtain.addColorStop(0, "rgba(193,181,155,.08)"); curtain.addColorStop(.5, "rgba(210,201,177,.42)");
    curtain.addColorStop(1, "rgba(193,181,155,.08)"); g.fillStyle = curtain;
    g.fillRect(0, blind, 29, 192 - blind); g.fillRect(101, blind, 27, 192 - blind);
  }
  g.fillStyle = "rgba(12,20,24,.25)"; g.fillRect(0, 184, 128, 8);
  return new THREE.MeshPhysicalMaterial({map: texture(c, true), color: 0xdde6e7,
    metalness: .25, roughness: .16, clearcoat: .85, clearcoatRoughness: .08,
    envMapIntensity: night ? .1 : .8, emissive: lit ? 0xdcb77d : 0x000000,
    emissiveMap: lit ? texture(c, true) : null, emissiveIntensity: lit ? .75 : 0});
}

function solid(parent, size, pos, material, castShadow = true) {
  const geometry = new THREE.BoxGeometry(...size);
  if (material.userData.metreUV) {
    const vertices = geometry.attributes.position, normals = geometry.attributes.normal, uv = geometry.attributes.uv;
    // Metre-based UVs keep masonry courses aligned across the separate window reveals.
    for (let i = 0; i < vertices.count; i++) {
      const x = vertices.getX(i) + pos[0], y = vertices.getY(i) + pos[1], z = vertices.getZ(i) + pos[2];
      uv.setXY(i, (Math.abs(normals.getX(i)) > .5 ? z : x) / 3, (Math.abs(normals.getY(i)) > .5 ? z : y) / 3);
    }
  }
  const object = new THREE.Mesh(geometry, material);
  object.position.set(...pos); object.castShadow = castShadow; object.receiveShadow = true;
  parent.add(object);
  return object;
}

function batch(group) {
  group.updateMatrixWorld(true);
  const batches = new Map();
  group.traverse(o => {
    if (!o.isMesh) return;
    const key = `${o.material.uuid}:${o.castShadow}`;
    if (!batches.has(key)) batches.set(key, {material: o.material, shadow: o.castShadow, parts: []});
    o.geometry.applyMatrix4(o.matrixWorld); batches.get(key).parts.push(o.geometry);
  });
  group.clear();
  for (const b of batches.values()) {
    const object = new THREE.Mesh(mergeGeometries(b.parts), b.material);
    object.castShadow = b.shadow; object.receiveShadow = true; group.add(object);
    b.parts.forEach(g => g.dispose());
  }
  return group;
}

export function addBuildings(scene, sc, seed, conditions) {
  const context = new THREE.Group(), A = Math.max(sc.approach + 20, 60), L = sc.crosswalk.length;
  const walls = [masonry("concrete", 73), masonry("brick", 19), masonry("stone", 131)];
  const metal = new THREE.MeshStandardMaterial({color: 0x525b60, roughness: .48, metalness: .6});
  const sill = new THREE.MeshStandardMaterial({color: 0xb6b7b0, roughness: .72});
  const roof = new THREE.MeshStandardMaterial({color: 0x656966, roughness: .93});
  const recess = new THREE.MeshStandardMaterial({color: 0x141d21, roughness: .92});
  const night = conditions.time_of_day === "night";
  const panes = Array.from({length: 6}, (_, i) => glass(i * 97 + 3, night, night && i < 2));
  let index = 0;
  for (const side of [-1, 1]) for (let x = -A; x < A; x += 12) {
    if (sc.intersection && Math.abs(x) < 16) continue;
    const rnd = random(seed * 7919 + ++index * 104729);
    // Retain the old context's footprint and height range, outside the waiting/approach areas.
    const h = 9 + ((Math.abs(x) + seed) % 5), width = 11.7, depth = 8;
    const g = new THREE.Group();
    g.position.set(x, 0, -side * (L / 2 + sc.curb_depth + sc.sidewalk_width + 5));
    g.rotation.y = side > 0 ? 0 : Math.PI; context.add(g);
    const wall = walls[(index + seed) % walls.length], front = depth / 2;
    solid(g, [width, h, depth - .35], [0, h / 2, -.175], wall);
    const floors = Math.floor((h - .5) / 2.6), windowW = 1.65, windowH = 1.65;
    const bays = [-3.8, -1.2, 1.2, 3.8];
    // Openings in the front wall are real geometry, with glass 18 cm behind the face.
    const facade = (left, right, bottom, top) => {
      if (right > left && top > bottom) solid(g, [right - left, top - bottom, .35],
        [(left + right) / 2, (bottom + top) / 2, front - .175], wall);
    };
    let lastTop = 0;
    for (let floor = 0; floor < floors; floor++) {
      const bottom = .65 + floor * 2.6, top = bottom + windowH;
      facade(-width / 2, width / 2, lastTop, bottom);
      let previous = -width / 2;
      for (const bx of bays) {
        facade(previous, bx - windowW / 2, bottom, top); previous = bx + windowW / 2;
        solid(g, [windowW, windowH, .015], [bx, bottom + windowH / 2, front - .30], recess, false);
        solid(g, [windowW - .12, windowH - .12, .025], [bx, bottom + windowH / 2, front - .18], panes[Math.floor(rnd() * panes.length)], false);
        for (const dx of [-windowW / 2 + .025, windowW / 2 - .025, -.15]) {
          solid(g, [.05, windowH, .12], [bx + dx, bottom + windowH / 2, front - .115], metal);
        }
        for (const dy of [bottom + .025, top - .025]) solid(g, [windowW, .05, .12], [bx, dy, front - .115], metal);
        solid(g, [windowW + .15, .07, .48], [bx, bottom - .035, front - .10], sill);
      }
      facade(previous, width / 2, bottom, top); lastTop = top;
    }
    facade(-width / 2, width / 2, lastTop, h);
    solid(g, [width, .25, .20], [0, .125, front + .01], roof);
    // An understated metal entrance and canopy; no period ornament or shutters.
    const doorX = index % 2 ? 0 : -5.0;
    solid(g, [1.15, 2.25, .05], [doorX, 1.125, front + .03], recess);
    solid(g, [.96, 2.10, .035], [doorX, 1.08, front + .065], panes[index % panes.length], false);
    for (const dx of [-.54, .54]) solid(g, [.045, 2.25, .075], [doorX + dx, 1.125, front + .08], metal);
    solid(g, [1.6, .09, .75], [doorX, 2.40, front + .26], metal);
    solid(g, [.025, .40, .055], [doorX + .32, 1.10, front + .12], sill);
    solid(g, [width, .08, depth], [0, h + .04, 0], roof);
    for (const z of [-front + .08, front - .08]) {
      solid(g, [width, .28, .16], [0, h + .14, z], wall);
      solid(g, [width + .06, .045, .23], [0, h + .30, z], metal);
    }
    for (const dx of [-width / 2 + .08, width / 2 - .08]) solid(g, [.16, .28, depth], [dx, h + .14, 0], wall);
    solid(g, [.07, h, .07], [width / 2 - .18, h / 2, front + .05], metal);
    // Rooftop plant and vents give believable silhouettes without extending toward traffic.
    const plantX = (rnd() - .5) * 4;
    solid(g, [1.6, .65, .9], [plantX, h + .40, -1], sill);
    for (let n = 0; n < 6; n++) solid(g, [1.35, .018, .035], [plantX, h + .16 + n * .08, -.535], metal, false);
    solid(g, [.28, .60, .28], [-plantX + 2, h + .34, -2.3], metal);
  }
  context.userData.genericFacade = true;
  scene.add(batch(context));
  return {buildings: index, drawMeshes: context.children.length};
}

export function visibleSky(hdr, conditions) {
  // The existing CC0 photographic HDRI already supplies reflections. Also show it in the camera.
  hdr.mapping = THREE.EquirectangularReflectionMapping;
  if (conditions.time_of_day === "day" && conditions.weather === "clear") return hdr;
  const {width, height, data} = hdr.image;
  const output = new Float32Array(width * height * 4);
  const night = conditions.time_of_day === "night", fog = conditions.weather === "fog", rain = conditions.weather === "rain";
  const unpack = hdr.type === THREE.HalfFloatType ? THREE.DataUtils.fromHalfFloat : value => value;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const i = (y * width + x) * 4;
    const source = [0, 1, 2].map(c => unpack(data[i + c]));
    const luma = source[0] * .2126 + source[1] * .7152 + source[2] * .0722;
    const horizon = Math.exp(-(((y / height - .5) / .17) ** 2));
    if (night) {
      const clouds = Math.min(.045, luma * .012);
      output.set([.006 + clouds + horizon * .012, .012 + clouds + horizon * .016, .023 + clouds + horizon * .024, 1], i);
    } else if (fog || rain) {
      // Keep photographic cloud structure, suppress the clear-day sun and flatten contrast in fog.
      const cloud = luma / (1 + luma), shade = (fog ? .63 : .34) + cloud * (fog ? .08 : .23) + horizon * .10;
      output.set([shade * .93, shade * .98, shade * 1.04, 1], i);
    } else {
      // Dusk/low sun: blue upper atmosphere and a warm horizon, retaining the HDR cloud detail.
      const base = Math.min(1.5, luma) * .45;
      output.set([base * .77 + horizon * .57, base * .90 + horizon * .29, base * 1.12 + horizon * .12, 1], i);
    }
  }
  const sky = new THREE.DataTexture(output, width, height, THREE.RGBAFormat, THREE.FloatType);
  sky.mapping = THREE.EquirectangularReflectionMapping; sky.minFilter = sky.magFilter = THREE.LinearFilter;
  sky.needsUpdate = true;
  return sky;
}
