"""Daily Assistant - reminders, routines, daily needs and (simulated) phone controls."""
import datetime as dt
import time

import streamlit as st

from neurolink import assistant, config, db, render, ui

ss = st.session_state
ui.page_bar("daily")
prefs = db.get_prefs()
now = assistant.local_now(prefs)
today = now.strftime("%Y-%m-%d")

ui.reminder_banner()


# ------------------------------------------------------------------ callbacks
def ack(rid: int) -> None:
    db.update_reminder(rid, last_ack_date=today, snooze_until=None)
    db.log_event("reminder_done", rid)


def snooze(rid: int) -> None:
    db.update_reminder(rid, snooze_until=time.time() + 600)


def toggle_reminder(rid: int, enabled: bool) -> None:
    db.update_reminder(rid, enabled=int(enabled))


def remove_reminder(rid: int) -> None:
    db.delete_reminder(rid)


def set_step(routine: str, step: str, key: str) -> None:
    db.set_routine_step(today, routine, step, bool(ss.get(key)))


def need(label: str, sentence: str) -> None:
    db.add_request(sentence, "need", "daily-assistant")
    ui.queue_speech(sentence)
    ui.set_last_command(f"Need: {label}", None, "daily-assistant")
    ui.flash("success", f"Sent to your caregiver: “{sentence}”")


def send_free_need() -> None:
    text = (ss.get("free_need") or "").strip()
    if text:
        db.add_request(text, "need", "daily-assistant")
        ui.queue_speech(text)
        ss["free_need"] = ""
        ui.flash("success", f"Sent to your caregiver: “{text}”")


def phone(key: str) -> None:
    msg = assistant.phone_action(ss["phone"], key)
    ui.set_last_command(f"Phone: {msg}", None, "daily-assistant")


tabs = st.tabs(["⏰ Reminders", "✅ Routines", "🙋 Daily needs", "📱 Phone controls"])

# ------------------------------------------------------------------ reminders
with tabs[0]:
    reminders = db.list_reminders()
    st.markdown(f'<div class="nl-label">Today · {now:%A %d %B} · {now:%H:%M}</div>', unsafe_allow_html=True)
    if not reminders:
        st.caption("No reminders yet - add one below.")
    for r in reminders:
        status = assistant.reminder_status(r, now)
        icon = config.REMINDER_ICONS.get(r["kind"], "⏰")
        chip = {"done": "✔ done", "due": "● due now", "upcoming": "upcoming", "snoozed": "snoozed", "missed": "missed", "off": "off"}[status]
        cls = {"due": "due", "done": "done", "missed": "missed"}.get(status, "")
        ui.html(f'<div class="nl-rem {cls}"><span class="ic">{icon}</span><span class="tt">{render.esc(r["title"])}'
                f'<div class="nl-muted">{chip}</div></span><span class="tm">{r["hhmm"]}</span></div>')
        if status in ("due", "missed", "snoozed"):
            c = st.columns(2)
            with c[0]:
                ui.button("✔ Done", key=f"da_done_{r['id']}", on_click=ack, args=(r["id"],))
            with c[1]:
                ui.button("⏰ Snooze 10 min", key=f"da_snz_{r['id']}", on_click=snooze, args=(r["id"],))
    with st.expander("➕ Add or manage reminders"):
        with st.form("add_reminder", clear_on_submit=True):
            c = st.columns([4, 2, 2])
            title = c[0].text_input("What should I remind you about?", key="new_rem_title")
            when = c[1].time_input("Time", value=dt.time(9, 0), step=300, key="new_rem_time")
            kind = c[2].selectbox("Type", list(config.REMINDER_ICONS), format_func=lambda k: f"{config.REMINDER_ICONS[k]} {k}", key="new_rem_kind")
            if ui.form_submit("Add reminder", key="add_rem_btn"):
                if title.strip():
                    db.add_reminder(title.strip(), when.strftime("%H:%M"), kind)
                    ui.flash("success", "Reminder added.")
                    st.rerun()
                else:
                    st.error("Please type what the reminder is for.")
        for r in reminders:
            c = st.columns([5, 2, 1], vertical_alignment="center")
            c[0].markdown(f"{config.REMINDER_ICONS.get(r['kind'], '⏰')} **{r['hhmm']}** - {render.esc(r['title'])}")
            with c[1]:
                st.toggle("On", value=bool(r["enabled"]), key=f"da_on_{r['id']}",
                          on_change=lambda rid=r["id"]: toggle_reminder(rid, bool(ss.get(f"da_on_{rid}"))))
            with c[2]:
                st.button("🗑", key=f"da_del_{r['id']}", on_click=remove_reminder, args=(r["id"],), help="Delete")

# ------------------------------------------------------------------ routines
with tabs[1]:
    names = list(config.ROUTINES)
    routine = st.radio("Routine", names, horizontal=True, key="routine_pick", label_visibility="collapsed")
    steps = config.ROUTINES[routine]
    state = db.routine_state(today, routine)
    done_n = sum(1 for s in steps if state.get(s))
    st.progress(done_n / len(steps), text=f"{done_n} of {len(steps)} done today")
    for i, step in enumerate(steps):
        k = f"rt_{today}_{routine}_{i}"
        st.checkbox(step, value=state.get(step, False), key=k, on_change=set_step, args=(routine, step, k))
    if done_n == len(steps):
        st.success("All done - well done! 🎉")

# ------------------------------------------------------------------ daily needs
with tabs[2]:
    st.markdown('<div class="nl-label">Tap what you need - your caregiver gets a request and your device says it aloud.</div>',
                unsafe_allow_html=True)
    for i in range(0, len(config.DAILY_NEEDS), 2):
        cols = st.columns(2)
        for col, (key, icon, label, sentence) in zip(cols, config.DAILY_NEEDS[i:i + 2]):
            with col:
                ui.button(f"{icon}  {label}", key=f"more_need_{key}", on_click=need, args=(label, sentence))
    c = st.columns([5, 2], vertical_alignment="bottom")
    c[0].text_input("Something else", key="free_need", placeholder="Type a request for your caregiver…")
    with c[1]:
        ui.button("Send", key="send_need", on_click=send_free_need)
    open_reqs = db.list_requests(5, "open")
    if open_reqs:
        st.markdown('<div class="nl-label" style="margin-top:10px">Waiting for your caregiver</div>', unsafe_allow_html=True)
        for q in open_reqs:
            st.markdown(f'<div class="nl-kv"><span>{render.esc(q["text"])}</span><b>{time.strftime("%H:%M", time.localtime(q["ts"]))}</b></div>',
                        unsafe_allow_html=True)

# ------------------------------------------------------------------ phone controls
with tabs[3]:
    ph = ss["phone"]
    st.caption("A simulated phone: these are the same kinds of actions as an Android key-mapper (volume, Do Not Disturb, camera, "
               "navigation). A web app cannot press real Android buttons - connect a real controller to `assistant.phone_action` to do that.")
    left, right = st.columns([3, 2])
    with left:
        for group, items in config.PHONE_ACTIONS.items():
            st.markdown(f'<div class="nl-label" style="margin-top:6px">{group}</div>', unsafe_allow_html=True)
            for i in range(0, len(items), 2):
                cols = st.columns(2)
                for col, (key, icon, label) in zip(cols, items[i:i + 2]):
                    with col:
                        ui.button(f"{icon}  {label}", key=f"more_ph_{key}", on_click=phone, args=(key,))
    with right:
        vol_pct = 0 if ph["muted"] else int(100 * ph["volume"] / ph["max"])
        dialog = f'<div class="vol">🔊 Volume {ph["volume"]}/{ph["max"]}{" (muted)" if ph["muted"] else ""}<div class="tr"><div style="width:{vol_pct}%"></div></div></div>' \
            if time.time() - ph["volume_dialog_ts"] < 6 else ""
        drawer = '<div class="drawer">🔔 Notifications<br>• Reminder: take medication<br>• Message from caregiver</div>' if ph["drawer"] else ""
        quick = '<div class="drawer">⚡ Quick settings: Wi-Fi · Bluetooth · Torch · Rotate</div>' if ph["quick"] else ""
        app = ph["app"] or "Home screen"
        ui.html(f'<div class="nl-phone"><div class="scr"><div class="row"><span>{now:%H:%M}</span>'
                f'<span>{"⛔ DND · " if ph["dnd"] else ""}{ {"Ring": "🔔", "Vibrate": "📳", "Silent": "🔕"}[ph["ringer"]] } {ph["ringer"]}</span></div>'
                f'{drawer}{quick}<div class="app">{render.esc(app)}</div>{dialog}</div></div>')
        st.caption(f"Last action: {ph['last']}")
