"""Safety integration: obstacle / hazard detection ahead and warnings for approaching vehicles.

Works on a simulated sensor world (obstacles + vehicles in a local metric frame, x east / y north,
heading in degrees clockwise from north). `assess()` is the single entry point; a real sensor feed
(ultrasonic, LiDAR, camera detections) can be plugged in by filling the same `obstacles` /
`vehicles` lists.

No Streamlit imports.
"""
from __future__ import annotations

import math
import random

CHAIR_RADIUS = 0.45
SENSOR_RANGE = 6.0
SENSOR_ANGLES = {"left": -35.0, "center": 0.0, "right": 35.0}
LEVEL_RANK = {"clear": 0, "caution": 1, "danger": 2}

# Right-hand traffic. Lane centres chosen to match roadgeo.demo_pack (main 14 m wide, cross 11 m wide).
VEHICLE_SPAWNS = {
    "from_west": {"x": -125.0, "y": -2.5, "vx": 1.0, "vy": 0.0, "road": "main", "label": "from the west"},
    "from_east": {"x": 125.0, "y": 2.5, "vx": -1.0, "vy": 0.0, "road": "main", "label": "from the east"},
    "from_south": {"x": 2.75, "y": -125.0, "vx": 0.0, "vy": 1.0, "road": "cross", "label": "from the south"},
    "from_north": {"x": -2.75, "y": 125.0, "vx": 0.0, "vy": -1.0, "road": "cross", "label": "from the north"},
}


# --------------------------------------------------------------------------- obstacles
def default_obstacles() -> list[dict]:
    return [
        {"id": "o1", "x": 3.2, "y": -19.0, "r": 0.5, "kind": "bicycle", "label": "Parked bicycle"},
        {"id": "o2", "x": -1.4, "y": -12.0, "r": 0.4, "kind": "pothole", "label": "Pothole"},
    ]


def obstacle_ahead(chair: dict, distance: float = 4.0, kind: str = "pole", label: str = "Obstacle") -> dict:
    h = math.radians(chair["heading"])
    return {"id": f"o{int(random.random() * 1e6)}", "x": chair["x"] + math.sin(h) * distance,
            "y": chair["y"] + math.cos(h) * distance, "r": 0.5, "kind": kind, "label": label}


def _ray_circle(ox: float, oy: float, dx: float, dy: float, cx: float, cy: float, r: float) -> float | None:
    fx, fy = ox - cx, oy - cy
    b = fx * dx + fy * dy
    c = fx * fx + fy * fy - r * r
    disc = b * b - c
    if disc < 0:
        return None
    s = math.sqrt(disc)
    t = -b - s
    if t < 0:
        t = max(0.0, -b + s) if c < 0 else -1.0
    return t if 0.0 <= t <= SENSOR_RANGE else None


def front_sensors(chair: dict, obstacles: list[dict]) -> dict[str, dict]:
    """Simulated 3-beam range finder. -> {'left': {'dist': m|None, 'obstacle': ob|None}, ...}"""
    out = {}
    for name, ang in SENSOR_ANGLES.items():
        h = math.radians(chair["heading"] + ang)
        dx, dy = math.sin(h), math.cos(h)
        best, who = None, None
        for ob in obstacles:
            t = _ray_circle(chair["x"], chair["y"], dx, dy, ob["x"], ob["y"], ob["r"])
            if t is not None and (best is None or t < best):
                best, who = t, ob
        out[name] = {"dist": best, "obstacle": who}
    return out


def collides(x: float, y: float, obstacles: list[dict]) -> dict | None:
    for ob in obstacles:
        if math.hypot(x - ob["x"], y - ob["y"]) < ob["r"] + CHAIR_RADIUS:
            return ob
    return None


# --------------------------------------------------------------------------- vehicles
def spawn_vehicle(direction: str, speed: float | None = None, rng: random.Random | None = None,
                  vehicles: list[dict] | None = None) -> dict:
    sp = VEHICLE_SPAWNS[direction]
    rng = rng or random
    v = speed if speed is not None else rng.uniform(7.0, 12.0)     # m/s  (25-43 km/h)
    veh = {"id": f"v{int(rng.random() * 1e9)}", "x": sp["x"], "y": sp["y"], "vx": sp["vx"] * v, "vy": sp["vy"] * v,
           "dir": direction, "road": sp["road"], "kind": rng.choice(["car", "car", "van", "bus"])}
    if vehicles is not None:
        vehicles.append(veh)
    return veh


def step_vehicles(vehicles: list[dict], dt: float) -> list[dict]:
    """Advance vehicles; drop those that left the area. Returns the surviving list (new list)."""
    keep = []
    for v in vehicles:
        v["x"] += v["vx"] * dt
        v["y"] += v["vy"] * dt
        if abs(v["x"]) <= 135 and abs(v["y"]) <= 135:
            keep.append(v)
    return keep


def maybe_spawn(vehicles: list[dict], dt: float, light_for_road, rng: random.Random, rate_per_s: float = 0.12) -> None:
    """Random traffic: arrivals are only generated on roads that currently have a green light."""
    for direction, sp in VEHICLE_SPAWNS.items():
        if light_for_road(sp["road"]) == "green" and rng.random() < rate_per_s * dt:
            if not any(v["dir"] == direction and math.hypot(v["x"] - sp["x"], v["y"] - sp["y"]) < 25 for v in vehicles):
                spawn_vehicle(direction, rng=rng, vehicles=vehicles)


def relative_direction(chair: dict, x: float, y: float) -> str:
    bearing = math.degrees(math.atan2(x - chair["x"], y - chair["y"]))
    rel = (bearing - chair["heading"] + 180.0) % 360.0 - 180.0
    if abs(rel) <= 45:
        return "ahead"
    if abs(rel) >= 135:
        return "behind"
    return "right" if rel > 0 else "left"


def closest_approach(chair: dict, veh: dict, horizon: float = 12.0) -> tuple[float, float]:
    """(time_s, distance_m) of closest approach within `horizon` seconds, straight-line motion for both."""
    h = math.radians(chair["heading"])
    speed = chair["speed"] if chair.get("motion") == "forward" else (-0.5 * chair["speed"] if chair.get("motion") == "backward" else 0.0)
    cvx, cvy = math.sin(h) * speed, math.cos(h) * speed
    px, py = veh["x"] - chair["x"], veh["y"] - chair["y"]
    vx, vy = veh["vx"] - cvx, veh["vy"] - cvy
    v2 = vx * vx + vy * vy
    t = 0.0 if v2 < 1e-9 else max(0.0, min(horizon, -(px * vx + py * vy) / v2))
    return t, math.hypot(px + vx * t, py + vy * t)


# --------------------------------------------------------------------------- assessment
def assess(chair: dict, obstacles: list[dict], vehicles: list[dict], prefs: dict,
           ped_ctx: dict | None = None) -> dict:
    """Combine obstacle ranging, vehicle tracking and (optional) pedestrian-signal context.

    Returns {'level', 'warnings': [{'level','kind','text'}], 'sensors', 'block_forward', 'stop_for_vehicle'}.
    """
    stop_d = float(prefs.get("stop_distance_m", 1.2))
    slow_d = float(prefs.get("slow_distance_m", 3.0))
    t_caution = float(prefs.get("vehicle_caution_s", 8.0))
    t_danger = float(prefs.get("vehicle_danger_s", 4.0))
    warnings: list[dict] = []

    sensors = front_sensors(chair, obstacles)
    dists = {k: v["dist"] for k, v in sensors.items() if v["dist"] is not None}
    block = False
    if dists:
        near_k = min(dists, key=dists.get)
        near_d = dists[near_k]
        ob = sensors[near_k]["obstacle"]
        where = {"left": "ahead-left", "center": "ahead", "right": "ahead-right"}[near_k]
        label = ob["label"] if ob else "Obstacle"
        if dists.get("center", 99.0) < stop_d or min(dists.get("left", 99.0), dists.get("right", 99.0)) < stop_d * 0.7:
            block = True
            warnings.append({"level": "danger", "kind": "obstacle", "text": f"{label} {near_d:.1f} m {where} - too close, stopping"})
        elif near_d < slow_d:
            warnings.append({"level": "caution", "kind": "obstacle", "text": f"{label} {near_d:.1f} m {where} - slow down"})
        else:
            warnings.append({"level": "info", "kind": "obstacle", "text": f"{label} detected {near_d:.1f} m {where}"})

    stop_for_vehicle = False
    threats = []
    for v in vehicles:
        t, d = closest_approach(chair, v)
        speed = math.hypot(v["vx"], v["vy"])
        dist_now = math.hypot(v["x"] - chair["x"], v["y"] - chair["y"])
        if dist_now > 90:
            continue
        side = relative_direction(chair, v["x"], v["y"])
        if d < 3.5 and t <= t_danger:
            lvl = "danger"
        elif d < 7.0 and t <= t_caution:
            lvl = "caution"
        else:
            continue
        threats.append({"vehicle": v["id"], "level": lvl, "t": t, "d": d, "side": side, "speed_kmh": speed * 3.6})
        verb = "STOP" if lvl == "danger" else "be careful"
        warnings.append({"level": lvl, "kind": "vehicle",
                         "text": f"Vehicle approaching from the {side} ({speed * 3.6:.0f} km/h) - reaches you in ~{t:.0f} s - {verb}"})
        if lvl == "danger" and chair.get("motion") in ("forward", "backward"):
            stop_for_vehicle = True

    if ped_ctx and ped_ctx.get("on_crosswalk"):
        if not ped_ctx.get("walk"):
            warnings.append({"level": "caution", "kind": "signal",
                             "text": "On a crosswalk while the pedestrian signal says DON'T WALK"})
        elif ped_ctx.get("seconds_to_change", 99) < 6:
            warnings.append({"level": "caution", "kind": "signal",
                             "text": f"Walk signal ends in {ped_ctx['seconds_to_change']:.0f} s - finish crossing"})

    level = "clear"
    for w in warnings:
        if w["level"] in LEVEL_RANK and LEVEL_RANK[w["level"]] > LEVEL_RANK[level]:
            level = w["level"]
    warnings.sort(key=lambda w: -LEVEL_RANK.get(w["level"], 0))
    return {"level": level, "warnings": warnings, "sensors": sensors, "block_forward": block,
            "stop_for_vehicle": stop_for_vehicle, "threats": threats}
