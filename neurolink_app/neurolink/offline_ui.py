"""Offline mode section (shown inside Settings): connection status and the "simulate poor connectivity" switch."""
import streamlit as st

from . import connectivity, db, ui


def _set_forced() -> None:
    db.set_prefs(offline_forced=bool(st.session_state.get("offline_toggle")))


def render_panels() -> None:
    """One panel: connection status, the test switch and what keeps working offline."""
    prefs = db.get_prefs()
    online_real = connectivity.network_online()
    effective = connectivity.effective_online(prefs)

    with st.container(key="panel_off1"):
        st.markdown('<div class="nl-label">📡 Offline mode</div>', unsafe_allow_html=True)
        if effective:
            ui.html('<div class="nl-chip green">🟢 <b>Online</b> - the connection is available.</div>')
        elif prefs["offline_forced"] and online_real:
            ui.html('<div class="nl-chip amber">🟡 <b>Offline mode (simulated)</b> - you switched off the connection for testing.</div>')
        else:
            ui.html('<div class="nl-chip amber">🟠 <b>No internet connection</b> - the app is using the road and signal data stored on this device.</div>')
        st.toggle("Simulate poor connectivity (test offline mode)", value=prefs["offline_forced"], key="offline_toggle", on_change=_set_forced)
        st.markdown('<div class="nl-label" style="margin-top:6px">What keeps working without a connection</div>', unsafe_allow_html=True)
        ui.html('<div class="nl-info">'
                '✅ <b>Helmet decoding</b> - the model runs on this device.<br>'
                '✅ <b>Text-to-speech</b> - uses the voices installed on the device.<br>'
                '✅ <b>Wheelchair control &amp; safety checks</b> - obstacle and vehicle logic is local.<br>'
                '✅ <b>Contextual navigation</b> - road map and traffic-signal timing are stored on this device.<br>'
                '✅ <b>Emergency</b> - reaches the dashboard on the same device/network; webhook alerts are queued and sent when the connection returns.<br>'
                '✅ <b>Reminders &amp; routines</b> - stored locally.</div>')
        pending = [a for a in db.list_alerts(40) if "webhook: pending" in (a["delivery"] or "")]
        if pending:
            st.warning(f"{len(pending)} alert(s) are waiting to be sent to the webhook.")
