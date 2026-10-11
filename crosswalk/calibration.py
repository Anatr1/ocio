"""Calibration helpers: zebra-stripe auto-detection, corner ordering, config update.

Zebra crossings are a free calibration target: the stripes are a standard size (in Italy 50 cm wide, parallel to
the road axis), so the four outer corners of the stripe block give the image->ground homography and, through
Zhang's constraints, even the camera focal length, height and tilt - no checkerboard, no ladder.
"""
from __future__ import annotations

import math

import cv2
import numpy as np


def detect_stripes(frame, min_area_frac=0.0004, max_area_frac=0.08):
    """Find bright, elongated quadrilateral blobs (zebra stripes). Returns list of dicts sorted by image y."""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    # white paint is much brighter than asphalt: top-hat + Otsu is robust to illumination gradients
    k = max(15, (min(h, w) // 12) | 1)
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    _, bw = cv2.threshold(tophat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        a = cv2.contourArea(c)
        if not (min_area_frac * w * h <= a <= max_area_frac * w * h):
            continue
        rect = cv2.minAreaRect(c)
        (cx, cy), (rw, rh), ang = rect
        if min(rw, rh) < 2:
            continue
        elong = max(rw, rh) / min(rw, rh)
        fill = a / max(rw * rh, 1)
        if elong < 2.0 or fill < 0.6:
            continue
        box = cv2.boxPoints(rect)
        # long-axis direction
        if rw >= rh:
            theta = math.radians(ang)
        else:
            theta = math.radians(ang + 90)
        out.append({"center": (cx, cy), "box": box, "area": a, "theta": theta % math.pi, "elong": elong,
                    "length": max(rw, rh), "width": min(rw, rh)})
    return out


def _angle_diff(a, b):
    return abs(math.degrees(math.atan2(math.sin(2 * (a - b)), math.cos(2 * (a - b)))) / 2)


def group_zebra(stripes, max_angle_deg=15):
    """Largest chain of stripes that look like a zebra: parallel, similar length and width, side by side
    (aligned along their long axis) and evenly spaced. Rejects curbs, stop lines and lane dashes."""
    best = []
    for s in stripes:
        d_long = np.array([math.cos(s["theta"]), math.sin(s["theta"])])
        d_perp = np.array([-d_long[1], d_long[0]])
        c0 = np.array(s["center"])
        cand = []
        for t in stripes:
            if _angle_diff(t["theta"], s["theta"]) > max_angle_deg:
                continue
            if not (0.5 <= t["length"] / s["length"] <= 2.0 and 0.4 <= t["width"] / s["width"] <= 2.5):
                continue
            rel = np.array(t["center"]) - c0
            if abs(rel @ d_long) > 0.6 * max(s["length"], t["length"]):  # side by side, not in a row
                continue
            cand.append((float(rel @ d_perp), t))
        cand.sort(key=lambda x: x[0])
        if len(cand) < 3:
            continue
        # longest run with consistent spacing
        pos = [p for p, _ in cand]
        for i in range(len(cand)):
            run = [cand[i]]
            gap = None
            for j in range(i + 1, len(cand)):
                g = pos[j] - run[-1][0]
                if g < 0.5 * s["width"]:
                    continue
                if gap is None:
                    if g > 6 * s["width"]:
                        break
                    gap = g
                elif not (0.6 * gap <= g <= 1.6 * gap):
                    break
                run.append(cand[j])
            if len(run) > len(best):
                best = [t for _, t in run]
    return best


def zebra_corners(stripes):
    """Order the 4 outer corners of a zebra as P1..P4 (crosswalk convention, curb A = nearest the camera).

    Stripes are parallel to the road axis (X); they are stacked across the road (Y). The stripe closest to the
    bottom of the image is taken as curb A.
    """
    if len(stripes) < 3:
        return None
    # stacking direction in the image: perpendicular to the mean stripe direction
    th = math.atan2(np.mean([math.sin(2 * s["theta"]) for s in stripes]), np.mean([math.cos(2 * s["theta"]) for s in stripes])) / 2
    d_long = np.array([math.cos(th), math.sin(th)])
    d_perp = np.array([-d_long[1], d_long[0]])
    if d_perp[1] < 0:  # point "down" the image (towards the camera)
        d_perp = -d_perp
    proj = [np.dot(np.array(s["center"]), d_perp) for s in stripes]
    order = np.argsort(proj)
    near = stripes[order[-1]]   # largest projection = lowest in image = nearest to the camera = curb A
    far = stripes[order[0]]
    centroid = np.mean([s["center"] for s in stripes], axis=0)

    def ends(s):
        """The stripe's long edge farther from the zebra centroid, endpoints sorted along the road axis."""
        box = np.asarray(s["box"])
        edges = [(box[i], box[(i + 1) % 4]) for i in range(4)]
        edges.sort(key=lambda e: -np.linalg.norm(e[1] - e[0]))
        long_edges = edges[:2]
        outer = max(long_edges, key=lambda e: np.linalg.norm((e[0] + e[1]) / 2 - centroid))
        edge = np.array(outer)
        return edge[np.argsort(edge @ d_long)]

    a = ends(near)   # outer edge of the nearest stripe (curb A side)
    b = ends(far)    # outer edge of the farthest stripe (curb B side)
    # P1 (-W/2,-L/2), P2 (+W/2,-L/2), P3 (+W/2,+L/2), P4 (-W/2,+L/2)
    pts = [a[0], a[1], b[1], b[0]]
    return [[float(p[0]), float(p[1])] for p in pts], len(stripes)


def auto_calibrate(frame):
    s = detect_stripes(frame)
    z = group_zebra(s)
    res = zebra_corners(z)
    if res is None:
        return None
    pts, n = res
    return {"image_points": pts, "n_stripes": n, "stripes": z}


def estimate_length(n_stripes, stripe_w=0.5, gap=0.5):
    """Painted block length (curb to curb, approx.) from the stripe count."""
    return n_stripes * stripe_w + (n_stripes - 1) * gap


def draw_calibration(img, scene, points=None, grid_step=1.0):
    """Overlay the metric grid of the calibrated ground plane + zones + clicked points."""
    out = img
    if scene is not None and scene.calibrated:
        Hinv = np.linalg.inv(scene.H)

        def P(x, y):
            p = Hinv @ np.array([x, y, 1.0])
            if p[2] <= 1e-9:
                return None
            return int(round(p[0] / p[2])), int(round(p[1] / p[2]))

        W, L, A = scene.W, scene.L, min(scene.A, 15)
        for x in np.arange(-A, A + 0.01, grid_step):
            a, b = P(x, -L / 2 - scene.D), P(x, L / 2 + scene.D)
            if a and b:
                cv2.line(out, a, b, (90, 90, 90) if abs(x) > W / 2 else (0, 200, 255), 1, cv2.LINE_AA)
        for y in np.arange(-L / 2 - scene.D, L / 2 + scene.D + 0.01, grid_step):
            a, b = P(-A, y), P(A, y)
            if a and b:
                cv2.line(out, a, b, (90, 90, 90), 1, cv2.LINE_AA)
        poly = [P(x, y) for x, y in scene.crosswalk]
        if all(poly):
            cv2.polylines(out, [np.array(poly, np.int32)], True, (0, 255, 255), 2, cv2.LINE_AA)
        o = P(0, 0)
        ax = P(2, 0)
        ay = P(0, 2)
        if o and ax and ay:
            cv2.arrowedLine(out, o, ax, (0, 0, 255), 2, tipLength=0.2)
            cv2.arrowedLine(out, o, ay, (0, 255, 0), 2, tipLength=0.2)
            cv2.putText(out, "X road", ax, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
            cv2.putText(out, "Y cross (to curb B)", ay, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
    for i, p in enumerate(points or []):
        q = (int(p[0]), int(p[1]))
        cv2.circle(out, q, 6, (0, 0, 255), 2, cv2.LINE_AA)
        cv2.putText(out, f"P{i + 1}", (q[0] + 8, q[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
    return out
