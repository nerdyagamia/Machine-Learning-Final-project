"""Home - "Welcome! What would you like to do?" (layout of the NeuroLink mock-up)."""
import streamlit as st

from neurolink import render, ui

ss = st.session_state

ui.show_flash()
ui.reminder_banner()

with st.container(key="panel_home"):
    st.markdown('<div class="nl-h">Welcome!</div><div class="nl-sub">What would you like to do?</div>', unsafe_allow_html=True)

    cols = st.columns(3)
    with cols[0]:
        ui.tile("comm", "💬", "Communication", "communication")
    with cols[1]:
        ui.tile("mobility", "♿", "Mobility\nController", "mobility")
    with cols[2]:
        ui.tile("emergency", "⚠️", "Emergency", "emergency")

    cols = st.columns(3)
    with cols[0]:
        ui.tile("daily", "🗓️", "Daily Assistant", "daily")
    with cols[1]:
        ui.tile("caregiver", "👥", "Caregiver\nDashboard", "caregiver")
    with cols[2]:
        ui.tile("settings", "⚙️", "Settings", "settings")

    lc = ss["last_command"]
    conf = "--" if lc["conf"] is None else f"{lc['conf']:.0%}"
    ui.status_bar(f"Last Command: {render.esc(lc['text'])}", f"Confidence: {conf}")
