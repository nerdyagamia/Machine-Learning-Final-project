"""Communication Center - speak phrases, communicate needs, free-text text-to-speech."""
import time

import streamlit as st

from neurolink import config, db, render, ui

ss = st.session_state
ui.page_bar("communication")
prefs = db.get_prefs()
lang = prefs["language"]


def say(key: str, text: str) -> None:
    """Speak a phrase; needs (thirsty, hungry, help, pain...) also reach the caregiver dashboard."""
    p = db.get_prefs()
    ui.speak(text)
    ui.set_last_command(f"Said: {text}", None, "communication")
    if key in config.NEED_PHRASES and p.get("notify_on_need", True):
        db.add_request(text, "need", "communication")
        ui.flash("success", f"“{text}” - your caregiver has been notified.")


def say_free() -> None:
    text = (ss.get("free_text") or "").strip()
    if text:
        ui.speak(text)
        ui.set_last_command(f"Said: {text}", None, "communication")


def set_language() -> None:
    db.set_prefs(language="ar" if ss["comm_lang"] == "العربية" else "en")


def add_custom() -> None:
    text = (ss.get("new_phrase") or "").strip()
    if text:
        items = db.kv_get("custom_phrases", [])
        if text not in items:
            db.kv_set("custom_phrases", (items + [text])[-12:])
        ss["new_phrase"] = ""


def delete_custom(i: int) -> None:
    items = db.kv_get("custom_phrases", [])
    if 0 <= i < len(items):
        db.kv_set("custom_phrases", items[:i] + items[i + 1:])


with st.container(key="panel_comm"):
    head = st.columns([3, 2], vertical_alignment="center")
    head[0].markdown('<div class="nl-label">Select a phrase to speak:</div>', unsafe_allow_html=True)
    with head[1]:
        st.radio("Language", ["English", "العربية"], index=1 if lang == "ar" else 0, horizontal=True, key="comm_lang",
                 on_change=set_language, label_visibility="collapsed")

    for i in range(0, len(config.CORE_PHRASES), 2):
        cols = st.columns(2)
        for col, (key, en, ar, icon, _cls) in zip(cols, config.CORE_PHRASES[i:i + 2]):
            text = ar if lang == "ar" else en
            with col:
                ui.button(f"{icon}  {text}", key=f"ph_{key}", on_click=say, args=(key, text))

    ui.speech_bar()

with st.container(key="panel_comm2"):
    tab_more, tab_type, tab_hist = st.tabs(["More phrases", "Type a message", "Recently said"])

    with tab_more:
        more = config.MORE_PHRASES
        for i in range(0, len(more), 2):
            cols = st.columns(2)
            for col, (key, en, ar) in zip(cols, more[i:i + 2]):
                text = ar if lang == "ar" else en
                with col:
                    ui.button(text, key=f"more_{key}", on_click=say, args=(key, text))
        custom = db.kv_get("custom_phrases", [])
        if custom:
            st.markdown('<div class="nl-label" style="margin-top:12px">My phrases</div>', unsafe_allow_html=True)
            for i, text in enumerate(custom):
                c = st.columns([6, 1])
                with c[0]:
                    ui.button(text, key=f"more_c{i}", on_click=say, args=(f"custom{i}", text))
                with c[1]:
                    st.button("🗑", key=f"delc_{i}", on_click=delete_custom, args=(i,), help="Remove this phrase")
        c = st.columns([5, 2], vertical_alignment="bottom")
        c[0].text_input("Add my own phrase", key="new_phrase", placeholder="e.g. Please open the window")
        with c[1]:
            ui.button("➕ Save phrase", key="add_phrase", on_click=add_custom)

    with tab_type:
        st.text_area("Message", key="free_text", height=110, placeholder="Type what you want to say…",
                     label_visibility="collapsed")
        ui.button("🔊 Speak", key="speak_free", on_click=say_free)
        st.caption("Text-to-speech runs in your browser using your device's voices, so it works offline "
                   "(Arabic needs an Arabic voice installed on the device).")

    with tab_hist:
        rows = [e for e in db.recent_events(60, "speak")][:8]
        if not rows:
            st.caption("Nothing spoken yet.")
        for e in rows:
            t = time.strftime("%H:%M:%S", time.localtime(e["ts"]))
            st.markdown(f'<div class="nl-kv"><span>{render.esc(e["detail"])}</span><b>{t}</b></div>', unsafe_allow_html=True)

if prefs.get("notify_on_need", True):
    st.caption("ℹ️ When you say you are thirsty, hungry, in pain or need help, your caregiver also receives a request on the Caregiver Dashboard.")
