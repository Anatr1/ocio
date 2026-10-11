"""Road-user taxonomy: fine detector classes -> coarse kinds, rider fusion, physical dimensions."""
from __future__ import annotations

from .detectors.base import Detection

# fine class -> (kind, display subclass)
CLASS_MAP = {
    "person": ("pedestrian", "pedestrian"),
    "pedestrian": ("pedestrian", "pedestrian"),
    "wheelchair": ("pedestrian", "wheelchair"),
    "stroller": ("pedestrian", "stroller"),
    "bicycle": ("bicycle", "bicycle"),
    "cyclist": ("bicycle", "bicycle"),
    "e-scooter": ("micromobility", "e-scooter"),
    "scooter": ("micromobility", "e-scooter"),
    "motorcycle": ("vehicle", "motorcycle"),
    "car": ("vehicle", "car"),
    "van": ("vehicle", "car"),
    "bus": ("vehicle", "bus"),
    "truck": ("vehicle", "truck"),
}

KINDS = ("pedestrian", "bicycle", "micromobility", "vehicle")
VRU_KINDS = ("pedestrian", "bicycle", "micromobility")  # vulnerable road users

# length (along heading), width, height in metres - used for BEV footprints, PET and the 3D twin
DIMS = {
    "pedestrian": (0.5, 0.5, 1.7),
    "wheelchair": (1.1, 0.7, 1.3),
    "stroller": (1.0, 0.6, 1.1),
    "bicycle": (1.8, 0.6, 1.7),
    "e-scooter": (1.1, 0.5, 1.75),
    "motorcycle": (2.1, 0.8, 1.5),
    "car": (4.4, 1.8, 1.5),
    "bus": (12.0, 2.55, 3.2),
    "truck": (8.0, 2.5, 3.3),
}

# distance (m) between the bottom-centre-of-box ground point and the object's centre, along the
# viewing ray: the bottom of a car's box is its near edge, not its centre.
FOOT_OFFSET = {"pedestrian": 0.12, "wheelchair": 0.3, "stroller": 0.3, "bicycle": 0.3, "e-scooter": 0.2,
               "motorcycle": 0.4, "car": 1.0, "bus": 1.3, "truck": 1.3}


def kind_of(cls: str) -> str:
    return CLASS_MAP.get(cls, ("other", cls))[0]


def subclass_of(cls: str) -> str:
    return CLASS_MAP.get(cls, (None, cls))[1]


def _overlap(a: Detection, b: Detection) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    return ix * iy


def fuse_riders(dets: list[Detection]) -> list[Detection]:
    """Merge 'person' detections riding a bicycle / motorcycle into a single road user.

    Without this, every cyclist is double-counted as a pedestrian + a bicycle.
    """
    persons = [d for d in dets if d.cls in ("person", "pedestrian")]
    rides = [d for d in dets if d.cls in ("bicycle", "motorcycle", "e-scooter", "scooter")]
    if not persons or not rides:
        for d in dets:
            d.kind = kind_of(d.cls)
        return dets
    used = set()
    for r in sorted(rides, key=lambda d: -d.score):
        best, best_score = None, 0.0
        for i, p in enumerate(persons):
            if i in used:
                continue
            inter = _overlap(p, r)
            if inter <= 0:
                continue
            frac_p = inter / max(p.w * p.h, 1e-6)
            cx = (p.x1 + p.x2) / 2
            centred = r.x1 - 0.15 * r.w <= cx <= r.x2 + 0.15 * r.w
            # rider's feet are within the vehicle's vertical extent; rider's head is above it
            feet_ok = r.y1 - 0.1 * r.h <= p.y2 <= r.y2 + 0.15 * r.h
            score = frac_p * (1.0 if centred else 0.4) * (1.0 if feet_ok else 0.5)
            if score > best_score:
                best, best_score = i, score
        if best is not None and best_score >= 0.18:
            p = persons[best]
            used.add(best)
            r.ridden = True
            r.extra["rider_box"] = [p.x1, p.y1, p.x2, p.y2]
            # keep the vehicle's ground contact, but the union box for height/visuals
            r.y1 = min(r.y1, p.y1)
            r.x1, r.x2 = min(r.x1, p.x1), max(r.x2, p.x2)
            r.score = max(r.score, p.score)
    out = []
    for i, p in enumerate(persons):
        if i not in used:
            out.append(p)
    person_ids = {id(p) for p in persons}
    out.extend(d for d in dets if id(d) not in person_ids)
    for d in out:
        d.kind = kind_of(d.cls)
    return out
