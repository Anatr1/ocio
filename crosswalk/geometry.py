"""Geometry: homographies, pinhole camera model, ground-plane helpers.

Conventions
-----------
* ``H_i2w`` maps image pixels (u, v) to ground-plane world metres (X, Y) - the one used at runtime.
* ``H_w2i`` is its inverse.
* Camera rotation ``R`` / translation ``t`` map world -> camera (OpenCV: x right, y down, z forward).
"""
from __future__ import annotations

import math

import numpy as np


# --------------------------------------------------------------------------- homographies
def apply_h(H: np.ndarray, pts) -> np.ndarray:
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    p = np.hstack([pts, np.ones((len(pts), 1))]) @ np.asarray(H, dtype=np.float64).T
    w = p[:, 2:3]
    w = np.where(np.abs(w) < 1e-12, 1e-12, w)
    return p[:, :2] / w


def _normalize_pts(pts: np.ndarray):
    c = pts.mean(axis=0)
    d = np.sqrt(((pts - c) ** 2).sum(axis=1)).mean()
    s = math.sqrt(2) / max(d, 1e-12)
    T = np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1]])
    return T, apply_h(T, pts)


def homography_dlt(src, dst) -> np.ndarray:
    """Normalised DLT homography src->dst from >= 4 correspondences (least squares)."""
    src = np.asarray(src, dtype=np.float64).reshape(-1, 2)
    dst = np.asarray(dst, dtype=np.float64).reshape(-1, 2)
    if len(src) < 4 or len(src) != len(dst):
        raise ValueError("need >= 4 matching points")
    Ts, s = _normalize_pts(src)
    Td, d = _normalize_pts(dst)
    A = []
    for (x, y), (u, v) in zip(s, d):
        A.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        A.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, _, Vt = np.linalg.svd(np.asarray(A))
    Hn = Vt[-1].reshape(3, 3)
    H = np.linalg.inv(Td) @ Hn @ Ts
    return H / H[2, 2]


def h_jacobian(H: np.ndarray, u: float, v: float) -> np.ndarray:
    """d(world)/d(pixel) of homography H at pixel (u, v) -> 2x2."""
    x = H @ np.array([u, v, 1.0])
    w = x[2]
    X, Y = x[0] / w, x[1] / w
    return np.array(
        [
            [H[0, 0] - X * H[2, 0], H[0, 1] - X * H[2, 1]],
            [H[1, 0] - Y * H[2, 0], H[1, 1] - Y * H[2, 1]],
        ]
    ) / w


def reprojection_error(H_i2w, img_pts, world_pts) -> float:
    p = apply_h(H_i2w, img_pts)
    return float(np.sqrt(((p - np.asarray(world_pts, float)) ** 2).sum(axis=1)).mean())


# --------------------------------------------------------------------------- camera
def intrinsics(width: int, height: int, focal_px: float | None = None, hfov_deg: float = 70.0) -> np.ndarray:
    if not focal_px:
        focal_px = (width / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    return np.array([[focal_px, 0, width / 2.0], [0, focal_px, height / 2.0], [0, 0, 1.0]])


def estimate_focal(H_w2i: np.ndarray, cx: float, cy: float, width: int) -> float | None:
    """Focal length (px) from a world-plane->image homography, assuming square pixels and a known
    principal point (Zhang's constraints r1.r2 = 0, |r1| = |r2|). Returns None when ill-conditioned."""
    T = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1.0]])
    G = T @ H_w2i
    G = G / np.linalg.norm(G)
    h1, h2 = G[:, 0], G[:, 1]
    a1, b1 = h1[0] * h2[0] + h1[1] * h2[1], h1[2] * h2[2]
    a2, b2 = h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2, h1[2] ** 2 - h2[2] ** 2
    den = a1 * a1 + a2 * a2
    if den < 1e-18:
        return None
    x = -(a1 * b1 + a2 * b2) / den
    if x <= 0:
        return None
    f = 1.0 / math.sqrt(x)
    if not (0.25 * width < f < 6.0 * width):
        return None
    return f


class Camera:
    """Pinhole camera with world->camera extrinsics."""

    def __init__(self, K: np.ndarray, R: np.ndarray, t: np.ndarray, width: int, height: int):
        self.K = np.asarray(K, dtype=np.float64)
        self.R = np.asarray(R, dtype=np.float64)
        self.t = np.asarray(t, dtype=np.float64).reshape(3)
        self.width, self.height = int(width), int(height)

    # ---- construction
    @classmethod
    def look_at(cls, position, target, width=640, height=480, hfov_deg=70.0, focal_px=None):
        C = np.asarray(position, dtype=np.float64)
        f = np.asarray(target, dtype=np.float64) - C
        f /= np.linalg.norm(f)
        up = np.array([0.0, 0.0, 1.0])
        right = np.cross(f, up)
        if np.linalg.norm(right) < 1e-9:  # looking straight down
            right = np.array([0.0, -1.0, 0.0])
        right /= np.linalg.norm(right)
        down = np.cross(f, right)
        R = np.vstack([right, down, f])
        t = -R @ C
        return cls(intrinsics(width, height, focal_px, hfov_deg), R, t, width, height)

    @classmethod
    def from_ground_homography(cls, H_i2w, width, height, focal_px=None, hfov_deg=70.0, estimate=True):
        """Recover the camera pose from the ground homography. Returns (camera, info)."""
        H_w2i = np.linalg.inv(H_i2w)
        info = {"focal_source": "given" if focal_px else "fov"}
        if not focal_px and estimate:
            f = estimate_focal(H_w2i, width / 2.0, height / 2.0, width)
            if f:
                focal_px = f
                info["focal_source"] = "estimated"
        K = intrinsics(width, height, focal_px, hfov_deg)
        B = np.linalg.inv(K) @ H_w2i
        lam = 2.0 / (np.linalg.norm(B[:, 0]) + np.linalg.norm(B[:, 1]))
        if B[2, 2] * lam < 0:  # world origin must be in front of the camera
            lam = -lam
        r1, r2, tt = lam * B[:, 0], lam * B[:, 1], lam * B[:, 2]
        r3 = np.cross(r1, r2)
        U, _, Vt = np.linalg.svd(np.column_stack([r1, r2, r3]))
        R = U @ Vt
        if np.linalg.det(R) < 0:
            R = -R
        cam = cls(K, R, tt, width, height)
        info["focal_px"] = float(K[0, 0])
        info["hfov_deg"] = float(math.degrees(2 * math.atan(width / 2.0 / K[0, 0])))
        info["center"] = cam.center.tolist()
        info["mirrored"] = bool(cam.center[2] < 0)
        return cam, info

    # ---- properties
    @property
    def center(self) -> np.ndarray:
        return -self.R.T @ self.t

    @property
    def forward(self) -> np.ndarray:
        return self.R[2]

    @property
    def H_w2i(self) -> np.ndarray:
        # not normalised by H[2,2]: keeping the sign makes w = depth > 0 for points in front of the camera
        return self.K @ np.column_stack([self.R[:, 0], self.R[:, 1], self.t])

    @property
    def H_i2w(self) -> np.ndarray:
        return np.linalg.inv(self.H_w2i)

    @property
    def tilt_deg(self) -> float:
        """Angle below the horizon of the optical axis."""
        f = self.forward
        return float(math.degrees(math.asin(-f[2])))

    # ---- projection
    def project(self, Xw) -> tuple[np.ndarray, np.ndarray]:
        Xw = np.asarray(Xw, dtype=np.float64).reshape(-1, 3)
        Xc = Xw @ self.R.T + self.t
        z = Xc[:, 2]
        zs = np.where(np.abs(z) < 1e-9, 1e-9, z)
        u = self.K[0, 0] * Xc[:, 0] / zs + self.K[0, 2]
        v = self.K[1, 1] * Xc[:, 1] / zs + self.K[1, 2]
        return np.column_stack([u, v]), z

    def height_from_box(self, foot_uv, top_v: float) -> float | None:
        """Metric height of an upright object whose ground contact projects to foot_uv and whose top
        is at image row top_v."""
        P = apply_h(self.H_i2w, [foot_uv])[0]
        a = self.R @ np.array([P[0], P[1], 0.0]) + self.t
        fy, cy = self.K[1, 1], self.K[1, 2]
        r2z, r3z = self.R[1, 2], self.R[2, 2]
        den = fy * r2z + cy * r3z - top_v * r3z
        if abs(den) < 1e-9:
            return None
        Z = (top_v * a[2] - fy * a[1] - cy * a[2]) / den
        return float(Z) if 0 < Z < 10 else None

    def ground_from_pixel(self, uv) -> np.ndarray:
        return apply_h(self.H_i2w, uv)

    def to_dict(self) -> dict:
        C = self.center
        f = self.forward
        return {
            "position": [float(x) for x in C],
            "forward": [float(x) for x in f],
            "up": [float(x) for x in -self.R[1]],
            "hfov_deg": float(math.degrees(2 * math.atan(self.width / 2.0 / self.K[0, 0]))),
            "vfov_deg": float(math.degrees(2 * math.atan(self.height / 2.0 / self.K[1, 1]))),
            "width": self.width,
            "height": self.height,
            "tilt_deg": self.tilt_deg,
        }


# --------------------------------------------------------------------------- 2D helpers
def point_in_poly(x: float, y: float, poly) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            xc = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < xc:
                inside = not inside
        j = i
    return inside


def rect_poly(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def crossing_time(ts, vals, level) -> float | None:
    """First time a sampled 1-D signal crosses ``level`` (linear interpolation)."""
    for i in range(1, len(ts)):
        a, b = vals[i - 1] - level, vals[i] - level
        if a == 0:
            return ts[i - 1]
        if a * b < 0:
            return ts[i - 1] + (ts[i] - ts[i - 1]) * (a / (a - b))
    return None


def wrap_angle(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi
