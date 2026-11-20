"""Daily Assistant logic: reminder status and the simulated phone/device controls. No Streamlit imports."""
from __future__ import annotations

import datetime as dt
import time

from . import config

RINGER_MODES = ["Ring", "Vibrate", "Silent"]


def local_now(prefs: dict) -> dt.datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(prefs.get("timezone", "Africa/Cairo")))
    except Exception:                       # tzdata missing on Windows, bad name, ...
        return dt.datetime.now().astimezone()


def reminder_status(r: dict, now: dt.datetime, now_ts: float | None = None, missed_after_min: int = 180) -> str:
    """'off' | 'done' | 'snoozed' | 'upcoming' | 'due' | 'missed' for today."""
    now_ts = now_ts or time.time()
    if not r["enabled"]:
        return "off"
    if r.get("last_ack_date") == now.strftime("%Y-%m-%d"):
        return "done"
    hh, mm = (int(x) for x in r["hhmm"].split(":"))
    due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < due:
        return "upcoming"
    if r.get("snooze_until") and now_ts < r["snooze_until"]:
        return "snoozed"
    if (now - due).total_seconds() > missed_after_min * 60:
        return "missed"
    return "due"


def due_reminders(reminders: list[dict], now: dt.datetime, now_ts: float | None = None) -> list[dict]:
    return [r for r in reminders if reminder_status(r, now, now_ts) == "due"]


def new_phone() -> dict:
    return {"volume": 8, "max": 15, "muted": False, "ringer": "Ring", "dnd": False, "app": None,
            "drawer": False, "quick": False, "volume_dialog_ts": 0.0, "last": "No action yet"}


def phone_action(phone: dict, key: str) -> str:
    """Apply one simulated Android action. Returns a human-readable result."""
    if key == "vol_up":
        phone["volume"] = min(phone["max"], phone["volume"] + 1)
        phone["muted"] = False
        phone["volume_dialog_ts"] = time.time()
        msg = f"Volume up -> {phone['volume']}/{phone['max']}"
    elif key == "vol_down":
        phone["volume"] = max(0, phone["volume"] - 1)
        phone["volume_dialog_ts"] = time.time()
        msg = f"Volume down -> {phone['volume']}/{phone['max']}"
    elif key == "show_volume":
        phone["volume_dialog_ts"] = time.time()
        msg = "Volume dialog shown"
    elif key == "cycle_ringer":
        phone["ringer"] = RINGER_MODES[(RINGER_MODES.index(phone["ringer"]) + 1) % len(RINGER_MODES)]
        msg = f"Ringer mode: {phone['ringer']}"
    elif key == "toggle_dnd":
        phone["dnd"] = not phone["dnd"]
        msg = f"Do Not Disturb {'on' if phone['dnd'] else 'off'}"
    elif key == "mute":
        phone["muted"] = True
        msg = "Muted"
    elif key == "unmute":
        phone["muted"] = False
        msg = "Unmuted"
    elif key == "toggle_mute":
        phone["muted"] = not phone["muted"]
        msg = "Muted" if phone["muted"] else "Unmuted"
    elif key == "voice_assistant":
        phone["app"] = "Voice assistant"
        msg = "Voice assistant launched"
    elif key == "camera":
        phone["app"] = "Camera"
        msg = "Camera opened"
    elif key == "settings":
        phone["app"] = "Settings"
        msg = "Settings opened"
    elif key == "notif_drawer":
        phone["drawer"] = not phone["drawer"]
        msg = "Notification drawer " + ("opened" if phone["drawer"] else "closed")
    elif key == "quick_settings":
        phone["quick"] = not phone["quick"]
        msg = "Quick settings " + ("opened" if phone["quick"] else "closed")
    elif key == "back":
        if phone["drawer"] or phone["quick"]:
            phone["drawer"] = phone["quick"] = False
        else:
            phone["app"] = None
        msg = "Went back"
    elif key == "home":
        phone["app"], phone["drawer"], phone["quick"] = None, False, False
        msg = "Home screen"
    else:
        raise ValueError(f"unknown phone action {key!r}")
    phone["last"] = msg
    return msg


def phone_action_label(key: str) -> str:
    for group in config.PHONE_ACTIONS.values():
        for k, _, label in group:
            if k == key:
                return label
    return key
