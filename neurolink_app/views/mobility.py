"""Mobility Controller - drive / simulate the wheelchair with buttons or with the helmet (Left/Right),
contextual navigation to the next safe crossing, and the obstacle / vehicle safety checks."""
import time

import streamlit as st

from neurolink import brain, db, guidance, mobility, render, safety, signals, ui, worldctx

ss = st.session_state
ui.page_bar("mobility")
ui.model_banner()
prefs = db.get_prefs()
world = ss["world"]
bundle, _err = ui.get_bundle()
if "nav" not in ss:
    ss["nav"] = guidance.new_tracker()      # contextual-navigation state (chosen crossing, finished crossings)
    ss["nav_say"] = None

LABELS = {"forward": "Forward", "backward": "Backward", "stop": "Stop", "left": "Turn Left", "right": "Turn Right"}


def do_cmd(cmd: str) -> None:
    w = ss["world"]
    p = db.get_prefs()
    msg = mobility.command(w["chair"], cmd, p, w["obstacles"], w["vehicles"])
    ui.set_last_command(LABELS[cmd], None, "buttons")
    db.log_event("move", {"cmd": cmd, "result": msg})


def set_speed() -> None:
    db.set_prefs(speed_mps=float(ss["mob_speed"]))
    ss["world"]["chair"]["speed"] = float(ss["mob_speed"])


def reset_position() -> None:
    mobility.teleport(ss["world"]["chair"], *mobility.START)
    ss["world"]["vehicles"] = []
    ss["nav"] = guidance.new_tracker()
    ss["nav_say"] = None


def to_crossing() -> None:
    """Demo helper: put the wheelchair 25 m before the junction, facing it."""
    mobility.teleport(ss["world"]["chair"], 0.0, -25.0, 0.0)
    ss["nav"] = guidance.new_tracker()
    ss["nav_say"] = None


def next_crossing() -> None:
    """'Find another crossing': forget the current target (and avoid it for two minutes)."""
    guidance.reset(ss["nav"], time.time())
    ss["nav_say"] = None


# ---- simulated sensors (moved here from the removed Safety Integration page)
def add_vehicle(direction: str) -> None:
    """Drop a vehicle 45 m from the junction on the chosen approach so a warning appears within seconds."""
    w = ss["world"]
    sp = safety.VEHICLE_SPAWNS[direction]
    v = safety.spawn_vehicle(direction, speed=9.0, rng=w["rng"], vehicles=w["vehicles"])
    if sp["road"] == "main":
        v["x"] = -45.0 if sp["vx"] > 0 else 45.0
    else:
        v["y"] = -45.0 if sp["vy"] > 0 else 45.0
    db.log_event("safety_sim", f"vehicle {direction}")


def add_obstacle(kind: str) -> None:
    w = ss["world"]
    if kind == "obstacle":
        w["obstacles"].append(safety.obstacle_ahead(w["chair"], 4.5, "pole", "Obstacle"))
    else:
        w["obstacles"].append({**safety.obstacle_ahead(w["chair"], 3.5, "pothole", "Hazard: hole in path"), "r": 0.45})
    db.log_event("safety_sim", f"{kind} ahead")


def clear(what: str) -> None:
    w = ss["world"]
    if what in ("obstacles", "all"):
        w["obstacles"] = []
    if what in ("vehicles", "all"):
        w["vehicles"] = []


def toggle_traffic() -> None:
    ss["world"]["traffic_on"] = bool(ss.get("traffic_toggle"))


# --------------------------------------------------------------------------- d-pad + wheelchair picture
top = st.columns(2)
with top[0]:
    with st.container(key="panel_dpad"):
        st.markdown('<div class="nl-label">Control your movement:</div>', unsafe_allow_html=True)
        with st.container(key="dpad"):
            r = st.columns(3)
            with r[1]:
                ui.button("↑", key="dp_up", on_click=do_cmd, args=("forward",), help="Forward")
            r = st.columns(3)
            with r[0]:
                ui.button("←", key="dp_left", on_click=do_cmd, args=("left",), help="Turn left")
            with r[1]:
                ui.button("■ Stop", key="dp_stop", on_click=do_cmd, args=("stop",), help="Stop immediately")
            with r[2]:
                ui.button("→", key="dp_right", on_click=do_cmd, args=("right",), help="Turn right")
            r = st.columns(3)
            with r[1]:
                ui.button("↓", key="dp_down", on_click=do_cmd, args=("backward",), help="Reverse slowly")
        st.slider("Speed (m/s)", 0.3, 2.0, float(prefs["speed_mps"]), 0.1, key="mob_speed", on_change=set_speed)
with top[1]:
    with st.container(key="panel_chair"):
        st.markdown(render.svg_img(render.wheelchair_svg(), style="width:100%;max-width:330px;display:block;margin:0 auto"),
                    unsafe_allow_html=True)


# --------------------------------------------------------------------------- live simulation (re-runs by itself while moving)
def _maybe_auto_decode() -> None:
    """Auto-stream: read the helmet every N seconds and, in helmet mode, steer the chair with the result."""
    if not ss.get("auto_stream") or bundle is None:
        return
    now = time.time()
    if now - ss.get("last_auto", 0.0) < float(ss.get("auto_every", 4)):
        return
    ss["last_auto"] = now
    try:
        d = ui.decode_next(ss.get("replay_mode", "random"))
        if ss.get("control_mode") == "Helmet steering (Left / Right)":
            ui.run_decision_on_chair(d)
    except Exception as exc:                          # noqa: BLE001
        ss["auto_stream"] = False
        ui.flash("error", f"Auto-read stopped: {exc}")


def _safety_block(a: dict, p: dict) -> None:
    """Warnings for vehicles from other directions + the three obstacle sensors ahead."""
    ui.html(f'<div class="nl-label" style="margin-bottom:6px">🛡️ Safety: {ui.level_badge(a["level"])}</div>')
    ui.html(ui.warnings_html(a))
    rows = []
    for name in ("left", "center", "right"):
        d = a["sensors"][name]["dist"]
        frac = 0.0 if d is None else max(0.04, 1 - d / safety.SENSOR_RANGE)
        col = "#22c55e" if d is None or d >= p["slow_distance_m"] else ("#f59e0b" if d >= p["stop_distance_m"] else "#ef4444")
        label = "clear" if d is None else f"{d:.1f} m"
        rows.append(f'<div class="nl-dist"><span style="width:60px">{name.title()}</span><div class="t"><div style="width:{frac * 100:.0f}%;background:{col}"></div></div>'
                    f'<b style="width:60px;text-align:right">{label}</b></div>')
    ui.html("".join(rows))
    if ss["world"]["vehicles"]:
        st.caption(f"{len(ss['world']['vehicles'])} vehicle(s) tracked · stop distance {p['stop_distance_m']:.1f} m · "
                   f"vehicle horizons {p['vehicle_caution_s']:.0f}/{p['vehicle_danger_s']:.0f} s")


def _nav_block(nav: dict, ctx: dict) -> None:
    """Contextual navigation: crosswalks, pedestrian signals, road markings and step-by-step guidance."""
    st.markdown('<div class="nl-label">🧭 Contextual navigation</div>', unsafe_allow_html=True)
    if nav["state"] == "none":
        ui.html('<div class="nl-chip grey">No crosswalk is known in this area. Download the area in Settings → Offline mode.</div>')
        return
    chip = "green" if nav["safe"] and nav["state"] in ("wait", "cross", "done") else ("blue" if nav["state"] == "approach" else "amber")
    ui.html(f'<div class="nl-chip {chip}">🚸 <b>{render.esc(nav["headline"])}</b></div>')

    inter, ped = ctx["intersection"], ctx["ped"]
    if inter:
        secs = f"{ped['seconds_to_change']:.0f}" if ped else (f"{ctx['phase']['remaining']:.0f}" if ctx.get("phase") else "-")
        ui.html(f'<div class="nl-info"><b>✅ Intersection Detected</b> - {render.esc(inter["name"])}<div class="nl-big" style="font-size:1.35rem;margin-top:4px">'
                f'Next Signal Change in ~{secs} sec</div></div>')
    sig = nav["sig"]
    if sig is not None:
        cls = "green" if sig["walk"] else "red"
        ui.html(f'<div class="nl-chip {cls}" style="margin-top:8px">🚶 Pedestrian signal ({render.esc(nav["target"]["name"])}): '
                f'<b>{"WALK" if sig["walk"] else "DON’T WALK"}</b> &nbsp;·&nbsp; changes in ~{sig["change_in"]:.0f} s</div>')
    else:
        ui.html('<div class="nl-chip grey" style="margin-top:8px">🚶 No pedestrian signal data for this crossing - look and listen before crossing.</div>')

    icons = {"done": "✔", "current": "➜", "todo": ""}
    ui.html("".join(
        f'<div class="nl-step {s["status"]}"><span class="n">{icons[s["status"]] or i}</span><div><b>{render.esc(s["title"])}</b>'
        f'<div>{render.esc(s["text"])}</div></div></div>' for i, s in enumerate(nav["steps"], start=1)))

    ui.button("🔄 Find another crossing", key="nav_next", on_click=next_crossing)
    st.toggle("Speak the guidance aloud", value=True, key="guide_voice")

    found = guidance.detect(ctx["pack"], ss["world"]["chair"], ctx, time.time())
    with st.expander(f"Detected nearby ({len(found)})", expanded=False):
        if not found:
            st.caption("No crosswalks, pedestrian signals or road markings within 40 m.")
        for it in found:
            st.markdown(f'<div class="nl-kv"><span>{it["icon"]} {render.esc(it["text"])}</span><b>{it["distance"]:.0f} m · {it["where"]}</b></div>',
                        unsafe_allow_html=True)
        if nav["alternatives"]:
            st.caption("Other crossings: " + " · ".join(f"{a['name']} ({a['distance']:.0f} m{'' if a['signal'] else ', no signal'})"
                                                        for a in nav["alternatives"]))
    ui.html('<div class="nl-muted">Uses GPS and road data to identify intersections, crosswalks, pedestrian signals and road markings, '
            'and to find the next safe crossing.</div>')


def _world_panel() -> None:
    p = db.get_prefs()
    _maybe_auto_decode()
    ctx, a = worldctx.step(ss["world"], p)
    ch = ss["world"]["chair"]
    now = time.time()
    nav = guidance.plan(ss["nav"], ctx["pack"], ch, ctx, ss["world"]["vehicles"], p, now)

    ui.status_bar(f"♿ {mobility.describe(ch)}", f"Heading {ch['heading']:.0f}° · {ch['odometer']:.0f} m travelled · {ch['speed']:.1f} m/s")
    left, right = st.columns([3, 2])
    with left:
        with st.container(key="panel_map"):
            ui.html(ui.world_html(ss["world"], ctx, a, view_m=30.0, route=nav["route"],
                                  focus=nav["target"]["id"] if nav.get("target") else None))
            if ch["msg"] and now - ch["msg_ts"] < 8:
                st.caption(f"ℹ️ {ch['msg']}")
        with st.container(key="panel_safety"):
            _safety_block(a, p)
    with right:
        with st.container(key="panel_nav"):
            _nav_block(nav, ctx)

    # spoken announcements: danger warnings (at most one every 8 s) and the guidance (once per change)
    danger = [w for w in a["warnings"] if w["level"] == "danger"]
    if danger and ss.get("safety_voice", True) and now - ss.get("last_warn_ts", 0) > 8:
        ss["last_warn_ts"] = now
        ui.queue_speech("Warning! " + danger[0]["text"].split(" - ")[0])
        db.log_event("safety_warning", danger[0]["text"])
    sid = nav.get("say_id")
    if sid and sid != ss.get("nav_say"):
        ss["nav_say"] = sid
        if ss.get("guide_voice", True):
            ui.queue_speech(nav["say"])
    ui.flush_tts()


moving = world["chair"]["motion"] != "stop"
interval = 1.0 if (moving or world["vehicles"] or world["traffic_on"] or ss.get("auto_stream")) else 2.0     # 2 s keeps the signal countdown fresh
st.fragment(run_every=interval)(_world_panel)()

c = st.columns(2)
with c[0]:
    ui.button("↺ Reset position", key="reset_pos", on_click=reset_position)
with c[1]:
    ui.button("📍 Start near the junction", key="to_cross", on_click=to_crossing, help="Demo: place the wheelchair 25 m before the junction.")

# --------------------------------------------------------------------------- simulated sensors (vehicles, obstacles)
with st.container(key="panel_sim"):
    st.markdown('<div class="nl-label">Simulate what the sensors would see</div>', unsafe_allow_html=True)
    st.caption("A real build would feed these from the wheelchair's range sensors/camera and a vehicle-detection source. "
               "Here they are simulated so the warnings, the guidance and the automatic stop can be demonstrated.")
    sim = st.columns(2)
    with sim[0]:
        st.markdown("**Vehicle approaching from…**")
        c = st.columns(2)
        for i, (dirn, label) in enumerate([("from_west", "← West"), ("from_east", "East →"), ("from_south", "↑ South"), ("from_north", "↓ North")]):
            with c[i % 2]:
                ui.button(f"🚗 {label}", key=f"more_veh_{dirn}", on_click=add_vehicle, args=(dirn,))
        st.toggle("Random traffic on green", value=world["traffic_on"], key="traffic_toggle", on_change=toggle_traffic)
    with sim[1]:
        st.markdown("**Obstacles & hazards**")
        c = st.columns(2)
        with c[0]:
            ui.button("🧱 Obstacle ahead", key="more_ob", on_click=add_obstacle, args=("obstacle",))
            ui.button("Clear obstacles", key="more_clr_o", on_click=clear, args=("obstacles",))
        with c[1]:
            ui.button("🕳️ Hole ahead", key="more_hz", on_click=add_obstacle, args=("hazard",))
            ui.button("Clear vehicles", key="more_clr_v", on_click=clear, args=("vehicles",))
        st.toggle("Speak danger warnings aloud", value=True, key="safety_voice")


# --------------------------------------------------------------------------- helmet (BCI) section
def _helmet_view() -> None:
    d = ss["decisions"][-1] if ss["decisions"] else None
    win = ss.get("last_window")
    if d is None or win is None or bundle is None:
        st.caption("No helmet reading yet - press “Read helmet now”.")
        return
    cmd_txt = ("→ steers " + d.label.lower()) if d.accepted else "→ ignored (below the confidence gate)"
    pills = f'<span class="nl-tag-pill {"ok" if d.accepted else "warn"}">gate {d.gate:.0%}</span> '
    if d.truth:
        pills += f'<span class="nl-tag-pill {"ok" if d.correct else "warn"}">recorded label: {d.truth}{" ✓" if d.correct else " ✗"}</span> '
    pills += f'<span class="nl-tag-pill">{d.source}{" #" + str(d.trial_id) if d.trial_id else ""}</span>'
    ui.html(f'<div class="nl-decision">{render.esc(d.label)} <span class="nl-muted" style="font-size:1rem">{cmd_txt}</span></div><div>{pills}</div>')
    ui.html(render.probability_bar_html(d.proba, d.gate))
    ui.html(render.svg_img(render.eeg_svg(win, bundle.channels, bundle.fs, title="Helmet signal (preprocessed)")))
    f, pw = signals.psd(win, bundle.fs, bundle.welch_cfg)
    shares = signals.band_shares(f, pw, bundle.bands, bundle.total_band)
    q, notes = signals.quality(win)
    cols = st.columns([3, 2])
    with cols[0]:
        ui.html(render.svg_img(render.psd_svg(f, pw.mean(0), bundle.bands), style="width:100%;max-width:440px"))
    with cols[1]:
        for name, v in shares.items():
            st.progress(min(max(v, 0.0), 1.0), text=f"{name} {v:.0%}")
        st.caption(f"Signal quality (heuristic): {q:.0f}%" + (f" - {'; '.join(notes)}" if notes else ""))


with st.container(key="panel_helmet"):
    st.markdown('<div class="nl-label">🧠 Helmet (brain-computer interface)</div>', unsafe_allow_html=True)
    if bundle is None:
        st.info("The helmet decoder isn't loaded, so only the on-screen buttons are available. See the message at the top of the page.")
    else:
        st.radio("Control mode", ["Buttons only", "Helmet steering (Left / Right)"], key="control_mode", horizontal=True,
                 help="In helmet mode a confident Left/Right decision turns the wheelchair. Forward, reverse and Stop stay on the buttons.")
        src = st.radio("Signal source", ["Replay a recorded trial", "Upload a raw recording"], key="signal_source", horizontal=True)
        if src == "Replay a recorded trial":
            c = st.columns([3, 2])
            c[0].radio("Which trial", ["random", "sequential", "Left", "Right"], key="replay_mode", horizontal=True,
                       format_func=lambda x: {"random": "Random", "sequential": "Next in order", "Left": "A recorded Left",
                                              "Right": "A recorded Right"}[x])
            c[1].toggle("Auto-read every", key="auto_stream", help="Keeps reading the helmet while this page is open.")
            if ss.get("auto_stream"):
                st.slider("Seconds between readings", 2, 10, 4, key="auto_every")

            def read_now() -> None:
                try:
                    d = ui.decode_next(ss.get("replay_mode", "random"))
                    if ss.get("control_mode") == "Helmet steering (Left / Right)":
                        ui.run_decision_on_chair(d)
                    else:
                        ui.set_last_command(f"Helmet read: {d.label}", d.confidence, "helmet")
                except Exception as exc:                  # noqa: BLE001
                    ui.flash("error", f"Could not read the helmet: {exc}")

            ui.button("🧠 Read helmet now", key="read_helmet", on_click=read_now)
        else:
            st.caption("Upload one raw trial: a .csv/.xlsx with columns Time, FZ, C3, CZ, C4 (about 2500 rows at 250 Hz). "
                       "It is filtered with the partners' own `bci_preprocess.preprocess_file`.")
            up = st.file_uploader("Raw recording", type=["csv", "xlsx", "xls"], key="raw_upload", label_visibility="collapsed")
            if up is not None and ui.button("Decode this recording", key="decode_upload"):
                try:
                    window = brain.preprocess_upload(bundle, up.name, up.getvalue())
                    d = brain.decode_window(bundle, window, prefs["confidence_gate"], source="upload")
                    ss["last_window"] = window
                    ui.record_decision(d)
                    if ss.get("control_mode") == "Helmet steering (Left / Right)":
                        ui.run_decision_on_chair(d)
                    else:
                        ui.set_last_command(f"Helmet read: {d.label}", d.confidence, "helmet")
                    st.rerun()
                except Exception as exc:                  # noqa: BLE001
                    st.error(f"Could not process that file: {exc}")
        st.fragment(run_every=3.0 if ss.get("auto_stream") else None)(_helmet_view)()

        hist = ss["decisions"][-8:][::-1]
        if hist:
            with st.expander("Recent decisions"):
                st.dataframe([{"time": time.strftime("%H:%M:%S", time.localtime(h.ts)), "decision": h.label,
                               "confidence": f"{h.confidence:.1%}", "accepted": h.accepted, "recorded label": h.truth or "-",
                               "source": h.source} for h in hist], hide_index=True)
