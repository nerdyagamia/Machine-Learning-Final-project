"""Network / system-health helpers. No Streamlit imports."""
from __future__ import annotations

import socket
import time

_cache: dict = {"t": 0.0, "v": None}


def network_online(timeout: float = 0.8, ttl: float = 8.0) -> bool:
    """True if a TCP connection to a public DNS host works. Result cached for `ttl` seconds."""
    now = time.time()
    if _cache["v"] is not None and now - _cache["t"] < ttl:
        return bool(_cache["v"])
    ok = False
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                ok = True
                break
        except OSError:
            continue
    _cache.update(t=now, v=ok)
    return ok


def effective_online(prefs: dict) -> bool:
    """Online for the app's purposes: real connection AND the 'simulate poor connectivity' switch is off."""
    return (not prefs.get("offline_forced", False)) and network_online()


def age_text(ts: float | None, now: float | None = None) -> str:
    if not ts:
        return "never"
    s = max(0, int((now or time.time()) - ts))
    if s < 5:
        return "just now"
    if s < 90:
        return f"{s}s ago"
    if s < 5400:
        return f"{s // 60} min ago"
    if s < 172800:
        return f"{s // 3600} h ago"
    return f"{s // 86400} d ago"
