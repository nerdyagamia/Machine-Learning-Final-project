"""Emergency - alert the caregiver / emergency contact."""
import time

import streamlit as st

from neurolink import connectivity, db, mobility, notify, render, ui, worldctx

ss = st.session_state
ui.page_bar("emergency")
prefs = db.get_prefs()

PHONE_SVG = ('<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><path d="M18 8l8 2 4 12-6 4c3 7 8 12 15 15l4-6 12 4 2 8c0 4-4 8-9 8C28 55 9 36 9 17c0-5 4-9 9-9z" fill="#fff"/>'
             '<path d="M40 8c8 1 15 8 16 16M40 17c4 1 7 4 8 8" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round"/></svg>')


def trigger() -> None:
    p = db.get_prefs()
    w = ss["world"]
    ctx = worldctx.context(w, p, record=False)
    loc = f"{p['location_name']} ({ctx['lat']:.5f}, {ctx['lon']:.5f})"
    msg = (f"{p['patient_name']} requested emergency assistance. Wheelchair: {mobility.describe(w['chair'])}. "
           f"Location: {loc}.")
    alert = notify.raise_alert("emergency", msg, source="patient", location=loc, prefs=p)
    ss["alert_id"] = alert["id"]
    ss["alarm_pending"] = True
    mobility.command(w["chair"], "stop", p)             # safety: never keep driving during an emergency
    ui.set_last_command("Emergency alert", None, "emergency")


def cancel() -> None:
    if ss.get("alert_id"):
        notify.cancel(ss["alert_id"])
    ss["alert_id"] = None
    ui.flash("success", "Alert cancelled. Your caregiver has been told it was cancelled.")


def current_alert():
    aid = ss.get("alert_id")
    a = db.get_alert(aid) if aid else None
    return a if a and a["status"] in ("open", "acknowledged") else None


alert = current_alert()
phone = (prefs.get("caregiver_phone") or "").strip()

with st.container(key="panel_emerg"):
    if alert:
        ui.html(f'<div class="nl-emerg">{PHONE_SVG}<div class="big">Emergency Assistance<br>Requested!</div>'
                f'<div class="small">Alert sent to caregiver.</div></div>')

        def _status() -> None:
            a = current_alert()
            if not a:
                st.rerun()
                return
            t = time.strftime("%H:%M:%S", time.localtime(a["ts"]))
            if a["status"] == "acknowledged":
                ui.html(f'<div class="nl-chip green">✅ <b>{render.esc(prefs["caregiver_name"])} acknowledged</b> at '
                        f'{time.strftime("%H:%M:%S", time.localtime(a["ack_ts"] or a["ts"]))} - help is on the way.</div>')
            else:
                ui.html(f'<div class="nl-chip amber">⏳ Sent at {t} - waiting for {render.esc(prefs["caregiver_name"])} to acknowledge…</div>')
            ui.html(f'<div class="nl-muted">Delivery: {render.esc(a["delivery"] or "-")}</div>')

        st.fragment(run_every=3.0)(_status)()
        pending = ss.pop("alarm_pending", False)
        ui.embed_html(ui.alarm_bar_doc("Emergency! I need help!", ui.tts_lang(prefs), prefs["tts_rate"], prefs["tts_pitch"],
                                       prefs["tts_volume"], pending and prefs.get("tts_enabled", True),
                                       prefs.get("alarm_sound", True)), height=70)
    else:
        ui.html(f'<div class="nl-emerg idle">{PHONE_SVG}<div class="big">Need urgent help?</div>'
                f'<div class="small">Press the button below to alert your caregiver.</div></div>')
        ui.button("🆘  Send emergency alert", key="sos", on_click=trigger)

    c = st.columns(2)
    with c[0]:
        if phone:
            ui.link_button(f"📞 Call Caregiver ({prefs['caregiver_name']})", f"tel:{phone}")
        else:
            ui.button("📞 Call Caregiver (add a phone number first)", key="call_disabled", disabled=True)
    with c[1]:
        ui.link_button(f"🚑 Call emergency services ({prefs['emergency_number']})", f"tel:{prefs['emergency_number']}")
    if alert:
        ui.button("Cancel Alert", key="cancel_alert", on_click=cancel)
    elif not phone:
        st.caption("Tip: add the caregiver's phone number in Settings → Caregiver Dashboard → Preferences.")

with st.container(key="panel_emerg2"):
    st.markdown('<div class="nl-label">Recent alerts</div>', unsafe_allow_html=True)
    rows = db.list_alerts(6)
    if not rows:
        st.caption("No alerts so far.")
    for a in rows:
        icon = {"open": "🔴", "acknowledged": "🟠", "resolved": "🟢", "cancelled": "⚪"}.get(a["status"], "•")
        st.markdown(f'<div class="nl-kv"><span>{icon} {render.esc(a["message"][:90])}</span><b>{time.strftime("%d %b %H:%M", time.localtime(a["ts"]))} · {a["status"]}</b></div>',
                    unsafe_allow_html=True)
    if not connectivity.effective_online(prefs):
        st.caption("📡 Offline: the alert is stored locally and reaches the dashboard immediately; any webhook delivery is queued until the connection returns.")
