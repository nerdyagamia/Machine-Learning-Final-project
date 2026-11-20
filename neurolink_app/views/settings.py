"""Settings - the patient-facing preferences, model information, maintenance and Offline mode."""
import streamlit as st

from neurolink import db, offline_ui, ui

ss = st.session_state
ui.page_bar("settings")
ui.model_banner()

with st.container(key="panel_settings"):
    ui.prefs_form(["voice", "display", "helmet"], "user_prefs")

with st.container(key="panel_settings2"):
    st.markdown('<div class="nl-label">Helmet decoder</div>', unsafe_allow_html=True)
    bundle, err = ui.get_bundle()
    if bundle is None:
        st.error(err or "Model not loaded.")
        st.button("Try loading the model again", key="reload_model", on_click=ui.reload_model)
    else:
        meta = bundle.meta
        rows = [("Model", meta.get("model", "?")), ("Channels", ", ".join(bundle.channels)), ("Sampling rate", f"{bundle.fs:.0f} Hz"),
                ("Band-pass / notch", f"{bundle.prep_cfg['bandpass'][0]:.0f}-{bundle.prep_cfg['bandpass'][1]:.0f} Hz / {bundle.prep_cfg['notch_hz']:.0f} Hz"),
                ("Classes", ", ".join(f"{k}={v}" for k, v in bundle.labels.items())),
                ("Window", f"{bundle.n_times} samples ({bundle.n_times / bundle.fs:.1f} s) × {bundle.n_channels} channels")]
        for k, v in rows:
            st.markdown(f'<div class="nl-kv"><span>{k}</span><b>{v}</b></div>', unsafe_allow_html=True)
        st.caption(meta.get("caveat", ""))

    st.markdown('<div class="nl-label" style="margin-top:14px">Maintenance</div>', unsafe_allow_html=True)

    def reset_prefs() -> None:
        db.reset_prefs()
        ui.flash("success", "All preferences were reset to their defaults.")

    c = st.columns(2)
    with c[0]:
        ui.button("↺ Reset preferences to defaults", key="reset_prefs", on_click=reset_prefs)
    with c[1]:
        if ui.button("👥 Open the Caregiver Dashboard", key="to_cg"):
            st.switch_page(ui.PAGES["caregiver"][0])
    st.caption("Contacts, safety thresholds and location are configured by the caregiver (Caregiver Dashboard → Preferences).")

# ------------------------------------------------------------------ Offline mode (moved here from its own page)
offline_ui.render_panels()
