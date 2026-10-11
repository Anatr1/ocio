# Renderer Assets And Measurements

All downloaded binary assets/addons stay out of Git. `tools/fetch_sim_assets.py`
recreates the bundle from `render/assets/manifest.json`, checks recorded SHA256s,
and downloads licence notices alongside the assets. The renderer verifies the
bundle before running. Keep these notices with any redistribution. Changes to
materials, camera, illumination and height scaling are recorded by the run hashes.

| Asset | Attribution / licence | Use / measured recall |
|---|---|---|
| Rocketbox Male Adult 04 + neutral walk | Microsoft, MIT; pinned `0943055db6ec570bcef9f2c8b41c9e5467c808f9` | Default textured rigged person, **not a photogrammetry scan**; corrected-texture spike 19/50 person boxes (38%) |
| CesiumMan | Cesium, CC BY 4.0, plus Cesium trademark notice | Earlier rigged sample spike 3/50 (6%) |
| HVGirl | Babylon.js Assets contributors, CC BY 4.0 repository licence | Earlier rigged sample spike 9/50 (18%) |
| Dima scan | in3D, archived individual CC BY licence; Objaverse UID `3a606acdfbe04478b0ab8dfe0f1de978` | Static scan, **no skeleton/gait**; spike 17/50 (34%); optional alternative, not default |
| CarConcept | Eric Chadwick / Darmstadt Graphics Group, CC BY 4.0; original Unity Fan CC0 base; Khronos trademark notice | PBR concept car, not production-car variety; corrected-texture spike 34/35 (97.1%) |
| Asphalt 02 / Kloppenheim 06 Pure Sky | Poly Haven, CC0 | PBR road and HDRI; lighting conditions provisional |
| Three.js r160 addons | Three.js contributors, MIT; bundled Basis Universal Apache 2.0; retain bundled notices | GPU render, FBX/glTF/TGA loading, skin cloning |
| Bicycles: "Bike Ardis Verona 28\"" (oksana_grym), "Old Bicycle" (Tidominer) | Sketchfab via Objaverse, CC BY 4.0; notice in `assets/bicycle-LICENSE.md` | Real meshes with the rigged person as rider (walk clip, not a cycling pose). 25 zebra frames: YOLO11n finds the bicycle in 1 at 320 px, 9 at 640; YOLO11x in 23 at 640, so the asset is recognisable and the board model's resolution is the limit. Rider found as person in 19/25 |
| Scooters, accessories | Repository-authored schematic geometry | **Not realistic detector assets** |

Spikes use 50 frames at 5 fps, YOLO11n ONNX 320, confidence >=0.35, IoU >=0.5,
visible instance-mask boxes, seed 0, unsignalised detector-only trajectories.
These asset comparisons used the earlier 78-degree virtual camera; the ten-case
closed-loop board-config run uses 70 degrees. They are not paired real-data G2.

Rocketbox initially rendered black because its FBX diffuse tint is zero despite
valid texture maps. That broken state scored 60% (Phong) / 54% (PBR). **Do not
present those numbers as textured-person realism.** After correcting the tint,
person recall is 38% in the spike. This is a useful limitation, not a hidden pass.

The closed-loop ten-case results are in `runs/suite-l2/results.json`: person recall
is 36.5% for single A>B, 43.9% B>A, 10.3% child, 59.2% elderly, and 14.8% night
(medium boxes). Counting sometimes succeeds with intermittent detections.

Primary sources:

- [Microsoft Rocketbox and import notes](https://github.com/microsoft/Microsoft-Rocketbox), [MIT licence](https://raw.githubusercontent.com/microsoft/Microsoft-Rocketbox/master/LICENSE.md).
- [CarConcept attribution](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/CarConcept), [CesiumMan attribution](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/CesiumMan).
- [Babylon.js asset licence](https://github.com/BabylonJS/Assets/blob/master/README.md).
- [Objaverse public archive](https://huggingface.co/datasets/allenai/objaverse), [Dima by in3D](https://sketchfab.com/3d-models/3a606acdfbe04478b0ab8dfe0f1de978). The manifest preserves per-object author/licence metadata.
- [Poly Haven asset licence](https://polyhaven.com/license).

Renderpeople was **not used**: its [terms, sections 2.5 and 4.2(a)](https://renderpeople.com/general-terms-and-conditions/)
also cover freebies and require explicit written consent for computer-vision
research/simulation. The handoff's suggested free sample is not a blanket CV licence.
Mixamo was not used; the current animation is the MIT Rocketbox clip.
