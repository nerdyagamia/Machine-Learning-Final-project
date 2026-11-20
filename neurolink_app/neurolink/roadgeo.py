"""Road geometry packs, traffic-signal timing patterns and the offline cache.

* A *pack* is a small JSON document describing the roads / intersections / crosswalks around a
  point, in a local metric frame (x = east, y = north, metres) anchored at a GPS origin.
* Packs come from OpenStreetMap (Overpass API, needs a connection) or from the built-in synthetic
  Alexandria demo pack, and are cached on disk so contextual navigation and safety keep working with
  poor connectivity.
* A *signal plan* is a repeating list of (phase, seconds). Observed phase changes can be recorded
  and a pattern learned from them (the "signal pattern" cache).

No Streamlit imports.
"""
from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import config

EARTH_M_PER_DEG_LAT = 111_320.0

# --------------------------------------------------------------------------- coordinates
def ll_to_xy(lat: float, lon: float, origin: dict) -> tuple[float, float]:
    lat0, lon0 = origin["lat"], origin["lon"]
    x = (lon - lon0) * EARTH_M_PER_DEG_LAT * math.cos(math.radians(lat0))
    y = (lat - lat0) * EARTH_M_PER_DEG_LAT
    return x, y


def xy_to_ll(x: float, y: float, origin: dict) -> tuple[float, float]:
    lat0, lon0 = origin["lat"], origin["lon"]
    lat = lat0 + y / EARTH_M_PER_DEG_LAT
    lon = lon0 + x / (EARTH_M_PER_DEG_LAT * math.cos(math.radians(lat0)))
    return lat, lon


# --------------------------------------------------------------------------- signal plans
PHASE_LABELS = {
    "MAIN_GREEN": "Main Ave green", "MAIN_YELLOW": "Main Ave yellow", "RED_CLEAR_1": "All red",
    "CROSS_GREEN": "Cross St green", "CROSS_YELLOW": "Cross St yellow", "RED_CLEAR_2": "All red",
}


def plan_cycle(plan: dict) -> float:
    return float(sum(d for _, d in plan["phases"]))


def phase_at(plan: dict, t: float) -> dict:
    """Which phase is active at epoch time t -> name, index, elapsed, remaining, start_ts."""
    cyc = plan_cycle(plan)
    if cyc <= 0:                                       # a broken plan must not crash the page
        cyc = 1e-6
    pos = (t - float(plan.get("offset_s", 0.0))) % cyc
    acc = 0.0
    for i, (name, dur) in enumerate(plan["phases"]):
        if pos < acc + dur:
            elapsed = pos - acc
            return {"name": name, "index": i, "elapsed": elapsed, "remaining": dur - elapsed,
                    "start_ts": t - elapsed, "duration": float(dur)}
        acc += dur
    name, dur = plan["phases"][-1]
    return {"name": name, "index": len(plan["phases"]) - 1, "elapsed": dur, "remaining": 0.0,
            "start_ts": t - dur, "duration": float(dur)}


def road_light(phase_name: str, road_id: str) -> str:
    """'green' | 'yellow' | 'red' for vehicles on the given road ('main' or 'cross')."""
    prefix = "MAIN" if road_id == "main" else "CROSS"
    if phase_name == f"{prefix}_GREEN":
        return "green"
    if phase_name == f"{prefix}_YELLOW":
        return "yellow"
    return "red"


def pedestrian_state(plan: dict, walk_phase: str, t: float) -> dict:
    """WALK / DON'T WALK for a crosswalk plus seconds until that state flips."""
    cur = phase_at(plan, t)
    walking = cur["name"] == walk_phase
    remaining = cur["remaining"]
    # walk forward through the cycle until the state flips
    idx = cur["index"]
    phases = plan["phases"]
    for step in range(1, len(phases) + 1):
        nxt = phases[(idx + step) % len(phases)]
        if (nxt[0] == walk_phase) != walking:
            break
        remaining += nxt[1]
    return {"walk": walking, "seconds_to_change": remaining, "phase": cur["name"]}


# --------------------------------------------------------------------------- built-in demo pack
DEMO_VERSION = 2          # bump when the demo pack gains fields: older cached copies are rewritten


def demo_pack() -> dict:
    """Synthetic intersection placed in Alexandria, Egypt. NOT real survey data."""
    main_w, cross_w = 14.0, 11.0
    plan = {
        "id": "plan_main", "source": "demo",
        "offset_s": 0.0,
        "phases": [["MAIN_GREEN", 45], ["MAIN_YELLOW", 4], ["RED_CLEAR_1", 2],
                   ["CROSS_GREEN", 30], ["CROSS_YELLOW", 4], ["RED_CLEAR_2", 2]],
    }
    cw_off_main = main_w / 2 + 3.0      # crosswalk centre distance from the junction centre
    cw_off_cross = cross_w / 2 + 3.0
    return {
        "id": "alexandria-demo",
        "version": DEMO_VERSION,
        "name": "Alexandria demo intersection (synthetic)",
        "source": "builtin-demo",
        "origin": {"lat": 31.2001, "lon": 29.9187},
        "radius_m": 160.0,
        "created": 0.0,
        "roads": [
            {"id": "main", "name": "Main Avenue", "kind": "primary", "width": main_w, "lanes_per_dir": 2,
             "oneway": False, "points": [[-160.0, 0.0], [160.0, 0.0]]},
            {"id": "cross", "name": "Cross Street", "kind": "secondary", "width": cross_w, "lanes_per_dir": 1,
             "oneway": False, "points": [[0.0, -160.0], [0.0, 160.0]]},
        ],
        "intersections": [
            {"id": "i1", "name": "Main Ave / Cross St", "x": 0.0, "y": 0.0, "signalized": True, "plan": "plan_main"},
        ],
        # crosswalks across each leg. `crosses` = the road being crossed, so pedestrians get WALK while
        # the *other* road has green.
        "crosswalks": [
            {"id": "cw_s", "marking": "zebra", "ramp": True, "tactile": True, "x": 0.0, "y": -cw_off_main, "orient": "ew", "len": cross_w, "crosses": "cross",
             "walk_phase": "MAIN_GREEN", "intersection": "i1", "name": "South crossing"},
            {"id": "cw_n", "marking": "zebra", "ramp": True, "tactile": True, "x": 0.0, "y": cw_off_main, "orient": "ew", "len": cross_w, "crosses": "cross",
             "walk_phase": "MAIN_GREEN", "intersection": "i1", "name": "North crossing"},
            {"id": "cw_e", "marking": "zebra", "ramp": True, "tactile": True, "x": cw_off_cross, "y": 0.0, "orient": "ns", "len": main_w, "crosses": "main",
             "walk_phase": "CROSS_GREEN", "intersection": "i1", "name": "East crossing"},
            {"id": "cw_w", "marking": "zebra", "ramp": True, "tactile": True, "x": -cw_off_cross, "y": 0.0, "orient": "ns", "len": main_w, "crosses": "main",
             "walk_phase": "CROSS_GREEN", "intersection": "i1", "name": "West crossing"},
        ],
        "blocks": [  # buildings, just for the map picture: [x0, y0, x1, y1, label]
            [12, 12, 70, 60, ""], [-70, 12, -12, 60, ""], [12, -60, 70, -12, ""], [-70, -60, -12, -12, ""],
            [80, 12, 150, 70, ""], [-150, 12, -80, 70, ""], [80, -70, 150, -12, ""], [-150, -70, -80, -12, ""],
        ],
        "signal_plans": {"plan_main": plan},
    }


# --------------------------------------------------------------------------- OSM download + parse
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_ROAD_KINDS = "motorway|trunk|primary|secondary|tertiary|residential|unclassified|service|living_street"
_KIND_WIDTH = {"motorway": 16, "trunk": 15, "primary": 14, "secondary": 11, "tertiary": 9,
               "residential": 7, "unclassified": 7, "service": 5, "living_street": 5}


def _seg_dist(p, a, b) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def overpass_query(lat: float, lon: float, radius_m: float) -> str:
    r = int(radius_m)
    return (f"[out:json][timeout:25];(way(around:{r},{lat},{lon})[\"highway\"~\"^({_ROAD_KINDS})$\"];"
            f"node(around:{r},{lat},{lon})[\"highway\"=\"traffic_signals\"];"
            f"node(around:{r},{lat},{lon})[\"highway\"=\"crossing\"];);out body geom;")


def fetch_osm_json(lat: float, lon: float, radius_m: float, timeout: float = 25.0) -> dict:
    data = urllib.parse.urlencode({"data": overpass_query(lat, lon, radius_m)}).encode()
    req = urllib.request.Request(OVERPASS_URL, data=data, headers={"User-Agent": "NeuroLink-student-project/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:       # noqa: S310 (fixed https URL)
        return json.loads(resp.read().decode("utf-8"))


def pack_from_osm(osm: dict, lat: float, lon: float, radius_m: float, name: str | None = None) -> dict:
    """Convert an Overpass `out body geom` response into a pack (local metres around lat/lon)."""
    origin = {"lat": lat, "lon": lon}
    roads, node_use, signals, crossings = [], {}, [], []
    for el in osm.get("elements", []):
        if el.get("type") == "way" and el.get("geometry"):
            tags = el.get("tags", {})
            kind = tags.get("highway", "residential")
            pts = [list(ll_to_xy(g["lat"], g["lon"], origin)) for g in el["geometry"]]
            try:
                lanes = int(str(tags.get("lanes", "2")).split(";")[0])
            except ValueError:
                lanes = 2
            roads.append({"id": f"w{el['id']}", "name": tags.get("name", kind), "kind": kind,
                          "width": float(_KIND_WIDTH.get(kind, 7)), "lanes_per_dir": max(1, lanes // 2),
                          "oneway": tags.get("oneway") == "yes", "points": pts})
            for nid, p in zip(el.get("nodes", []), pts):
                node_use.setdefault(nid, [p, 0])[1] += 1
        elif el.get("type") == "node":
            tags = el.get("tags", {})
            xy = ll_to_xy(el["lat"], el["lon"], origin)
            if tags.get("highway") == "traffic_signals":
                signals.append(xy)
            elif tags.get("highway") == "crossing":
                crossings.append((xy, tags))
    inters = []
    for nid, (p, n) in node_use.items():
        if n >= 2:
            sig = any(math.hypot(p[0] - s[0], p[1] - s[1]) < 20 for s in signals)
            inters.append({"id": f"n{nid}", "name": "Junction", "x": p[0], "y": p[1], "signalized": sig,
                           "plan": "plan_default" if sig else None})
    cws = []
    for i, (c, tags) in enumerate(crossings):
        road, rd = None, 1e9                                        # the road this crossing crosses = the nearest one
        for r in roads:
            pts = r["points"]
            d = min((_seg_dist(c, a, b) for a, b in zip(pts, pts[1:])), default=1e9)
            if d < rd:
                road, rd = r, d
        orient, length, crosses, walk_phase = "ew", 8.0, "", "MAIN_GREEN"
        if road is not None and len(road["points"]) >= 2:
            seg = min(zip(road["points"], road["points"][1:]), key=lambda ab: _seg_dist(c, ab[0], ab[1]))
            dx, dy = seg[1][0] - seg[0][0], seg[1][1] - seg[0][1]
            road_is_ew = abs(dx) >= abs(dy)
            orient = "ns" if road_is_ew else "ew"                   # pedestrians cross perpendicular to the road
            length = max(5.0, float(road["width"]))
            crosses = road["id"]
            walk_phase = "CROSS_GREEN" if road_is_ew else "MAIN_GREEN"
        kind = tags.get("crossing") or ("marked" if tags.get("crossing_ref") == "zebra" else None)
        inter, di = None, 1e9
        for it in inters:
            d = math.hypot(it["x"] - c[0], it["y"] - c[1])
            if it["signalized"] and d < di:
                inter, di = it, d
        signalled = kind == "traffic_signals" or (inter is not None and di < 30)
        kerb = tags.get("kerb")
        cws.append({"id": f"c{i}", "x": c[0], "y": c[1], "orient": orient, "len": length, "crosses": crosses,
                    "walk_phase": walk_phase, "intersection": inter["id"] if (signalled and inter is not None and di < 30) else None,
                    "name": "Pedestrian crossing" if i == 0 else f"Pedestrian crossing {i + 1}",
                    "marking": (tags.get("crossing:markings") or kind or "marked"),
                    "ramp": True if kerb in ("lowered", "flush") else (False if kerb == "raised" else None),
                    "tactile": True if tags.get("tactile_paving") == "yes" else None})
    default_plan = {"id": "plan_default", "source": "default-estimate", "offset_s": 0.0,
                    "phases": [["MAIN_GREEN", 40], ["MAIN_YELLOW", 4], ["RED_CLEAR_1", 2],
                               ["CROSS_GREEN", 30], ["CROSS_YELLOW", 4], ["RED_CLEAR_2", 2]]}
    return {"id": f"osm-{lat:.4f}-{lon:.4f}-{int(radius_m)}", "name": name or f"OpenStreetMap area {lat:.4f}, {lon:.4f}",
            "source": "osm", "origin": origin, "radius_m": float(radius_m), "created": time.time(),
            "roads": roads, "intersections": inters, "crosswalks": cws, "blocks": [],
            "signal_plans": {"plan_default": default_plan}}


# --------------------------------------------------------------------------- offline cache on disk
def _packs_dir() -> Path:
    d = config.CACHE_DIR / "packs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_pack(pack: dict) -> Path:
    p = _packs_dir() / f"{pack['id']}.json"
    p.write_text(json.dumps(pack, separators=(",", ":")), encoding="utf-8")
    return p


def load_pack(pack_id: str) -> dict | None:
    p = _packs_dir() / f"{pack_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def delete_pack(pack_id: str) -> None:
    p = _packs_dir() / f"{pack_id}.json"
    if p.exists():
        p.unlink()


def list_packs() -> list[dict]:
    out = []
    for p in sorted(_packs_dir().glob("*.json")):
        try:
            pk = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": pk["id"], "name": pk.get("name", pk["id"]), "source": pk.get("source", "?"),
                    "lat": pk["origin"]["lat"], "lon": pk["origin"]["lon"], "radius_m": pk.get("radius_m", 0),
                    "created": pk.get("created", 0.0), "bytes": p.stat().st_size,
                    "n_roads": len(pk.get("roads", [])), "n_intersections": len(pk.get("intersections", [])),
                    "n_crosswalks": len(pk.get("crosswalks", []))})
    return out


def packs_signature() -> tuple:
    """Cheap fingerprint of the cache folder (changes when a pack is added/removed/rewritten)."""
    try:
        return tuple((p.name, p.stat().st_mtime_ns) for p in sorted(_packs_dir().glob("*.json")))
    except OSError:
        return ()


def ensure_builtin() -> None:
    """Make sure the demo pack is always in the cache (so offline mode always has something)."""
    cur = load_pack("alexandria-demo")
    if cur is None or cur.get("version", 1) < DEMO_VERSION:
        pk = demo_pack()
        pk["created"] = time.time()
        save_pack(pk)


def download_area(lat: float, lon: float, radius_m: float, name: str | None = None) -> dict:
    """Fetch an area from OpenStreetMap and store it. Raises OSError/URLError offline."""
    osm = fetch_osm_json(lat, lon, radius_m)
    pack = pack_from_osm(osm, lat, lon, radius_m, name)
    if not pack["roads"]:
        raise ValueError("OpenStreetMap returned no roads for that area.")
    save_pack(pack)
    return pack


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    o = {"lat": lat1, "lon": lon1}
    x, y = ll_to_xy(lat2, lon2, o)
    return math.hypot(x, y)


def pick_pack(lat: float, lon: float) -> tuple[dict, str]:
    """Best cached pack for a GPS position -> (pack, how). Falls back to the demo pack."""
    ensure_builtin()
    best, best_d = None, 1e12
    for info in list_packs():
        d = distance_m(lat, lon, info["lat"], info["lon"])
        if d <= info["radius_m"] * 1.2 and d < best_d:
            best, best_d = info["id"], d
    if best:
        pk = load_pack(best)
        if pk:
            return pk, f"cached pack '{pk.get('name', best)}'"
    return demo_pack(), "built-in demo pack (no cached map covers this position)"


# --------------------------------------------------------------------------- lookups
def nearest(items: list[dict], x: float, y: float) -> tuple[dict | None, float]:
    best, bd = None, 1e12
    for it in items:
        d = math.hypot(it["x"] - x, it["y"] - y)
        if d < bd:
            best, bd = it, d
    return best, bd


def plan_for(pack: dict, intersection: dict | None) -> dict | None:
    if not intersection or not intersection.get("plan"):
        return None
    return pack.get("signal_plans", {}).get(intersection["plan"])


# --------------------------------------------------------------------------- signal-pattern cache
def _patterns_path() -> Path:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return config.CACHE_DIR / "signal_patterns.json"


def _read_patterns() -> dict:
    p = _patterns_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_observation(inter_id: str, phase: str, start_ts: float, keep: int = 400) -> bool:
    """Remember that `phase` started at `start_ts` (as reported by the live signal feed)."""
    data = _read_patterns()
    obs = data.setdefault(inter_id, {}).setdefault("observations", [])
    if obs and (obs[-1][1] == phase or start_ts <= obs[-1][0] + 0.5):     # same phase again, or out of order
        return False
    obs.append([float(start_ts), phase])
    data[inter_id]["observations"] = obs[-keep:]
    _patterns_path().write_text(json.dumps(data), encoding="utf-8")
    return True


MAX_PHASE_S = 240.0        # a longer gap between two phase starts means the app was not watching in between
MIN_PHASE_S = 1.0


def _clean_observations(obs: list) -> list:
    """Oldest first, no repeated phase, and only the most recent unbroken run (gaps > MAX_PHASE_S start a new run)."""
    seq: list[list] = []
    for ts, name in sorted(([float(t), str(n)] for t, n in obs), key=lambda o: o[0]):
        if seq and (seq[-1][1] == name or ts - seq[-1][0] < 0.5):
            continue
        seq.append([ts, name])
    run: list[list] = []
    for o in seq:
        if run and o[0] - run[-1][0] > MAX_PHASE_S:
            run = []
        run.append(o)
    return run


def learn_pattern(inter_id: str) -> dict | None:
    """Derive a plan (ordered phases, durations, offset) from recorded phase starts.

    Needs one complete cycle of *fully observed* phases (first partial phase is skipped).
    """
    obs = _clean_observations(_read_patterns().get(inter_id, {}).get("observations", []))
    if len(obs) < 3:
        return None
    durs: dict[str, list[float]] = {}
    seq: list[tuple[float, str]] = []
    for (t0, p0), (t1, _) in zip(obs[:-1], obs[1:]):
        durs.setdefault(p0, []).append(t1 - t0)
        seq.append((t0, p0))
    seq = seq[1:]                                   # first phase was only partly seen
    order: list[str] = []
    for _, name in seq:
        if name in order:
            break
        order.append(name)
    if len(order) < 2:
        return None
    full = {n: sum(d) / len(d) for n, d in durs.items() if n in order}
    if len(full) != len(order) or any(v < MIN_PHASE_S for v in full.values()):
        return None
    first_ts = next(t for t, n in seq if n == order[0])
    n_cycles = max(1, len(seq) // len(order))
    return {"id": f"learned-{inter_id}", "source": "observed", "offset_s": float(first_ts),
            "phases": [[n, round(full[n], 1)] for n in order], "n_cycles": n_cycles}


def simulate_observations(plan: dict, inter_id: str, now: float, cycles: int = 3) -> int:
    """Demo helper: pretend the app watched the live feed for `cycles` cycles up to `now`."""
    clear_patterns(inter_id)                         # the demo replaces what was recorded so far
    cyc = plan_cycle(plan)
    t = now - cycles * cyc
    n = 0
    cur = phase_at(plan, t)
    ts = cur["start_ts"] + cur["duration"]          # first full phase boundary after t
    idx = (cur["index"] + 1) % len(plan["phases"])
    while ts <= now:
        name, dur = plan["phases"][idx]
        n += int(record_observation(inter_id, name, ts))
        ts += dur
        idx = (idx + 1) % len(plan["phases"])
    return n


def clear_patterns(inter_id: str | None = None) -> None:
    data = _read_patterns()
    if inter_id is None:
        data = {}
    else:
        data.pop(inter_id, None)
    _patterns_path().write_text(json.dumps(data), encoding="utf-8")


def cached_pattern_info() -> list[dict]:
    out = []
    for iid, d in _read_patterns().items():
        learned = learn_pattern(iid)
        out.append({"intersection": iid, "n_observations": len(d.get("observations", [])),
                    "learned": learned})
    return out
