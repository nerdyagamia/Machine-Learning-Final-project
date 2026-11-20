"""Alert the caregiver. Always writes to the shared database (what the Caregiver Dashboard reads);
optionally also POSTs JSON to a webhook (e.g. a Telegram/Slack/Zapier bridge) when configured.
Webhook deliveries that fail or happen offline stay 'pending' and are retried by `flush_pending`.

No Streamlit imports.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import connectivity, db


def _valid_url(url: str) -> bool:
    u = urlparse(url.strip())
    return u.scheme in ("http", "https") and bool(u.netloc)


def _post(url: str, payload: dict, timeout: float = 5.0) -> tuple[bool, str]:
    if not _valid_url(url):
        return False, "invalid URL (http/https only)"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "User-Agent": "NeuroLink/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:                # noqa: S310 (validated above)
            return 200 <= r.status < 300, f"HTTP {r.status}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, str(getattr(exc, "reason", exc))[:80]


def _payload(alert: dict, prefs: dict) -> dict:
    return {"app": "NeuroLink", "id": alert["id"], "kind": alert["kind"], "message": alert["message"],
            "patient": prefs.get("patient_name"), "location": alert.get("location"),
            "timestamp": alert["ts"], "source": alert.get("source")}


def raise_alert(kind: str, message: str, *, source: str = "patient", location: str = "",
                prefs: dict | None = None) -> dict:
    """Create an alert. Returns the stored alert row (with its delivery summary)."""
    prefs = prefs or db.get_prefs()
    aid = db.add_alert(kind, message, source, location)
    delivery = ["dashboard: delivered"]
    url = (prefs.get("webhook_url") or "").strip()
    if url:
        alert = db.get_alert(aid)
        if connectivity.effective_online(prefs):
            ok, info = _post(url, _payload(alert, prefs))
            delivery.append("webhook: sent" if ok else f"webhook: pending ({info})")
        else:
            delivery.append("webhook: pending (offline)")
    db.update_alert(aid, delivery="; ".join(delivery))
    db.log_event("alert", {"id": aid, "kind": kind, "message": message})
    return db.get_alert(aid)


def flush_pending(prefs: dict | None = None, limit: int = 5) -> int:
    """Retry webhook deliveries that are still pending. Returns how many were sent."""
    prefs = prefs or db.get_prefs()
    url = (prefs.get("webhook_url") or "").strip()
    if not url or not connectivity.effective_online(prefs):
        return 0
    sent = 0
    for alert in db.list_alerts(limit=30):
        if sent >= limit:
            break
        if alert["status"] == "cancelled" or "webhook: pending" not in (alert.get("delivery") or ""):
            continue
        ok, info = _post(url, _payload(alert, prefs))
        if ok:
            parts = [p for p in (alert["delivery"] or "").split("; ") if p and not p.startswith("webhook")]
            db.update_alert(alert["id"], delivery="; ".join(parts + ["webhook: sent (retried)"]))
            sent += 1
    return sent


def acknowledge(alert_id: int) -> None:
    db.update_alert(alert_id, status="acknowledged", ack_ts=time.time())
    db.log_event("alert_ack", {"id": alert_id})


def resolve(alert_id: int) -> None:
    db.update_alert(alert_id, status="resolved", ack_ts=time.time())


def cancel(alert_id: int) -> None:
    db.update_alert(alert_id, status="cancelled")
    db.log_event("alert_cancel", {"id": alert_id})
