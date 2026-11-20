"""SQLite persistence shared by the patient app and the caregiver dashboard.

Different browser sessions (patient tablet, caregiver laptop) talk to each other through this file.
No Streamlit imports.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from typing import Any

from . import config

_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS alerts(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL,
        message TEXT NOT NULL, source TEXT, location TEXT, status TEXT NOT NULL DEFAULT 'open',
        ack_ts REAL, delivery TEXT)""",
    """CREATE TABLE IF NOT EXISTS requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, text TEXT NOT NULL,
        category TEXT, source TEXT, status TEXT NOT NULL DEFAULT 'open', done_ts REAL)""",
    """CREATE TABLE IF NOT EXISTS reminders(
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, hhmm TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'other', enabled INTEGER NOT NULL DEFAULT 1,
        last_ack_date TEXT, snooze_until REAL)""",
    """CREATE TABLE IF NOT EXISTS routine_log(
        day TEXT NOT NULL, routine TEXT NOT NULL, step TEXT NOT NULL, done INTEGER NOT NULL,
        PRIMARY KEY(day, routine, step))""",
    "CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL, detail TEXT)",
    "CREATE TABLE IF NOT EXISTS heartbeat(component TEXT PRIMARY KEY, ts REAL NOT NULL, status TEXT, detail TEXT)",
]

_ALERT_FIELDS = {"status", "ack_ts", "delivery"}
_inited_path = None


def _connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init() -> None:
    """Create tables (idempotent) and seed defaults on first run."""
    global _inited_path
    if _inited_path == str(config.DB_PATH) and config.DB_PATH.exists():
        return
    with closing(_connect()) as con:
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        for stmt in _SCHEMA:
            con.execute(stmt)
        con.commit()
    _inited_path = str(config.DB_PATH)
    if kv_get("seeded") is None:
        with closing(_connect()) as con:
            for title, hhmm, kind in config.DEFAULT_REMINDERS:
                con.execute("INSERT INTO reminders(title,hhmm,kind) VALUES(?,?,?)", (title, hhmm, kind))
            con.commit()
        kv_set("seeded", True)


def _rows(sql: str, args: tuple = ()) -> list[dict]:
    init()
    with closing(_connect()) as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


def _exec(sql: str, args: tuple = ()) -> int:
    init()
    with closing(_connect()) as con:
        cur = con.execute(sql, args)
        con.commit()
        return int(cur.lastrowid or 0)


# ------------------------------------------------------------------ key/value + preferences
def kv_get(key: str, default: Any = None) -> Any:
    with closing(_connect()) as con:
        try:
            row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        except sqlite3.OperationalError:       # table not created yet
            return default
    return json.loads(row["value"]) if row else default


def kv_set(key: str, value: Any) -> None:
    with closing(_connect()) as con:
        con.execute("CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)))
        con.commit()


def get_prefs() -> dict:
    init()
    stored = kv_get("prefs", {}) or {}
    prefs = dict(config.DEFAULT_PREFS)
    prefs.update({k: v for k, v in stored.items() if k in config.DEFAULT_PREFS})
    return prefs


def set_prefs(**changes: Any) -> dict:
    init()
    stored = kv_get("prefs", {}) or {}
    stored.update({k: v for k, v in changes.items() if k in config.DEFAULT_PREFS})
    kv_set("prefs", stored)
    return get_prefs()


def reset_prefs() -> None:
    kv_set("prefs", {})


# ------------------------------------------------------------------ alerts (emergency)
def add_alert(kind: str, message: str, source: str = "patient", location: str = "") -> int:
    return _exec("INSERT INTO alerts(ts,kind,message,source,location) VALUES(?,?,?,?,?)",
                 (time.time(), kind, message, source, location))


def get_alert(alert_id: int) -> dict | None:
    rows = _rows("SELECT * FROM alerts WHERE id=?", (alert_id,))
    return rows[0] if rows else None


def list_alerts(limit: int = 50, status: str | None = None) -> list[dict]:
    if status:
        return _rows("SELECT * FROM alerts WHERE status=? ORDER BY ts DESC LIMIT ?", (status, limit))
    return _rows("SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,))


def update_alert(alert_id: int, **fields: Any) -> None:
    fields = {k: v for k, v in fields.items() if k in _ALERT_FIELDS}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    _exec(f"UPDATE alerts SET {sets} WHERE id=?", (*fields.values(), alert_id))


# ------------------------------------------------------------------ assistance requests
def add_request(text: str, category: str = "need", source: str = "patient") -> int:
    return _exec("INSERT INTO requests(ts,text,category,source) VALUES(?,?,?,?)",
                 (time.time(), text, category, source))


def list_requests(limit: int = 50, status: str | None = None) -> list[dict]:
    if status:
        return _rows("SELECT * FROM requests WHERE status=? ORDER BY ts DESC LIMIT ?", (status, limit))
    return _rows("SELECT * FROM requests ORDER BY ts DESC LIMIT ?", (limit,))


def set_request_status(req_id: int, status: str) -> None:
    _exec("UPDATE requests SET status=?, done_ts=? WHERE id=?",
          (status, time.time() if status == "done" else None, req_id))


# ------------------------------------------------------------------ reminders & routines
def list_reminders() -> list[dict]:
    return _rows("SELECT * FROM reminders ORDER BY hhmm, id")


def add_reminder(title: str, hhmm: str, kind: str = "other") -> int:
    return _exec("INSERT INTO reminders(title,hhmm,kind) VALUES(?,?,?)", (title, hhmm, kind))


def update_reminder(rid: int, **fields: Any) -> None:
    allowed = {"title", "hhmm", "kind", "enabled", "last_ack_date", "snooze_until"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        _exec(f"UPDATE reminders SET {sets} WHERE id=?", (*fields.values(), rid))


def delete_reminder(rid: int) -> None:
    _exec("DELETE FROM reminders WHERE id=?", (rid,))


def routine_state(day: str, routine: str) -> dict[str, bool]:
    rows = _rows("SELECT step, done FROM routine_log WHERE day=? AND routine=?", (day, routine))
    return {r["step"]: bool(r["done"]) for r in rows}


def set_routine_step(day: str, routine: str, step: str, done: bool) -> None:
    _exec("INSERT INTO routine_log(day,routine,step,done) VALUES(?,?,?,?) "
          "ON CONFLICT(day,routine,step) DO UPDATE SET done=excluded.done", (day, routine, step, int(done)))


# ------------------------------------------------------------------ events + heartbeat
def log_event(kind: str, detail: Any = "") -> None:
    if not isinstance(detail, str):
        detail = json.dumps(detail, default=str)
    _exec("INSERT INTO events(ts,kind,detail) VALUES(?,?,?)", (time.time(), kind, detail))


def recent_events(limit: int = 100, kind: str | None = None) -> list[dict]:
    if kind:
        return _rows("SELECT * FROM events WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, limit))
    return _rows("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))


def beat(component: str, status: str = "ok", detail: str = "") -> None:
    _exec("INSERT INTO heartbeat(component,ts,status,detail) VALUES(?,?,?,?) "
          "ON CONFLICT(component) DO UPDATE SET ts=excluded.ts, status=excluded.status, detail=excluded.detail",
          (component, time.time(), status, detail))


def heartbeats() -> dict[str, dict]:
    return {r["component"]: r for r in _rows("SELECT * FROM heartbeat")}
