"""IDM acceleration, social-force steering and oriented collision geometry."""
import math


PARAMETERS = {
    "adult_speed_mean": 1.35, "adult_speed_sd": 0.2,
    "elderly_speed_min": 0.6, "elderly_speed_max": 0.9,
    "relaxation_s": 0.5, "social_strength": 2.0, "social_range_m": 0.3,
    "idm_accel": 1.6, "idm_comfort_brake": 2.2, "idm_headway_s": 1.2,
    "idm_min_gap_m": 2.0, "emergency_brake": 8.0,
    "mobil_politeness": 0.3, "mobil_threshold": 0.2, "mobil_safe_brake": 4.0,
    # wrecks are removed after this many seconds (emergency services reopen the road), else one crash
    # blocks a continuous scenario forever
    "crash_clear_s": 60.0,
    # minimum time-to-arrival a cautious crosser accepts before stepping into a lane (the time needed to
    # clear that lane plus 1 s applies when it is longer)
    "lane_check_tta_s": 2.0,
}


def idm(speed, desired, gap=math.inf, leader_speed=0.0, params=None):
    p = {**PARAMETERS, **(params or {})}
    a, b = p["idm_accel"], p["idm_comfort_brake"]
    free = a * (1 - (speed / max(desired, 0.1)) ** 4)
    if math.isinf(gap):
        return free
    wanted = p["idm_min_gap_m"] + max(0.0, speed * p["idm_headway_s"] +
                                    speed * (speed - leader_speed) / (2 * math.sqrt(a * b)))
    return free - a * (wanted / max(gap, 0.1)) ** 2


def social_velocity(agent, target, neighbours, speed, dt, params):
    dx, dy = target[0] - agent.x, target[1] - agent.y
    distance = math.hypot(dx, dy)
    desired = min(speed, distance / max(dt, 1e-6))
    tx, ty = (dx / distance * desired, dy / distance * desired) if distance > 1e-6 else (0.0, 0.0)
    tau = max(0.1, params["relaxation_s"])
    ax, ay = (tx - agent.vx) / tau, (ty - agent.vy) / tau
    for other in neighbours:
        if other is agent or other.state == "leave" and agent.state == "to_curb":
            continue
        rx, ry = agent.x - other.x, agent.y - other.y
        # Repel from the vehicle's surface, not its centre (important beside buses).
        rectangular = other.kind == "vehicle"
        if rectangular:
            if math.hypot(rx, ry) > math.hypot(*other.dims[:2]) / 2 + 2.5:
                continue
            c, s = math.cos(other.heading), math.sin(other.heading)
            lx, ly = c * rx + s * ry, -s * rx + c * ry
            qx = max(-other.dims[0] / 2, min(other.dims[0] / 2, lx))
            qy = max(-other.dims[1] / 2, min(other.dims[1] / 2, ly))
            rx, ry = c * (lx - qx) - s * (ly - qy), s * (lx - qx) + c * (ly - qy)
        dist = math.hypot(rx, ry)
        if dist > 2.5:
            continue
        if dist < 1e-6:
            rx, ry, dist = (1.0 if agent.id > other.id else -1.0), 0.0, 1.0
        c, s = math.cos(agent.heading), math.sin(agent.heading)
        own_radius = (agent.dims[0] * abs(c * rx + s * ry) +
                      agent.dims[1] * abs(-s * rx + c * ry)) / (2 * dist)
        if agent.kind == "pedestrian" and agent.dims[0] == agent.dims[1]:
            own_radius = agent.dims[0] / 2
        radius = own_radius + (0 if rectangular else other.dims[1] / 2)
        force = params["social_strength"] * math.exp(min(5.0, (radius - dist) / params["social_range_m"]))
        ax += force * rx / dist
        ay += force * ry / dist
        if (agent.vx - other.vx) * rx + (agent.vy - other.vy) * ry < -0.1 and dist < 1.8:
            # Pass on the pedestrian's right instead of deadlocking head-on.
            norm = max(math.hypot(tx, ty), 0.1)
            ax += 0.8 * ty / norm
            ay -= 0.8 * tx / norm
        if agent.meta.get("group") is not None and agent.meta.get("group") == other.meta.get("group") and dist > 1.0:
            ax -= 0.4 * rx
            ay -= 0.4 * ry
    vx, vy = agent.vx + ax * dt, agent.vy + ay * dt
    norm = math.hypot(vx, vy)
    limit = speed * 1.25
    if norm > limit:
        vx, vy = vx / norm * limit, vy / norm * limit
    return vx, vy


def _is_circle(agent):
    return agent.kind == "pedestrian" and agent.dims[0] == agent.dims[1]


def penetration(a, b):
    """Penetration depth and unit normal pointing from b to a (depth <= 0: no overlap).
    Same shapes as overlaps(): circular walkers, oriented rectangles for everything else."""
    dx, dy = a.x - b.x, a.y - b.y
    ca, cb = _is_circle(a), _is_circle(b)
    if ca and cb:
        dist = math.hypot(dx, dy)
        if dist < 1e-9:
            return (a.dims[0] + b.dims[0]) / 2, (1.0 if a.id > b.id else -1.0), 0.0
        return (a.dims[0] + b.dims[0]) / 2 - dist, dx / dist, dy / dist
    if ca or cb:
        walker, rect, sign = (a, b, 1.0) if ca else (b, a, -1.0)
        rx, ry = walker.x - rect.x, walker.y - rect.y
        c, s = math.cos(rect.heading), math.sin(rect.heading)
        lx, ly = c * rx + s * ry, -s * rx + c * ry
        hx, hy = rect.dims[0] / 2, rect.dims[1] / 2
        r = walker.dims[0] / 2
        if abs(lx) <= hx and abs(ly) <= hy:  # centre inside the rectangle: leave by the nearest face
            if hx - abs(lx) < hy - abs(ly):
                nlx, nly, depth = math.copysign(1.0, lx or 1.0), 0.0, r + hx - abs(lx)
            else:
                nlx, nly, depth = 0.0, math.copysign(1.0, ly or 1.0), r + hy - abs(ly)
        else:
            qx, qy = max(-hx, min(hx, lx)), max(-hy, min(hy, ly))
            ex, ey = lx - qx, ly - qy
            dist = math.hypot(ex, ey)
            nlx, nly, depth = ex / dist, ey / dist, r - dist
        nx, ny = c * nlx - s * nly, s * nlx + c * nly
        return depth, sign * nx, sign * ny
    ac, ass = math.cos(a.heading), math.sin(a.heading)
    bc, bs = math.cos(b.heading), math.sin(b.heading)
    axes_a, axes_b = ((ac, ass), (-ass, ac)), ((bc, bs), (-bs, bc))
    ha, hb = (a.dims[0] / 2, a.dims[1] / 2), (b.dims[0] / 2, b.dims[1] / 2)
    best = None
    for ux, uy in (*axes_a, *axes_b):
        ra = sum(h * abs(ux * vx + uy * vy) for h, (vx, vy) in zip(ha, axes_a))
        rb = sum(h * abs(ux * vx + uy * vy) for h, (vx, vy) in zip(hb, axes_b))
        proj = dx * ux + dy * uy
        depth = ra + rb - abs(proj)
        if best is None or depth < best[0]:
            sgn = 1.0 if proj >= 0 else -1.0
            best = (depth, sgn * ux, sgn * uy)
    return best


def overlaps(a, b, padding=0.0):
    """Circular walkers and oriented vehicles; touching is not penetration."""
    dx, dy = b.x - a.x, b.y - a.y
    circle_a = a.kind == "pedestrian" and a.dims[0] == a.dims[1]
    circle_b = b.kind == "pedestrian" and b.dims[0] == b.dims[1]
    if circle_a and circle_b:
        return math.hypot(dx, dy) < (a.dims[0] + b.dims[0]) / 2 + 2 * padding - 1e-7
    if circle_a or circle_b:
        walker, rectangle = (a, b) if circle_a else (b, a)
        rx, ry = walker.x - rectangle.x, walker.y - rectangle.y
        c, s = math.cos(rectangle.heading), math.sin(rectangle.heading)
        lx, ly = c * rx + s * ry, -s * rx + c * ry
        ex = max(0.0, abs(lx) - rectangle.dims[0] / 2 - padding)
        ey = max(0.0, abs(ly) - rectangle.dims[1] / 2 - padding)
        return math.hypot(ex, ey) < walker.dims[0] / 2 + padding - 1e-7
    ac, ass = math.cos(a.heading), math.sin(a.heading)
    bc, bs = math.cos(b.heading), math.sin(b.heading)
    axes_a, axes_b = ((ac, ass), (-ass, ac)), ((bc, bs), (-bs, bc))
    ha = (a.dims[0] / 2 + padding, a.dims[1] / 2 + padding)
    hb = (b.dims[0] / 2 + padding, b.dims[1] / 2 + padding)
    for ux, uy in (*axes_a, *axes_b):
        ra = sum(h * abs(ux * vx + uy * vy) for h, (vx, vy) in zip(ha, axes_a))
        rb = sum(h * abs(ux * vx + uy * vy) for h, (vx, vy) in zip(hb, axes_b))
        if abs(dx * ux + dy * uy) >= ra + rb - 1e-7:
            return False
    return True
