"""Download licensed renderer assets and matching Three.js r160 addons once.

    python tools/fetch_sim_assets.py
Records hashes so every run can identify the exact local asset set.
"""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "sim" / "render"
THREE = "https://raw.githubusercontent.com/mrdoob/three.js/r160/examples/jsm/"
KHRONOS = "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/"
ROCKETBOX = "https://raw.githubusercontent.com/microsoft/Microsoft-Rocketbox/0943055db6ec570bcef9f2c8b41c9e5467c808f9/"
OBJAVERSE = "https://huggingface.co/datasets/allenai/objaverse/resolve/main/"
# Real bicycle meshes (the schematic one is never detected by YOLO). CC BY 4.0, attribution in BICYCLE_NOTICE.
BICYCLES = {"bicycle-1.glb": "glbs/000-054/99d6dce2e49e4ba185ac108ab044524d.glb",
            "bicycle-2.glb": "glbs/000-039/17ab00cb733443a2b552a2b620a68087.glb"}
BICYCLE_NOTICE = """# Bicycle models (Objaverse, CC BY 4.0)

- bicycle-1.glb: "Bike Ardis Verona 28\\"" by oksana_grym,
  https://sketchfab.com/3d-models/99d6dce2e49e4ba185ac108ab044524d
- bicycle-2.glb: "Old Bicycle" by Tidominer,
  https://sketchfab.com/3d-models/17ab00cb733443a2b552a2b620a68087

Licence: Creative Commons Attribution 4.0, https://creativecommons.org/licenses/by/4.0/
Retrieved through the Objaverse archive (https://huggingface.co/datasets/allenai/objaverse).
Used unmodified apart from runtime scaling/placement in the renderer.
"""


def fetch(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        print("get", path.name, flush=True)
        temporary = path.with_suffix(path.suffix + ".download")
        urllib.request.urlretrieve(url, temporary)
        temporary.replace(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    files = {
        "vendor/loaders/GLTFLoader.js": THREE + "loaders/GLTFLoader.js",
        "vendor/loaders/RGBELoader.js": THREE + "loaders/RGBELoader.js",
        "vendor/loaders/KTX2Loader.js": THREE + "loaders/KTX2Loader.js",
        "vendor/loaders/FBXLoader.js": THREE + "loaders/FBXLoader.js",
        "vendor/loaders/TGALoader.js": THREE + "loaders/TGALoader.js",
        "vendor/libs/fflate.module.js": THREE + "libs/fflate.module.js",
        "vendor/curves/NURBSCurve.js": THREE + "curves/NURBSCurve.js",
        "vendor/curves/NURBSUtils.js": THREE + "curves/NURBSUtils.js",
        "vendor/utils/BufferGeometryUtils.js": THREE + "utils/BufferGeometryUtils.js",
        "vendor/utils/SkeletonUtils.js": THREE + "utils/SkeletonUtils.js",
        "vendor/utils/WorkerPool.js": THREE + "utils/WorkerPool.js",
        "vendor/libs/basis/basis_transcoder.js": THREE + "libs/basis/basis_transcoder.js",
        "vendor/libs/basis/basis_transcoder.wasm": THREE + "libs/basis/basis_transcoder.wasm",
        "vendor/libs/basis/README.md": THREE + "libs/basis/README.md",
        "vendor/libs/ktx-parse.module.js": THREE + "libs/ktx-parse.module.js",
        "vendor/libs/zstddec.module.js": THREE + "libs/zstddec.module.js",
        "vendor/LICENSE": "https://raw.githubusercontent.com/mrdoob/three.js/r160/LICENSE",
        "assets/human.glb": KHRONOS + "CesiumMan/glTF-Binary/CesiumMan.glb",
        "assets/human-LICENSE.md": KHRONOS + "CesiumMan/README.md",
        "assets/human-alt.glb": "https://raw.githubusercontent.com/BabylonJS/Assets/master/meshes/HVGirl.glb",
        "assets/human-alt-LICENSE.md": "https://raw.githubusercontent.com/BabylonJS/Assets/master/README.md",
        "assets/Babylon-LICENSE": "https://raw.githubusercontent.com/BabylonJS/Assets/master/LICENSE",
        "assets/car.glb": KHRONOS + "CarConcept/GLB/CarConcept.glb",
        "assets/car-LICENSE.md": KHRONOS + "CarConcept/README.md",
        "assets/Cesium-mark-LICENSE.txt": KHRONOS.replace("Models/", "LICENSES/") + "LicenseRef-LegalMark-Cesium.txt",
        "assets/Khronos-mark-LICENSE.txt": KHRONOS.replace("Models/", "LICENSES/") + "LicenseRef-LegalMark-Khronos.txt",
        "assets/rocketbox/human.fbx": ROCKETBOX + "Assets/Avatars/Adults/Male_Adult_04/Export/Male_Adult_04.fbx",
        "assets/rocketbox/walk.fbx": ROCKETBOX + "Assets/Animations/all_animations_max_motextr_xy/m_walk_neutral_01.max.fbx",
        "assets/rocketbox/LICENSE.md": ROCKETBOX + "LICENSE.md",
    }
    for texture in ("body_color", "body_normal", "body_specular", "head_color", "head_normal", "head_specular", "opacity_color"):
        name = f"m006_{texture}.tga"
        files["assets/rocketbox/" + name] = ROCKETBOX + "Assets/Avatars/Adults/Male_Adult_04/Textures/" + name
    for channel, local in (("diff", "asphalt.jpg"), ("nor_gl", "asphalt-normal.jpg"), ("rough", "asphalt-rough.jpg")):
        files["assets/" + local] = f"https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/asphalt_02/asphalt_02_{channel}_1k.jpg"
    files["assets/sky.hdr"] = "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/kloppenheim_06_puresky_1k.hdr"
    for local, path in BICYCLES.items():
        files["assets/" + local] = OBJAVERSE + path
    manifest_path = RENDER / "assets" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    for name, record in manifest.items():
        files.setdefault(name, record["url"])
    for name, url in files.items():
        expected = manifest.get(name, {})
        destination = (RENDER / name).resolve()
        if not destination.is_relative_to(RENDER.resolve()):
            raise ValueError(f"asset path escapes the renderer: {name}")
        digest = fetch(expected.get("url", url), destination)
        if expected.get("sha256") and digest != expected["sha256"]:
            raise ValueError(f"asset checksum mismatch: {name}; do not silently change the measured bundle")
        manifest[name] = {"url": expected.get("url", url), "sha256": digest}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (RENDER / "assets" / "bicycle-LICENSE.md").write_text(BICYCLE_NOTICE, encoding="utf-8")
    print("ready:", RENDER)


if __name__ == "__main__":
    main()
