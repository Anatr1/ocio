// Small, local geometry helpers. No model downloads, loaders or runtime dependencies.
import * as THREE from "three";

export const material = (color, options = {}) => new THREE.MeshStandardMaterial({
  color, roughness: 0.78, metalness: 0.03, envMapIntensity: 0.45, ...options,
});

export function mesh(parent, geometry, surface, x = 0, y = 0, z = 0, shadow = true) {
  const object = new THREE.Mesh(geometry, surface);
  object.position.set(x, y, z);
  object.castShadow = shadow;
  object.receiveShadow = true;
  parent.add(object);
  return object;
}

export function bevelBox(width, height, depth, radius = 0.06) {
  const r = Math.min(radius, width / 3, height / 3, depth / 3);
  const w = width / 2 - r, h = height / 2 - r;
  const shape = new THREE.Shape();
  shape.moveTo(-w, -h); shape.lineTo(w, -h); shape.lineTo(w, h);
  shape.lineTo(-w, h); shape.closePath();
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: depth - 2 * r, bevelEnabled: true, bevelSize: r,
    bevelThickness: r, bevelSegments: 2, steps: 1, curveSegments: 2,
  });
  geometry.translate(0, 0, -(depth - 2 * r) / 2);
  return geometry;
}

export function link(parent, start, end, radius, surface, shadow = true) {
  const a = new THREE.Vector3(...start), b = new THREE.Vector3(...end);
  const object = mesh(parent, new THREE.CylinderGeometry(radius, radius, a.distanceTo(b), 8), surface, 0, 0, 0, shadow);
  object.position.copy(a).add(b).multiplyScalar(0.5);
  object.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.sub(a).normalize());
  return object;
}

// Sculpted longitudinal sections; +X is always the front of an avatar.
export function coachwork(sections) {
  const points = [], indices = [];
  for (const [x, bottom, top, halfWidth] of sections) {
    const bevel = Math.min(0.12, (top - bottom) / 4, halfWidth / 4);
    for (const [y, z] of [
      [bottom, -halfWidth + bevel], [bottom + bevel, -halfWidth],
      [top - bevel, -halfWidth], [top, -halfWidth + bevel],
      [top, halfWidth - bevel], [top - bevel, halfWidth],
      [bottom + bevel, halfWidth], [bottom, halfWidth - bevel],
    ]) points.push(x, y, z);
  }
  for (let s = 0; s < sections.length - 1; s++) for (let i = 0; i < 8; i++) {
    const a = s * 8 + i, b = s * 8 + (i + 1) % 8, c = b + 8, d = a + 8;
    indices.push(a, b, d, b, c, d);
  }
  // Caps face away from the length of the body.
  for (let i = 1; i < 7; i++) {
    indices.push(0, i + 1, i);
    const n = (sections.length - 1) * 8;
    indices.push(n, n + i, n + i + 1);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

// Static architecture has hundreds of small details, but only one draw per material.
// Only scenery is merged: agent rigs, signals and analytical overlays remain separate.
export function batchScenery(group) {
  group.updateMatrixWorld(true);
  const batches = new Map(), originals = new Set();
  group.traverse((object) => {
    if (!object.isMesh || Array.isArray(object.material)) return;
    const key = `${object.material.uuid}:${object.castShadow}`;
    if (!batches.has(key)) batches.set(key, { material: object.material, shadow: object.castShadow, parts: [] });
    const geometry = object.geometry.index ? object.geometry.toNonIndexed() : object.geometry.clone();
    geometry.applyMatrix4(object.matrixWorld);
    batches.get(key).parts.push(geometry);
    originals.add(object.geometry);
  });
  group.clear();
  for (const batch of batches.values()) {
    const geometry = new THREE.BufferGeometry();
    for (const name of ["position", "normal", "uv"]) {
      if (!batch.parts.every((part) => part.getAttribute(name))) continue;
      const size = batch.parts[0].getAttribute(name).itemSize;
      const length = batch.parts.reduce((n, part) => n + part.getAttribute(name).array.length, 0);
      const array = new Float32Array(length);
      let offset = 0;
      for (const part of batch.parts) {
        const source = part.getAttribute(name).array;
        array.set(source, offset); offset += source.length;
      }
      geometry.setAttribute(name, new THREE.BufferAttribute(array, size));
    }
    mesh(group, geometry, batch.material, 0, 0, 0, batch.shadow);
    batch.parts.forEach((part) => part.dispose());
  }
  originals.forEach((geometry) => geometry.dispose());
  return group;
}
