"""Debug overlay, privacy blur, and the bird's-eye-view (BEV) background texture for the 3D twin."""
from __future__ import annotations

import cv2
import numpy as np

COLORS = {  # BGR
    "pedestrian": (80, 200, 255),
    "bicycle": (80, 255, 120),
    "micromobility": (255, 120, 220),
    "vehicle": (255, 170, 60),
    "other": (180, 180, 180),
}


def pixelate(img, x1, y1, x2, y2, block=8):
    h, w = img.shape[:2]
    x1, y1, x2, y2 = max(0, int(x1)), max(0, int(y1)), min(w, int(x2)), min(h, int(y2))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return
    roi = img[y1:y2, x1:x2]
    sw, sh = max(1, (x2 - x1) // block), max(1, (y2 - y1) // block)
    small = cv2.resize(roi, (sw, sh), interpolation=cv2.INTER_LINEAR)
    img[y1:y2, x1:x2] = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)


def privacy_blur(frame, boxes_kinds):
    """Pixelate heads of people and the lowest 20 % of vehicles (number plates). In place."""
    for (x1, y1, x2, y2), kind in boxes_kinds:
        h = y2 - y1
        if kind in ("pedestrian", "bicycle", "micromobility"):
            pixelate(frame, x1, y1, x2, y1 + 0.38 * h, 6)
        elif kind == "vehicle":
            pixelate(frame, x1, y1 + 0.80 * h, x2, y2, 10)  # lower 20 %: the number plate band
    return frame


def draw_overlay(frame, scene, tracks, dets=None, hud=None, signal=None, roi=None):
    out = frame
    H, W = out.shape[:2]
    if roi:
        x, y, w, h = [int(v) for v in roi]
        cv2.rectangle(out, (x, y), (x + w, y + h), (90, 90, 90), 1)
    polys = scene.image_polys() if scene is not None and scene.calibrated else {}
    over = out.copy()
    for name, pts in polys.items():
        p = np.round(pts).astype(np.int32)
        if name == "crosswalk":
            cv2.fillPoly(over, [p], (255, 255, 255))
        else:
            cv2.fillPoly(over, [p], (120, 200, 255))
    cv2.addWeighted(over, 0.18, out, 0.82, 0, out)
    for name, pts in polys.items():
        p = np.round(pts).astype(np.int32)
        cv2.polylines(out, [p], True, (255, 255, 255) if name == "crosswalk" else (120, 200, 255), 1, cv2.LINE_AA)
    if dets:
        for d in dets:
            cv2.rectangle(out, (int(d.x1), int(d.y1)), (int(d.x2), int(d.y2)), (110, 110, 110), 1)
    Hinv = np.linalg.inv(scene.H) if scene is not None and scene.calibrated else None
    for tr in tracks:
        if tr.state != "confirmed":
            continue
        col = COLORS.get(tr.kind, COLORS["other"])
        x1, y1, x2, y2 = [int(v) for v in tr.bbox]
        cv2.rectangle(out, (x1, y1), (x2, y2), col, 2)
        label = f"{tr.id} {tr.subclass} {tr.speed * 3.6:.0f}km/h"
        cv2.putText(out, label, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, label, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, 1, cv2.LINE_AA)
        if Hinv is not None and len(tr.history) > 1:
            pts = np.array([[h[1], h[2]] for h in list(tr.history)[-40:]], dtype=np.float64)
            hp = np.hstack([pts, np.ones((len(pts), 1))]) @ Hinv.T
            ok = hp[:, 2] > 1e-6
            if ok.sum() > 1:
                ip = (hp[ok, :2] / hp[ok, 2:3]).round().astype(np.int32)
                cv2.polylines(out, [ip], False, col, 1, cv2.LINE_AA)
    if hud:
        y = 18
        for line in hud:
            cv2.putText(out, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(out, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            y += 18
    if signal is not None and signal.mode != "beacon":
        veh, ped = signal.veh_state(), signal.ped_state()
        cx = W - 24
        for i, c in enumerate(("red", "yellow", "green")):
            on = veh == c
            colr = {"red": (40, 40, 255), "yellow": (40, 220, 255), "green": (80, 255, 80)}[c]
            cv2.circle(out, (cx, 20 + i * 22), 9, colr if on else (60, 60, 60), -1, cv2.LINE_AA)
        pc = (80, 255, 80) if ped in ("green", "flash") else (40, 40, 255)
        cv2.rectangle(out, (cx - 30, 10), (cx - 16, 60), (30, 30, 30), -1)
        cv2.circle(out, (cx - 23, 35), 6, pc, -1, cv2.LINE_AA)
    return out


def bev_background(frame, scene, px_per_m=20.0, max_px_footprint_m=0.25):
    """Ortho-rectify the (person-free) background into a top-down RGBA texture covering scene.bounds."""
    x0, y0, x1, y1 = scene.bounds
    Wb, Hb = int((x1 - x0) * px_per_m), int((y1 - y0) * px_per_m)
    A = np.array([[1.0 / px_per_m, 0, x0], [0, -1.0 / px_per_m, y1], [0, 0, 1]])
    Hw2i = np.linalg.inv(scene.H)
    M = Hw2i @ A
    bev = cv2.warpPerspective(frame, M, (Wb, Hb), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    # validity: in front of the camera, inside the image, and not too blurry (pixel footprint)
    cols, rows = np.meshgrid(np.arange(Wb, dtype=np.float64), np.arange(Hb, dtype=np.float64))
    P = np.stack([cols.ravel(), rows.ravel(), np.ones(cols.size)])
    q = M @ P
    w = q[2]
    valid = w > 1e-9
    u = np.where(valid, q[0] / np.where(valid, w, 1), -1)
    v = np.where(valid, q[1] / np.where(valid, w, 1), -1)
    h, wi = frame.shape[:2]
    valid &= (u >= 0) & (u < wi - 1) & (v >= 0) & (v < h - 1)
    # footprint: ground metres per image pixel (from Jacobian of H_i2w) - large means blurry far field
    Hi = scene.H
    den = Hi[2, 0] * u + Hi[2, 1] * v + Hi[2, 2]
    den = np.where(np.abs(den) < 1e-9, 1e-9, den)
    X = (Hi[0, 0] * u + Hi[0, 1] * v + Hi[0, 2]) / den
    Y = (Hi[1, 0] * u + Hi[1, 1] * v + Hi[1, 2]) / den
    dXdv = (Hi[0, 1] - X * Hi[2, 1]) / den
    dYdv = (Hi[1, 1] - Y * Hi[2, 1]) / den
    foot = np.sqrt(dXdv ** 2 + dYdv ** 2)
    alpha = np.clip(1.0 - (foot - max_px_footprint_m) / (2 * max_px_footprint_m), 0.0, 1.0)
    alpha = np.where(valid, alpha, 0.0).reshape(Hb, Wb)
    rgba = cv2.cvtColor(bev, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = (alpha * 255).astype(np.uint8)
    return rgba, {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "px_per_m": px_per_m, "width": Wb, "height": Hb}
