"""Contextual navigation: detect crosswalks, pedestrian signals and road markings, and guide the patient
step by step to the next safe crossing. No Streamlit imports.

Frame: x east / y north (metres); heading and bearings in degrees clockwise from north.

`plan()` is the single entry point used by the Mobility Controller. It keeps a tiny tracker dict (held in
the session) so the guidance does not jump between crossings while the wheelchair moves.
"""
from __future__ import annotations

import math

from . import roadgeo, safety

STANDOFF_M = 1.4        # waiting point is this far beyond the end of the zebra stripes (on the pavement)
ARRIVE_M = 2.5          # "I am at the kerb" radius
MARGIN_S = 2.0          # spare seconds required on top of the crossing time
STRIPE_T = 3.0          # depth of the zebra stripes (metres), same as the map drawing
MAX_RANGE_M = 150.0     # crossings further away are ignored
DONE_CLEAR_M = 12.0     # after crossing, move this far away before the next crossing is chosen


# --------------------------------------------------------------------------- geometry helpers
def _axis(cw: dict) -> tuple[float, float]:
    """Unit vector along the crossing direction (from end A to end B)."""
    return (1.0, 0.0) if cw["orient"] == "ew" else (0.0, 1.0)


def crosswalk_ends(cw: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    ax, ay = _axis(cw)
    h = cw["len"] / 2.0
    return (cw["x"] - ax * h, cw["y"] - ay * h), (cw["x"] + ax * h, cw["y"] + ay * h)


def _coords(cw: dict, x: float, y: float) -> tuple[float, float]:
    """(u, v): position along the crossing and across it, relative to the centre of the stripes."""
    ax, ay = _axis(cw)
    dx, dy = x - cw["x"], y - cw["y"]
    return dx * ax + dy * ay, -dx * ay + dy * ax


def on_crosswalk(cw: dict, x: float, y: float) -> bool:
    u, v = _coords(cw, x, y)
    return abs(u) <= cw["len"] / 2 + 0.5 and abs(v) <= STRIPE_T / 2 + 0.5


def wait_point(cw: dict, side: int) -> tuple[float, float]:
    """Waiting point on the pavement at the end of the crossing on `side` (+1 = end B, -1 = end A)."""
    ax, ay = _axis(cw)
    d = cw["len"] / 2 + STANDOFF_M
    return cw["x"] + side * ax * d, cw["y"] + side * ay * d


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360.0


def rel_turn(heading: float, brg: float) -> float:
    """Signed angle to turn (+ = right/clockwise, - = left) in (-180, 180]."""
    return (brg - heading + 180.0) % 360.0 - 180.0


def turn_text(rel: float, step_deg: float) -> str:
    a = abs(rel)
    if a < 8:
        return "keep going straight"
    side = "right" if rel > 0 else "left"
    n = max(1, round(a / max(step_deg, 1.0)))
    if a >= 150:
        return f"turn around (about {n} presses of the {side} arrow)"
    return f"turn {side} about {a:.0f}° (press the {side} arrow {n}×)"


def _dist_to_segment(p: tuple[float, float], a: list[float], b: list[float]) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


# --------------------------------------------------------------------------- what the crosswalk looks like
_MARKING_TEXT = {"zebra": "zebra stripes", "marked": "painted stripes", "uncontrolled": "painted stripes, no signal",
                 "traffic_signals": "painted stripes, signal-controlled", "unmarked": "no painted stripes",
                 "yes": "painted stripes"}


def crosswalk_features(cw: dict) -> dict:
    marking = _MARKING_TEXT.get(str(cw.get("marking") or "marked").lower(), "painted stripes")
    ramp = cw.get("ramp")
    return {"marking": marking, "ramp": ramp, "tactile": cw.get("tactile"),
            "signal": bool(cw.get("intersection"))}


def feature_text(cw: dict) -> str:
    f = crosswalk_features(cw)
    bits = [f["marking"]]
    if f["ramp"] is True:
        bits.append("kerb ramps")
    elif f["ramp"] is False:
        bits.append("raised kerb - no ramp")
    if f["tactile"]:
        bits.append("tactile paving")
    return ", ".join(bits)


def stop_lines(pack: dict) -> list[dict]:
    """White stop lines painted for vehicles in front of signal-controlled crosswalks (right-hand traffic)."""
    out = []
    for cw in pack.get("crosswalks", []):
        if not cw.get("intersection"):
            continue
        cx, cy, L, g = cw["x"], cw["y"], cw["len"], STRIPE_T / 2 + 1.1
        if cw["orient"] == "ew":      # crosses a north-south road: northbound lane is the east half, southbound the west half
            out.append({"x1": cx, "y1": cy - g, "x2": cx + L / 2, "y2": cy - g, "crosswalk": cw["id"]})
            out.append({"x1": cx - L / 2, "y1": cy + g, "x2": cx, "y2": cy + g, "crosswalk": cw["id"]})
        else:                         # crosses an east-west road: eastbound lane is the south half, westbound the north half
            out.append({"x1": cx - g, "y1": cy - L / 2, "x2": cx - g, "y2": cy, "crosswalk": cw["id"]})
            out.append({"x1": cx + g, "y1": cy, "x2": cx + g, "y2": cy + L / 2, "crosswalk": cw["id"]})
    return out


# --------------------------------------------------------------------------- pedestrian signal
def ped_info(cw: dict, ctx: dict, now: float, at: float = 0.0) -> dict | None:
    """Pedestrian-signal state of a crosswalk `at` seconds from now, or None when no signal is known for it."""
    plan = ctx.get("pattern")
    if not plan or cw["id"] not in (ctx.get("ped_states") or {}):
        return None
    t = now + at
    st = roadgeo.pedestrian_state(plan, cw["walk_phase"], t)
    if st["walk"]:
        walk_left = st["seconds_to_change"]
        dont = roadgeo.pedestrian_state(plan, cw["walk_phase"], t + walk_left + 0.01)["seconds_to_change"]
        return {"walk": True, "walk_left": walk_left, "next_walk_in": walk_left + dont, "change_in": walk_left}
    return {"walk": False, "walk_left": 0.0, "next_walk_in": st["seconds_to_change"], "change_in": st["seconds_to_change"]}


def vehicle_conflict(cw: dict, vehicles: list[dict], horizon: float) -> dict | None:
    """First moment (within `horizon` s) a tracked vehicle enters the road zone covered by the crosswalk."""
    cx, cy, L = cw["x"], cw["y"], cw["len"]
    for v in vehicles:
        for k in range(int(horizon * 2) + 1):
            t = k * 0.5
            x, y = v["x"] + v["vx"] * t, v["y"] + v["vy"] * t
            along, across = (abs(x - cx), abs(y - cy)) if cw["orient"] == "ew" else (abs(y - cy), abs(x - cx))
            if along <= L / 2 and across <= STRIPE_T / 2 + 3.0:
                return {"t": t, "vehicle": v}
    return None


# --------------------------------------------------------------------------- choosing the crossing
def _candidate(cw: dict, chair: dict, signal_known: bool) -> dict:
    here = (chair["x"], chair["y"])
    u, _ = _coords(cw, *here)
    best = None
    sides = [1 if u > 0.3 else -1] if abs(u) > 0.3 else [1, -1]       # right-hand side first when it makes no difference
    for side in sides:
        w = wait_point(cw, side)
        d = _dist(here, w)
        turn = abs(rel_turn(chair["heading"], bearing(here, w)))
        cost = d + turn / 30.0 + (0.0 if (cw.get("intersection") and signal_known) else 15.0)
        if best is None or cost < best["cost"] - 1e-9:
            best = {"cw": cw, "side": side, "cost": cost, "dist": d}
    return best


def choose_crossing(pack: dict, chair: dict, ctx: dict, exclude: set[str] | None = None,
                    prefer: str | None = None) -> tuple[dict | None, list[dict]]:
    """Best crosswalk to use next + the next best alternatives. Signal-controlled crossings are preferred."""
    signal_known = bool(ctx.get("ped_states"))
    cands = []
    for cw in pack.get("crosswalks", []):
        if exclude and cw["id"] in exclude:
            continue
        c = _candidate(cw, chair, signal_known)
        if c["dist"] <= MAX_RANGE_M:
            cands.append(c)
    if not cands:
        return None, []
    cands.sort(key=lambda c: c["cost"])
    best = cands[0]
    if prefer:                                    # keep the previous choice unless something is clearly better
        for c in cands:
            if c["cw"]["id"] == prefer and c["cost"] <= best["cost"] + 6.0:
                best = c
                break
    return best, [c for c in cands if c is not best][:3]


# --------------------------------------------------------------------------- the guidance plan
def new_tracker() -> dict:
    return {"target": None, "side": 1, "done": {}, "last_say": None}


def reset(track: dict, now: float) -> None:
    """Forget the current crossing (and do not pick it again for the next two minutes)."""
    if track.get("target"):
        track["done"][track["target"]] = now
    track["target"] = None
    track["last_say"] = None


def _step(title: str, text: str, status: str) -> dict:
    return {"title": title, "text": text, "status": status}


def plan(track: dict, pack: dict, chair: dict, ctx: dict, vehicles: list[dict], prefs: dict, now: float) -> dict:
    """Guidance to the next safe crossing. See module docstring."""
    here = (chair["x"], chair["y"])
    speed = max(float(prefs.get("speed_mps", chair.get("speed", 1.0))), 0.3)
    turn_step = float(prefs.get("turn_step_deg", 15))
    cws = {c["id"]: c for c in pack.get("crosswalks", [])}
    if not cws:
        return {"state": "none", "headline": "No crosswalk known in this area", "steps": [], "route": [], "alternatives": [],
                "say": None, "say_id": None, "target": None, "safe": False, "sig": None}

    # forget old "done" marks after 2 minutes so crossings can be used again
    track["done"] = {k: v for k, v in track.get("done", {}).items() if now - v < 120.0}
    cw = cws.get(track.get("target"))
    if cw is not None and cw["id"] in track["done"] and _dist(here, wait_point(cw, -int(track["side"]))) > DONE_CLEAR_M:
        cw, track["target"] = None, None                              # crossed and moved on: pick the next crossing
    alternatives: list[dict] = []
    if cw is None:
        best, alts = choose_crossing(pack, chair, ctx, exclude=set(track["done"]))
        if best is None:                                              # everything was used recently: allow all again
            track["done"] = {}
            best, alts = choose_crossing(pack, chair, ctx)
        track["target"], track["side"] = best["cw"]["id"], best["side"]
        cw, alternatives = best["cw"], alts
    else:
        _, alternatives = choose_crossing(pack, chair, ctx, exclude=set(track["done"]) | {cw["id"]})

    side = int(track["side"])
    w_start, w_far = wait_point(cw, side), wait_point(cw, -side)
    u, v = _coords(cw, *here)
    d_start, d_far = _dist(here, w_start), _dist(here, w_far)
    L = cw["len"]

    if on_crosswalk(cw, *here):
        state = "cross"
    elif d_far <= ARRIVE_M or (u * side < -(L / 2) and abs(v) <= 4.0):
        state = "done"
    elif d_start <= ARRIVE_M or (u * side >= L / 2 and abs(v) <= 4.0):
        state = "wait"
    else:
        state = "approach"

    if state == "done":
        track["done"][cw["id"]] = now
    # --- safety of crossing right now
    t_need = L / speed + MARGIN_S
    sig = ped_info(cw, ctx, now)
    conflict = vehicle_conflict(cw, vehicles, t_need + 3.0)
    safe, reason, wait_s = True, "", 0.0
    if sig is not None:
        if sig["walk"] and sig["walk_left"] >= t_need:
            reason = f"Pedestrian signal: WALK for another {sig['walk_left']:.0f} s (you need about {t_need:.0f} s)."
        elif sig["walk"]:
            safe, wait_s = False, sig["next_walk_in"]
            reason = (f"WALK is ending in {sig['walk_left']:.0f} s - not enough time (you need about {t_need:.0f} s). "
                      f"Wait for the next WALK in about {wait_s:.0f} s.")
        else:
            safe, wait_s = False, sig["next_walk_in"]
            reason = f"Pedestrian signal: DON'T WALK. WALK in about {wait_s:.0f} s."
    else:
        reason = "No pedestrian signal known here - cross only when no vehicle is coming."
    if conflict is not None:
        safe = False
        reason = f"A vehicle is heading for the crossing (reaches it in ~{conflict['t']:.0f} s). Wait until it has passed."

    # --- step texts
    eta = d_start / speed
    brg_start = bearing(here, w_start)
    arrival = ""
    if state == "approach":
        s_arr = ped_info(cw, ctx, now, at=eta)
        if s_arr is not None:
            arrival = (f" When you arrive the signal will show WALK for {s_arr['walk_left']:.0f} s." if s_arr["walk"]
                       else f" When you arrive the signal will show DON'T WALK (WALK in {s_arr['next_walk_in']:.0f} s).")
    to_far = bearing(here, wait_point(cw, -side) if state != "cross" else (crosswalk_ends(cw)[0 if side > 0 else 1]))
    face_cross = rel_turn(chair["heading"], bearing(w_start, w_far)) if state == "wait" else rel_turn(chair["heading"], to_far)
    remaining = _dist(here, crosswalk_ends(cw)[0 if side > 0 else 1])
    walk_left_txt = ""
    if state == "cross" and sig is not None:
        if not sig["walk"]:
            walk_left_txt = " The signal is DON'T WALK - keep moving and clear the road."
        elif sig["walk_left"] < remaining / speed + 1.0:
            walk_left_txt = f" WALK ends in {sig['walk_left']:.0f} s - hurry."

    s1 = _step("Go to the crossing",
               (f"{turn_text(rel_turn(chair['heading'], brg_start), turn_step).capitalize()}, then go forward about {d_start:.0f} m "
                f"(~{eta:.0f} s) to the kerb of the {cw['name']}.{arrival}") if state == "approach" else "You are at the kerb.",
               "current" if state == "approach" else "done")
    if state in ("cross", "done"):
        s2 = _step("Wait for a safe moment", "Done.", "done")
    elif state == "wait":
        s2 = _step("Wait for a safe moment", reason, "done" if safe else "current")
    else:
        s2 = _step("Wait for a safe moment", "At the kerb, check the pedestrian signal and traffic.", "todo")
    if state == "cross":
        s3 = _step("Cross", f"{turn_text(face_cross, turn_step).capitalize()}. {remaining:.0f} m to the far kerb.{walk_left_txt}", "current")
    elif state == "wait":
        s3 = _step("Cross", (f"{turn_text(face_cross, turn_step).capitalize()} to face the crossing, then go forward {L:.0f} m "
                             f"(~{L / speed:.0f} s) keeping inside the white stripes.") if safe else "Not yet - wait as above.",
                   "current" if safe else "todo")
    elif state == "done":
        s3 = _step("Cross", "Crossed.", "done")
    else:
        s3 = _step("Cross", f"About {L:.0f} m (~{L / speed:.0f} s) inside the white stripes, ramps at the kerbs "
                            f"({feature_text(cw)}).", "todo")
    s4 = _step("Arrived", "You are across. Press “Find another crossing” to continue." if state == "done" else "On the far pavement.",
               "current" if state == "done" else "todo")
    steps = [s1, s2, s3, s4]

    headline = {"approach": f"Next safe crossing: {cw['name']} - {d_start:.0f} m away",
                "wait": f"At the {cw['name']} - {'safe to cross now' if safe else 'wait'}",
                "cross": f"Crossing the {cw['name']} - {remaining:.0f} m to go",
                "done": f"Crossed the {cw['name']} safely"}[state]

    # --- what to say (one message per meaningful change)
    if state == "approach":
        say = f"Next crossing: {cw['name']}, {d_start:.0f} meters. {turn_text(rel_turn(chair['heading'], brg_start), turn_step).capitalize()}."
        say_id = f"{cw['id']}:approach"
    elif state == "wait":
        say = "Safe to cross now." if safe else ("Wait. " + reason)
        say_id = f"{cw['id']}:wait:{int(safe)}:{int(conflict is not None)}"
    elif state == "cross":
        say = f"Crossing. {remaining:.0f} meters to go.{walk_left_txt}"
        say_id = f"{cw['id']}:cross"
    else:
        say, say_id = "You have crossed safely.", f"{cw['id']}:done"

    route: list[tuple[float, float]] = []
    if state == "approach":
        route = [here, w_start, w_far]
    elif state == "wait":
        route = [here, w_far]
    elif state == "cross":
        route = [here, crosswalk_ends(cw)[0 if side > 0 else 1], w_far]

    return {"state": state, "headline": headline, "steps": steps, "route": route, "target": cw, "side": side, "safe": safe,
            "reason": reason, "sig": sig, "d_start": d_start, "eta_s": eta, "t_need": t_need, "wait_s": wait_s, "say": say,
            "say_id": say_id, "alternatives": [{"name": a["cw"]["name"], "distance": a["dist"],
                                                "signal": bool(a["cw"].get("intersection"))} for a in alternatives],
            "features": feature_text(cw), "conflict": conflict}


# --------------------------------------------------------------------------- detection list ("what the sensors see")
def detect(pack: dict, chair: dict, ctx: dict, now: float, radius: float = 40.0) -> list[dict]:
    """Crosswalks, pedestrian signals and road markings within `radius` metres, nearest first."""
    here = (chair["x"], chair["y"])
    items: list[dict] = []

    def add(kind: str, icon: str, text: str, x: float, y: float, d: float) -> None:
        items.append({"kind": kind, "icon": icon, "text": text, "distance": d, "where": safety.relative_direction(chair, x, y)})

    for cw in pack.get("crosswalks", []):
        d = _dist(here, (cw["x"], cw["y"]))
        if d > radius:
            continue
        add("crosswalk", "🦓", f"Crosswalk - {cw['name']} ({feature_text(cw)})", cw["x"], cw["y"], d)
        sig = ped_info(cw, ctx, now)
        if sig is not None:
            add("ped_signal", "🚶", f"Pedestrian signal ({cw['name']}): {'WALK' if sig['walk'] else 'DON’T WALK'} - "
                                  f"changes in ~{sig['change_in']:.0f} s", cw["x"], cw["y"], d)
    lines = sorted(stop_lines(pack), key=lambda s: _dist(here, ((s["x1"] + s["x2"]) / 2, (s["y1"] + s["y2"]) / 2)))
    for s in lines[:2]:
        mx, my = (s["x1"] + s["x2"]) / 2, (s["y1"] + s["y2"]) / 2
        d = _dist(here, (mx, my))
        if d <= radius:
            add("stop_line", "🛑", "Stop line (vehicles must stop here, not on the crossing)", mx, my, d)
    for r in pack.get("roads", []):
        pts = r.get("points", [])
        d = min((_dist_to_segment(here, a, b) for a, b in zip(pts, pts[1:])), default=1e9)
        if d <= min(radius, 14.0 + r.get("width", 7) / 2):
            txt = f"{'Solid arrow / one-way' if r.get('oneway') else 'Dashed centre line'} - {r.get('name', 'road')}"
            items.append({"kind": "centre_line", "icon": "➖", "distance": d,
                          "text": txt + ("" if r.get("oneway") else " (two-way road)"),
                          "where": "under you" if d < 1.5 else "ahead"})
    items.sort(key=lambda i: i["distance"])
    return items[:8]
