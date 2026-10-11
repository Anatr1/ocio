# Photoreal simulator background refresh

The L2 pixel renderer uses its own generic contemporary urban setting. It does not
use the digital twin's Crocetta architecture, shutters, balconies, foliage or colour
theme. The road, crossing dimensions, actor assets, camera defaults and World
behaviour are retained.

`sim/render/context.js` adds concrete, stone-panel and brick buildings with
metre-scaled surface grain, mortar and rain staining. Window openings have real
depth, recessed reflective glazing, frames, sills and varied blinds/curtains.
Simple entrances, parapets, downpipes and rooftop equipment complete the buildings.
The original block positions, widths, depths and wall heights are retained; the
small new façade and roof details are outside the traffic and waiting areas.

All 20 buildings in the default scene are batched into 15 meshes. Textures and room
variation are generated locally and deterministically, without consuming the
World's random stream. No new downloaded assets are required.

The existing CC0 Poly Haven sky HDRI is now visible in the camera instead of a flat
colour. Dusk, low-sun, rain, fog and night variants retain its cloud structure with
condition-specific colours and contrast. Some windows are illuminated at night.
These are illustrative sky variants, not calibrated atmospheric or lighting models;
the existing lighting/sensor limitations in `sim/DIVERGENCES.md` still apply.

The new module is included in the render-cache code fingerprint, so old cached
frames cannot be mistaken for the refreshed renderer.

## Ground-truth pose regression

Before each instance-mask pass, the renderer now explicitly refreshes the animated
skeleton matrices. Three.js r160 can otherwise reuse the previous RGB shadow pass's
skeleton upload when processing the next mask. Background HDR conversion changes
when this cache issue appears, which exposed it during the before/after comparison.
This corrects the labels' pose timing without changing actor assets or trajectories.

The GPU regression renders a pedestrian, cyclist and two cars, then renders the same
snapshot again after the initial sky conversion has settled. Its masks must match
exactly. The new assertion failed before the skeleton refresh and passed afterward.

## Verification — 2026-10-11

- JavaScript syntax checks pass for `renderer.js` and `context.js`.
- Full suite with the opt-in Chrome GPU test enabled: **94 passed**. This includes
  projection, instance masks, motion, dependency hashes and mobile sizing.
- A 30-frame scripted comparison against master retained identical World snapshots
  in all frames, with pedestrians, a cyclist and cars visible throughout. Camera
  corner projection error remained below one pixel.
- Day, dusk, low-sun, night, rain and fog previews loaded without JavaScript or HTTP
  errors. Their masks contained only background and actual actor IDs. Default and
  additional street-level preview cameras were visually inspected.

Local screenshots and diagnostic reports are under `runs/visual-review/` in the
worktree. No new counting-accuracy, detection-quality or board-performance figures
are claimed by this visual change.

To run all checks, including the optional GPU test, in PowerShell:

```powershell
$env:SIM_RENDER_TEST = '1'
$env:SIM_BROWSER = 'chrome'
& C:/Users/fedem/.venvs/hackturin/Scripts/python.exe -m pytest -q tests --basetemp=runs/render-context-tests
node --check sim/render/context.js
node --check sim/render/renderer.js
```

Use the usual `tools/sim_run.py` entry point to see the new background with the real
detector. The licensed local bundle is recreated by `tools/fetch_sim_assets.py`.
