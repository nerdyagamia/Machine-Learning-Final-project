"""Shared simulation context used by the Mobility Controller (contextual navigation, safety) and Settings (offline cache).

Combines: active road-geometry pack (cached/demo), traffic-signal state (live feed or cached pattern),
pedestrian-crossing state for the nearest crosswalk, and one simulation time-step.
No Streamlit imports.
"""
from __future__ import annotations

import math
import random
import time

from . import connectivity, mobility, roadgeo, safety

DETECT_RADIUS_M = 45.0


def new_world(prefs: dict) -> dict:
    return {"chair": mobility.new_chair(prefs.get("speed_mps", 1.0)), "obstacles": safety.default_obstacles(),
            "vehicles": [], "traffic_on": False, "rng": random.Random(7), "last_world_tick": time.time(),
            "pack": None, "pack_sig": None, "pack_note": "", "pack_id": None}


def get_pack(world: dict, prefs: dict) -> dict:
    """Pick (and memoise) the road-geometry pack covering the configured GPS position."""
    sig = (round(float(prefs["lat"]), 5), round(float(prefs["lon"]), 5), roadgeo.packs_signature())
    if world.get("pack") is None or world.get("pack_sig") != sig:
        pack, note = roadgeo.pick_pack(float(prefs["lat"]), float(prefs["lon"]))
        world["pack"], world["pack_sig"], world["pack_note"] = pack, sig, note
        if world.get("pack_id") not in (None, pack["id"]):
            mobility.teleport(world["chair"], *mobility.START)
            world["vehicles"] = []
        world["pack_id"] = pack["id"]
    return world["pack"]


def _on_crosswalk(cw: dict, x: float, y: float) -> bool:
    L, T = cw["len"], 3.0
    if cw["orient"] == "ew":
        return abs(x - cw["x"]) <= L / 2 + 0.5 and abs(y - cw["y"]) <= T / 2 + 0.5
    return abs(y - cw["y"]) <= L / 2 + 0.5 and abs(x - cw["x"]) <= T / 2 + 0.5


def context(world: dict, prefs: dict, now: float | None = None, record: bool = True) -> dict:
    now = now or time.time()
    pack = get_pack(world, prefs)
    chair = world["chair"]
    online = connectivity.effective_online(prefs)
    lat, lon = roadgeo.xy_to_ll(chair["x"], chair["y"], pack["origin"])
    inter, d_inter = roadgeo.nearest(pack.get("intersections", []), chair["x"], chair["y"])
    plan = roadgeo.plan_for(pack, inter)
    ctx = {"pack": pack, "pack_note": world.get("pack_note", ""), "online": online, "lat": lat, "lon": lon,
           "intersection": inter if inter is not None and d_inter <= DETECT_RADIUS_M else None,
           "dist_to_intersection": d_inter if inter is not None else None,
           "plan": plan, "phase": None, "lights": {}, "walk_states": {}, "ped_states": {}, "ped": None,
           "signal_source": "none", "pattern": None}
    if not plan or inter is None:
        return ctx

    # Which timing do we trust?  Online: the live controller (here: simulated from the plan).
    # Offline: the cached/learned pattern, falling back to the cached plan.
    live_phase = roadgeo.phase_at(plan, now)
    if online:
        use, source = plan, "live signal feed (simulated)"
        if record:
            roadgeo.record_observation(inter["id"], live_phase["name"], live_phase["start_ts"])
    else:
        learned = roadgeo.learn_pattern(inter["id"])
        if learned:
            use, source = learned, f"cached signal pattern (learned from {learned['n_cycles']} cycle(s))"
        else:
            use, source = plan, "cached timing plan from the offline map pack"
    phase = roadgeo.phase_at(use, now)
    ctx["phase"], ctx["signal_source"], ctx["pattern"] = phase, source, use
    ctx["lights"] = {rid: roadgeo.road_light(phase["name"], rid) for rid in ("main", "cross")}
    peds = {}
    for cw in pack.get("crosswalks", []):
        if cw.get("intersection") == inter["id"]:
            peds[cw["id"]] = roadgeo.pedestrian_state(use, cw["walk_phase"], now)
    ctx["walk_states"] = {cid: p["walk"] for cid, p in peds.items()}
    ctx["ped_states"] = peds
    near_cw, d_cw = roadgeo.nearest([c for c in pack.get("crosswalks", []) if c["id"] in peds], chair["x"], chair["y"])
    if near_cw is not None and d_cw <= DETECT_RADIUS_M:
        p = peds[near_cw["id"]]
        ctx["ped"] = {"crosswalk": near_cw, "walk": p["walk"], "seconds_to_change": p["seconds_to_change"],
                      "distance": d_cw, "on_crosswalk": _on_crosswalk(near_cw, chair["x"], chair["y"])}
    return ctx


def step(world: dict, prefs: dict, now: float | None = None) -> tuple[dict, dict]:
    """Advance vehicles and the wheelchair. Returns (context, safety assessment)."""
    now = now or time.time()
    dt = max(0.0, min(now - world.get("last_world_tick", now), 1.5))
    world["last_world_tick"] = now
    ctx = context(world, prefs, now)
    world["vehicles"] = safety.step_vehicles(world["vehicles"], dt)
    if world["traffic_on"] and ctx["lights"]:
        safety.maybe_spawn(world["vehicles"], dt, lambda road: ctx["lights"].get(road, "red"), world["rng"])
    assessment = mobility.tick(world["chair"], prefs, world["obstacles"], world["vehicles"], now, ctx["ped"])
    return ctx, assessment


def snapshot_assessment(world: dict, prefs: dict, ctx: dict | None = None) -> dict:
    """Assessment without advancing time (for pages that only display)."""
    ctx = ctx or context(world, prefs, record=False)
    return safety.assess(world["chair"], world["obstacles"], world["vehicles"], prefs, ctx.get("ped"))


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
