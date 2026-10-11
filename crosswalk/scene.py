"""Scene model: calibration (image <-> ground), camera pose, and the crosswalk zones in metres."""
from __future__ import annotations

import math

import numpy as np

from .classes import FOOT_OFFSET, subclass_of
from .geometry import Camera, apply_h, h_jacobian, homography_dlt, point_in_poly, rect_poly, reprojection_error


def default_world_points(W: float, L: float):
    """Crosswalk corners P1..P4 (see config docstring)."""
    return [(-W / 2, -L / 2), (W / 2, -L / 2), (W / 2, L / 2), (-W / 2, L / 2)]


class Scene:
    def __init__(self, scfg, image_size=None, tracker_cfg=None):
        self.cfg = scfg
        cw = scfg["crosswalk"]
        self.W = float(cw["width"])
        self.L = float(cw["length"])
        self.D = float(scfg.get("curb_depth", 2.5))
        self.A = float(scfg.get("approach", 25.0))
        self.sidewalk = float(scfg.get("sidewalk_width", 3.0))
        self.lanes = int(scfg.get("lanes", 2))
        self.speed_limit = float(scfg.get("speed_limit_kmh", 50.0)) / 3.6
        W, L, D, A = self.W, self.L, self.D, self.A
        self.crosswalk = rect_poly(-W / 2, -L / 2, W / 2, L / 2)
        self.curb_a = rect_poly(-W / 2 - 1.0, -L / 2 - D, W / 2 + 1.0, -L / 2)
        self.curb_b = rect_poly(-W / 2 - 1.0, L / 2, W / 2 + 1.0, L / 2 + D)
        self.road = rect_poly(-A, -L / 2, A, L / 2)
        margin = float((tracker_cfg or {}).get("world_margin", 6.0))
        self.bounds = (-A - margin, -L / 2 - D - self.sidewalk - margin, A + margin, L / 2 + D + self.sidewalk + margin)
        tc = tracker_cfg or {}
        self.pix_sigma = float(tc.get("pixel_sigma", 3.0))
        self.pix_sigma_rel = float(tc.get("pixel_sigma_rel", 0.04))
        self.min_sigma = float(tc.get("min_meas_sigma_m", 0.15))

        cal = scfg.get("calibration", {}) or {}
        self.image_size = tuple(image_size or cal.get("image_size") or (640, 480))
        self.H = None
        self.camera = None
        self.cal_info = {}
        self.set_calibration(cal)

    # ------------------------------------------------------------------ calibration
    def set_calibration(self, cal):
        H = cal.get("H")
        img_pts = cal.get("image_points")
        world_pts = cal.get("world_points") or (default_world_points(self.W, self.L) if img_pts else None)
        if H is not None:
            self.H = np.asarray(H, dtype=np.float64)
        elif img_pts:
            self.H = homography_dlt(img_pts, world_pts)
            self.cal_info["reproj_err_m"] = reprojection_error(self.H, img_pts, world_pts)
        else:
            self.H = None
            return
        w, h = self.image_size
        # the calibration may have been made at another resolution
        cw, ch = cal.get("image_size") or (w, h)
        if (cw, ch) != (w, h):
            S = np.diag([cw / w, ch / h, 1.0])
            self.H = self.H @ S
        self._normalize_sign(img_pts)
        cam, info = Camera.from_ground_homography(self.H, w, h, focal_px=cal.get("focal_px"),
                                                  hfov_deg=float(cal.get("hfov_deg", 70.0)))
        self.cal_info.update(info)
        if info.get("mirrored") and img_pts and not cal.get("H"):
            # point order was mirrored (camera ended up below ground): flip world X and recompute
            wp = [(-x, y) for (x, y) in world_pts]
            self.H = homography_dlt(img_pts, wp)
            self._normalize_sign(img_pts)
            cam, info = Camera.from_ground_homography(self.H, w, h, focal_px=cal.get("focal_px"),
                                                      hfov_deg=float(cal.get("hfov_deg", 70.0)))
            self.cal_info.update(info)
            self.cal_info["auto_flipped_x"] = True
        self.camera = cam
        self.cal_info["camera_height_m"] = float(cam.center[2])
        self.cal_info["tilt_deg"] = cam.tilt_deg

    def _normalize_sign(self, img_pts=None):
        """A homography is defined up to scale *and sign*. Make the homogeneous coordinate positive for visible
        ground pixels (calibration points, or the bottom-centre pixel) so that 'w > 0' means 'on the ground in
        front of the camera' everywhere (overlays, BEV texture, sensor footprint in the dashboard)."""
        if self.H is None:
            return
        if img_pts:
            u, v = np.mean(np.asarray(img_pts, dtype=np.float64), axis=0)
        else:
            u, v = self.image_size[0] / 2.0, self.image_size[1] * 0.95
        if float(self.H[2] @ np.array([u, v, 1.0])) < 0:
            self.H = -self.H

    @property
    def calibrated(self) -> bool:
        return self.H is not None

    # ------------------------------------------------------------------ zones
    def zone_of(self, x, y, margin=0.0) -> str:
        W, L, D = self.W, self.L, self.D
        if abs(x) <= W / 2 + margin and abs(y) <= L / 2:
            return "crosswalk"
        if abs(x) <= W / 2 + 1.0 + margin and -L / 2 - D <= y < -L / 2:
            return "curb_a"
        if abs(x) <= W / 2 + 1.0 + margin and L / 2 < y <= L / 2 + D:
            return "curb_b"
        if abs(y) <= L / 2 and abs(x) <= self.A:
            return "road"
        if abs(y) <= L / 2 + D + self.sidewalk:
            return "sidewalk"
        return "out"

    def in_crosswalk(self, x, y, margin=0.0) -> bool:
        return abs(x) <= self.W / 2 + margin and abs(y) <= self.L / 2

    def in_bounds(self, x, y) -> bool:
        x0, y0, x1, y1 = self.bounds
        return x0 <= x <= x1 and y0 <= y <= y1

    def in_poly(self, x, y, poly) -> bool:
        return point_in_poly(x, y, poly)

    # ------------------------------------------------------------------ projection of detections
    def localize(self, dets):
        """Attach ground position, covariance and metric height to detections (in place)."""
        if self.H is None:
            return dets
        cam_xy = self.camera.center[:2] if self.camera is not None else None
        for d in dets:
            u, v = d.foot
            P = apply_h(self.H, [(u, v)])[0]
            J = h_jacobian(self.H, u, v)
            su = self.pix_sigma + 0.5 * self.pix_sigma_rel * d.h
            sv = self.pix_sigma + self.pix_sigma_rel * d.h
            cov = J @ np.diag([su * su, sv * sv]) @ J.T + np.eye(2) * self.min_sigma ** 2
            sub = subclass_of(d.cls)
            fitted = None
            if self.camera is not None and sub in ("car", "bus", "truck") and self.fit_vehicles:
                fitted = self._fit_vehicle_box(d, P, sub)
            if fitted is not None:
                P = fitted
            else:
                off = FOOT_OFFSET.get(sub, 0.0)
                if cam_xy is not None and off > 0:
                    ray = P - cam_xy
                    n = np.linalg.norm(ray)
                    if n > 1e-6:
                        P = P + ray / n * off
            d.world = (float(P[0]), float(P[1]))
            if sub in ("car", "bus", "truck"):
                cov = cov + np.eye(2) * 0.45 ** 2  # footprint-centre uncertainty of a large object
            d.cov = cov
            if self.camera is not None and fitted is None:
                d.height_m = self.camera.height_from_box((u, v), d.y1)
        return dets

    fit_vehicles = True

    def _project_box(self, X, Y, dims, heading=0.0):
        L, W, H = dims
        c, s = math.cos(heading), math.sin(heading)
        pts = []
        for z in (0.0, H):
            for dx, dy in ((L / 2, W / 2), (L / 2, -W / 2), (-L / 2, -W / 2), (-L / 2, W / 2)):
                pts.append((X + c * dx - s * dy, Y + s * dx + c * dy, z))
        uv, zc = self.camera.project(pts)
        if (zc <= 0.2).any():
            return None
        return uv[:, 0].min(), uv[:, 0].max(), uv[:, 1].max()

    def _fit_vehicle_box(self, d, P0, sub):
        """Road vehicles are (almost always) aligned with the road axis and have known dimensions: solve for
        the footprint centre whose projected 3D box best explains the detection's left/right/bottom edges.
        Fixes the 1-2 m lateral bias of the plain bottom-centre point for vehicles seen at an angle."""
        from .classes import DIMS

        dims = DIMS.get(sub, DIMS["car"])
        meas = np.array([d.x1, d.x2, d.y2])
        w = np.array([1.0, 1.0, 2.0])  # bottom edge is the most reliable
        # left/right edges are unreliable when the box is cut by the image border
        if d.x1 <= 2:
            w[0] = 0.0
        if d.x2 >= self.image_size[0] - 3:
            w[1] = 0.0
        if d.y2 >= self.image_size[1] - 3:
            return None
        X = np.array(P0, dtype=np.float64)
        # start from the centre: push the near-edge point away from the camera by half the width
        cam = self.camera.center[:2]
        ray = X - cam
        n = np.linalg.norm(ray)
        if n > 1e-6:
            X = X + ray / n * dims[1] * 0.5
        eps = 0.05
        for _ in range(6):
            f0 = self._project_box(X[0], X[1], dims)
            if f0 is None:
                return None
            r = (np.array(f0) - meas) * w
            Jm = np.zeros((3, 2))
            for k in range(2):
                Xe = X.copy()
                Xe[k] += eps
                fe = self._project_box(Xe[0], Xe[1], dims)
                if fe is None:
                    return None
                Jm[:, k] = (np.array(fe) - np.array(f0)) * w / eps
            try:
                step, *_ = np.linalg.lstsq(Jm, -r, rcond=None)
            except np.linalg.LinAlgError:
                return None
            step = np.clip(step, -2.0, 2.0)
            X = X + step
            if np.abs(step).max() < 0.01:
                break
        if np.linalg.norm(X - P0) > 6.0:
            return None
        return X

    def world_to_image(self, pts):
        if self.H is None:
            return None
        return apply_h(np.linalg.inv(self.H), pts)

    def image_polys(self) -> dict:
        """Zone polygons projected into the image (for overlays). Only the part in front of the camera."""
        if self.H is None:
            return {}
        out = {}
        for name, poly in (("crosswalk", self.crosswalk), ("curb_a", self.curb_a), ("curb_b", self.curb_b)):
            dense = _densify(poly, 0.5)
            pts = self.world_to_image(dense)
            out[name] = pts
        # road edges for context
        return out

    def to_dict(self) -> dict:
        d = {
            "crosswalk": {"width": self.W, "length": self.L},
            "curb_depth": self.D,
            "approach": self.A,
            "sidewalk_width": self.sidewalk,
            "lanes": self.lanes,
            "speed_limit_kmh": self.speed_limit * 3.6,
            "stripe": dict(self.cfg.get("stripe", {"width": 0.5, "gap": 0.5})),
            "zones": {
                "crosswalk": self.crosswalk,
                "curb_a": self.curb_a,
                "curb_b": self.curb_b,
                "road": self.road,
            },
            "bounds": self.bounds,
            "calibrated": self.calibrated,
            "calibration": {k: (v if not isinstance(v, np.ndarray) else v.tolist()) for k, v in self.cal_info.items()},
        }
        if self.camera is not None:
            d["camera"] = self.camera.to_dict()
        if self.H is not None:
            d["H"] = self.H.tolist()
        return d


def _densify(poly, step):
    out = []
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        k = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        for j in range(k):
            out.append((x0 + (x1 - x0) * j / k, y0 + (y1 - y0) * j / k))
    return out
