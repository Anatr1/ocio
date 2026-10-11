"""The simulator uses the site's recovered camera when calibration exists."""
from crosswalk.geometry import Camera
from crosswalk.scene import Scene


def camera_for_config(cfg, width, height):
    scene = Scene(cfg.scene, (width, height), cfg.tracker)
    if scene.calibrated:
        return scene.camera, scene
    sim = cfg.get("sim", {})
    camera = Camera.look_at(sim.get("camera_pos") or [-scene.W / 2 - 7, -scene.L / 2 - scene.D - 1.5, 5.5],
                            sim.get("camera_target") or [3, 0.5, 0], width, height,
                            hfov_deg=float(sim.get("hfov_deg", cfg.scene.calibration.get("hfov_deg", 78))))
    return camera, scene
