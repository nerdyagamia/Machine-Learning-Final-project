"""NeuroLink - assistive helmet (BCI) companion app.

Run:   streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="NeuroLink", page_icon="🧠", layout="wide", initial_sidebar_state="collapsed")

from neurolink import ui  # noqa: E402  (must come after set_page_config)

# One real page (own URL) per feature. The built-in sidebar menu is hidden: navigation is the tile layout.
pages = [st.Page(path, title=title, url_path=key, default=(key == "home")) for key, (path, title, _icon) in ui.PAGES.items()]
try:
    nav = st.navigation(pages, position="hidden")
except TypeError:                       # very old Streamlit without `position`
    nav = st.navigation(pages)

ui.bootstrap()      # state, theme, heartbeat, header
nav.run()           # the selected page
ui.flush_tts()      # speak anything queued during this run (reminders, announcements)
