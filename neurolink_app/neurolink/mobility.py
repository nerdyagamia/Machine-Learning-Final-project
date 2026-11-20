"""Wheelchair simulation: pose, commands and a time-step update. No Streamlit imports.

Frame: x east, y north (metres); heading in degrees clockwise from north (0 = north).
"""
from __future__ import annotations

import math
import time

from . import safety

WORLD_LIMIT = 140.0
START = (0.0, -30.0, 0.0)          # 30 m south of the junction, facing north


def new_chair(speed: float = 1.0, start: tuple[float, float, float] = START) -> dict:
    x, y, h = start
    return {"x": x, "y": y, "heading": h, "motion": "stop", "speed": float(speed), "trail": [(x, y)],
            "last_tick": time.time(), "turn_dir": None, "turn_ts": 0.0, "odometer": 0.0, "msg": "", "msg_ts": 0.0}


def teleport(chair: dict, x: float, y: float, heading: float) -> None:
    chair.update(x=float(x), y=float(y), heading=float(heading) % 360.0, motion="stop")
    chair["trail"] = [(chair["x"], chair["y"])]
    chair["msg"] = ""
    chair["turn_dir"] = None


def _say(chair: dict, text: str) -> str:
    chair["msg"], chair["msg_ts"] = text, time.time()
    return text


def command(chair: dict, cmd: str, prefs: dict, obstacles: list[dict] | None = None, vehicles: list[dict] | None = None,
            source: str = "buttons") -> str:
    """Apply a command: forward | backward | stop | left | right. Returns a short status message."""
    chair["speed"] = float(prefs.get("speed_mps", chair["speed"]))
    if cmd == "stop":
        chair["motion"] = "stop"
        return _say(chair, "Stopped")
    if cmd in ("left", "right"):
        step = float(prefs.get("turn_step_deg", 15))
        chair["heading"] = (chair["heading"] + (step if cmd == "right" else -step)) % 360.0
        chair["turn_dir"], chair["turn_ts"] = cmd, time.time()
        return _say(chair, f"Turning {cmd}")
    if cmd in ("forward", "backward"):
        if prefs.get("auto_stop", True):
            a = safety.assess(chair if cmd == "forward" else {**chair, "heading": (chair["heading"] + 180) % 360},
                              obstacles or [], vehicles or [], prefs)
            if a["block_forward"]:
                chair["motion"] = "stop"
                return _say(chair, "Blocked: obstacle too close - not moving")
        chair["motion"] = cmd
        return _say(chair, f"Moving {cmd}")
    raise ValueError(f"unknown command {cmd!r}")


def describe(chair: dict, now: float | None = None) -> str:
    now = now or time.time()
    if chair["motion"] == "forward":
        return "Moving: Forward"
    if chair["motion"] == "backward":
        return "Moving: Backward"
    if chair.get("turn_dir") and now - chair.get("turn_ts", 0) < 2.0:
        return f"Turning: {chair['turn_dir'].title()}"
    return "Stopped"


def tick(chair: dict, prefs: dict, obstacles: list[dict], vehicles: list[dict], now: float | None = None,
         ped_ctx: dict | None = None) -> dict:
    """Advance the chair by the wall-clock time since the last tick (capped). Returns the safety assessment."""
    now = now or time.time()
    dt = max(0.0, min(now - chair.get("last_tick", now), 1.5))
    chair["last_tick"] = now
    assessment = safety.assess(chair, obstacles, vehicles, prefs, ped_ctx)
    if chair["motion"] != "stop" and prefs.get("auto_stop", True):
        if chair["motion"] == "forward" and assessment["block_forward"]:
            chair["motion"] = "stop"
            _say(chair, "Auto-stop: obstacle ahead")
        elif assessment["stop_for_vehicle"]:
            chair["motion"] = "stop"
            _say(chair, "Auto-stop: vehicle approaching")
    if chair["motion"] != "stop" and dt > 0:
        h = math.radians(chair["heading"])
        v = chair["speed"] if chair["motion"] == "forward" else -0.5 * chair["speed"]
        nx = max(-WORLD_LIMIT, min(WORLD_LIMIT, chair["x"] + math.sin(h) * v * dt))
        ny = max(-WORLD_LIMIT, min(WORLD_LIMIT, chair["y"] + math.cos(h) * v * dt))
        hit = safety.collides(nx, ny, obstacles)
        if not hit and chair["motion"] == "forward" and prefs.get("auto_stop", True):
            # look one step ahead so we stop *before* entering the stop-distance zone
            if safety.assess({**chair, "x": nx, "y": ny}, obstacles, [], prefs)["block_forward"]:
                chair["motion"] = "stop"
                _say(chair, "Auto-stop: obstacle ahead")
                return assessment
        if hit:
            chair["motion"] = "stop"
            _say(chair, f"Auto-stop: {hit['label']}")
        else:
            chair["odometer"] += math.hypot(nx - chair["x"], ny - chair["y"])
            chair["x"], chair["y"] = nx, ny
            trail = chair["trail"]
            if not trail or math.hypot(trail[-1][0] - nx, trail[-1][1] - ny) > 0.4:
                trail.append((nx, ny))
                del trail[:-400]
    return assessment


def apply_decision(chair: dict, decision, prefs: dict, obstacles: list[dict], vehicles: list[dict]) -> str:
    """Helmet steering: an accepted Left/Right decision turns the chair; low-confidence ones are ignored."""
    if not decision.accepted:
        return f"Ignored: confidence {decision.confidence:.0%} is below the {decision.gate:.0%} gate"
    return command(chair, "left" if decision.label == "Left" else "right", prefs, obstacles, vehicles, source="helmet")
