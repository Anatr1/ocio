# Open priorities

## CLOSED (2026-10-10, team decision): kerb-waiting detection at the real crosswalk
Not testable with the only site clip (kerbs out of view). Accepted: verified in the simulator; expected to work with a camera that sees the kerbs.
In the first site recording (`configs/site.yaml`), only 8 of the 11 stripes are in view: a cut stripe at the left edge,
then 7 full ones, the last of them just before the pole. **Neither kerb is visible.** Calibration covers the 6 fully
visible stripes, so counting works, but people waiting at either kerb are never seen. The approach/waiting rules
(B1, S1 on demand) cannot fire from the camera.

Fix options, best first:
1. **Re-place the camera** so both kerbs and at least 2 m of pavement on each side are in view: higher, further back,
   or turned along the zebra. Needs a new recording.
2. **Extend the calibration to the full 11-stripe zebra** (corners off-screen). This places the kerbs correctly in
   ground coordinates, but people standing there are still outside the image.
3. **Accept it for the demo** and use the push-button/Call for pedestrian demand. Waiting detection is then shown only
   in the simulator.
