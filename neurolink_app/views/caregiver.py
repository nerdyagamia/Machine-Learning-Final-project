"""Caregiver Dashboard - receive assistance requests and emergency alerts, configure the user's preferences."""
import time

import streamlit as st

from neurolink import connectivity, db, notify, render, ui

ss = st.session_state
ui.page_bar("caregiver")
prefs = db.get_prefs()

# ------------------------------------------------------------------ PIN gate (keeps the patient from changing settings by accident)
if not ss.get("caregiver_ok"):
    with st.container(key="panel_pin"):
        st.markdown('<div class="nl-h" style="font-size:1.5rem">Caregiver access</div>'
                    '<div class="nl-sub">Enter the PIN to continue (default 1234 - change it in Preferences).</div>', unsafe_allow_html=True)
        with st.form("pin_form"):
            pin = st.text_input("PIN", type="password", label_visibility="collapsed", placeholder="PIN", key="cg_pin_input")
            if ui.form_submit("Unlock", key="pin_btn"):
                if pin == prefs["caregiver_pin"]:
                    ss["caregiver_ok"] = True
                    st.rerun()
                else:
                    st.error("Wrong PIN.")
        st.caption("This PIN is a convenience lock for a shared device, not strong security.")
    st.stop()


def lock() -> None:
    ss["caregiver_ok"] = False


def ack(aid: int) -> None:
    notify.acknowledge(aid)


def resolve(aid: int) -> None:
    notify.resolve(aid)


def done(rid: int) -> None:
    db.set_request_status(rid, "done")


c = st.columns([5, 1])
with c[1]:
    ui.button("🔒 Lock", key="lock_btn", on_click=lock)

tabs = st.tabs(["🔔 Requests & alerts", "🛠️ Preferences"])


# ------------------------------------------------------------------ requests & alerts (live)
def _alerts_view() -> None:
    open_alerts = [a for a in db.list_alerts(30) if a["status"] in ("open", "acknowledged")]
    open_reqs = db.list_requests(30, "open")
    m = st.columns(3)
    m[0].metric("Emergency alerts", len(open_alerts))
    m[1].metric("Open requests", len(open_reqs))
    m[2].metric("Updated", time.strftime("%H:%M:%S"))
    if open_alerts:
        st.markdown('<div class="nl-label">🚨 Emergency alerts</div>', unsafe_allow_html=True)
    for a in open_alerts:
        ui.html(f'<div class="nl-alert {a["status"]}"><div class="hd">🚨 {render.esc(a["kind"].title())} · {a["status"]}</div>'
                f'<div>{render.esc(a["message"])}</div><div class="meta">{time.strftime("%d %b %H:%M:%S", time.localtime(a["ts"]))}'
                f' · {connectivity.age_text(a["ts"])} · {render.esc(a["delivery"] or "")}</div></div>')
        cc = st.columns(2)
        with cc[0]:
            ui.button("✔ Acknowledge - I'm on my way", key=f"ack_{a['id']}", on_click=ack, args=(a["id"],), disabled=a["status"] != "open")
        with cc[1]:
            ui.button("Mark resolved", key=f"res_{a['id']}", on_click=resolve, args=(a["id"],))
    st.markdown('<div class="nl-label" style="margin-top:8px">🙋 Assistance requests</div>', unsafe_allow_html=True)
    if not open_reqs:
        st.caption("No open requests.")
    for q in open_reqs:
        cc = st.columns([6, 2], vertical_alignment="center")
        cc[0].markdown(f'<div class="nl-alert"><div class="hd">{render.esc(q["text"])}</div>'
                       f'<div class="meta">{q["source"]} · {time.strftime("%H:%M", time.localtime(q["ts"]))} · {connectivity.age_text(q["ts"])}</div></div>',
                       unsafe_allow_html=True)
        with cc[1]:
            ui.button("✔ Done", key=f"done_{q['id']}", on_click=done, args=(q["id"],))
    hist = [r for r in db.list_requests(12) if r["status"] != "open"]
    if hist:
        with st.expander("Handled requests"):
            st.dataframe([{"time": time.strftime("%d %b %H:%M", time.localtime(r["ts"])), "request": r["text"], "status": r["status"]} for r in hist],
                         hide_index=True)


with tabs[0]:
    st.fragment(run_every=5.0)(_alerts_view)()


# ------------------------------------------------------------------ preferences
with tabs[1]:
    ui.prefs_form(["contacts", "voice", "display", "helmet", "safety", "location", "security"], "cg_prefs")
