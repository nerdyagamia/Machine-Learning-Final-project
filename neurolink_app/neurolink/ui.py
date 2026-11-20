"""Streamlit helpers shared by every page: theme, header, navigation, state, TTS, cached resources."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import streamlit as st

from . import assistant, brain, config, connectivity, db, mobility, notify, render, roadgeo, worldctx

# key -> (script, title, icon)
PAGES = {
    "home": ("views/home.py", "Home", "🏠"),
    "communication": ("views/communication.py", "Communication", "💬"),
    "mobility": ("views/mobility.py", "Mobility Controller", "♿"),
    "emergency": ("views/emergency.py", "Emergency", "🚨"),
    "daily": ("views/daily_assistant.py", "Daily Assistant", "🗓️"),
    "caregiver": ("views/caregiver.py", "Caregiver Dashboard", "👥"),
    "settings": ("views/settings.py", "Settings", "⚙️"),
}


# --------------------------------------------------------------------------- version-tolerant widgets
def _stretch(fn, *args, **kw):
    """Streamlit replaced `use_container_width=True` with `width="stretch"`; support both."""
    try:
        return fn(*args, width="stretch", **kw)
    except TypeError:
        return fn(*args, use_container_width=True, **kw)


def button(label: str, **kw):
    return _stretch(st.button, label, **kw)


def link_button(label: str, url: str, **kw):
    return _stretch(st.link_button, label, url, **kw)


def form_submit(label: str, **kw):
    return _stretch(st.form_submit_button, label, **kw)


def html(markup: str) -> None:
    st.markdown(render.collapse_html(markup), unsafe_allow_html=True)


def embed_html(doc: str, height: int = 1) -> None:
    """Show a self-contained HTML document in an iframe (needed for JavaScript: text-to-speech, alarm)."""
    doc = doc.strip()
    if hasattr(st, "iframe"):                       # newer Streamlit
        try:
            st.iframe(doc, height=max(int(height), 1))
            return
        except Exception:                            # noqa: BLE001 - fall back to the classic component
            pass
    import streamlit.components.v1 as components
    components.html(doc, height=int(height))


# --------------------------------------------------------------------------- cached heavy resources
@st.cache_resource(show_spinner=False)
def _bundle_cached():
    try:
        return brain.load_bundle(), None
    except brain.ModelLoadError as exc:
        return None, str(exc)
    except Exception as exc:                         # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def get_bundle():
    """-> (ModelBundle | None, error message | None)"""
    return _bundle_cached()


@st.cache_resource(show_spinner=False)
def get_replay():
    try:
        return brain.ReplaySource()
    except Exception:                                # noqa: BLE001
        return None


@st.cache_resource(show_spinner=False)
def _profile_cached(_bundle, _replay):
    return brain.confidence_profile(_bundle, _replay)


def get_profile():
    bundle, _ = get_bundle()
    replay = get_replay()
    if bundle is None or replay is None:
        return None
    return _profile_cached(bundle, replay)


def reload_model() -> None:
    st.cache_resource.clear()


# --------------------------------------------------------------------------- session state
def init_state() -> None:
    ss = st.session_state
    if ss.get("_boot"):
        return
    prefs = db.get_prefs()
    ss["_boot"] = True
    ss["world"] = worldctx.new_world(prefs)
    ss["decisions"] = []
    ss["last_window"] = None
    ss["last_command"] = {"text": "None", "conf": None, "ts": 0.0, "source": ""}
    ss["speaking"] = None
    ss["_tts"] = []
    ss["alert_id"] = None
    ss["phone"] = assistant.new_phone()
    ss["caregiver_ok"] = False
    ss["replay_idx"] = -1
    ss["replay_rng"] = np.random.default_rng(11)
    ss["auto_stream"] = False
    ss["spoken_due"] = set()
    ss["flash"] = None
    ss["last_beat"] = 0.0
    ss["last_flush"] = 0.0


def flash(kind: str, text: str) -> None:
    st.session_state["flash"] = (kind, text)


def show_flash() -> None:
    f = st.session_state.get("flash")
    if f:
        kind, text = f
        {"success": st.success, "warning": st.warning, "error": st.error}.get(kind, st.info)(text)
        st.session_state["flash"] = None


def set_last_command(text: str, conf: float | None = None, source: str = "buttons") -> None:
    st.session_state["last_command"] = {"text": text, "conf": conf, "ts": time.time(), "source": source}
    db.log_event("command", {"text": text, "confidence": conf, "source": source})


# --------------------------------------------------------------------------- chrome
def inject_css(prefs: dict) -> None:
    css = (Path(__file__).parent / "style.css").read_text(encoding="utf-8")
    if prefs.get("large_buttons"):
        css += "\n.stButton button { min-height: 76px; font-size: 1.3rem; }\n"
    if prefs.get("high_contrast"):
        css += ("\n.stApp { background:#ffffff !important; color:#000 !important; }\n"
                "div[class*='st-key-panel'] { background:#fff; border:3px solid #000; }\n"
                ".nl-muted, .nl-sub { color:#000 !important; }\n")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def system_status(prefs: dict) -> tuple[str, str]:
    bundle, _ = get_bundle()
    if bundle is None:
        return "bad", "Decoder unavailable"
    if not connectivity.effective_online(prefs):
        return "warn", "Offline mode"
    return "ok", "Connected"


def render_header(prefs: dict) -> None:
    kind, text = system_status(prefs)
    html(f"""
    <div class="nl-header">
      {render.svg_img(render.logo_svg(66), style="width:66px;height:66px;display:block")}
      <div class="nl-brand"><div class="nl-title">NeuroLink</div><div class="nl-tag">Think. Control. Live Independently.</div></div>
      <div class="nl-spacer"></div>
      <div class="nl-pill nl-pill-{kind}"><i></i>{render.esc(text)}</div>
      <div title="{render.esc(prefs.get('patient_name', 'Patient'))}">{render.svg_img(render.avatar_svg(56), style="width:56px;height:56px;display:block")}</div>
    </div>""")


def bootstrap() -> dict:
    """Runs on every rerun before the page: state, CSS, heartbeat, header. Returns the preferences."""
    init_state()
    prefs = db.get_prefs()
    inject_css(prefs)
    roadgeo.ensure_builtin()
    ss = st.session_state
    now = time.time()
    if now - ss["last_beat"] > 5:
        db.beat("patient_app", "ok", "session active")
        bundle, err = get_bundle()
        db.beat("decoder", "ok" if bundle else "error", "model loaded" if bundle else (err or "")[:120])
        ss["last_beat"] = now
    if now - ss["last_flush"] > 30:
        notify.flush_pending(prefs)
        ss["last_flush"] = now
    render_header(prefs)
    aid = ss.get("alert_id")
    if aid:
        alert = db.get_alert(aid)
        if alert and alert["status"] in ("open", "acknowledged"):
            who = "acknowledged by your caregiver" if alert["status"] == "acknowledged" else "waiting for your caregiver"
            html(f'<div class="nl-chip red">🚨 <b>Emergency alert active</b> - {who}. Open the Emergency page to cancel or call.</div>')
    return prefs


def page_bar(key: str) -> None:
    _, title, icon = PAGES[key]
    with st.container(key="pagebar"):
        c1, c2 = st.columns([8, 1], vertical_alignment="center")
        c1.markdown(f'<div class="nl-pagetitle"><span class="ic">{icon}</span>{render.esc(title)}</div>', unsafe_allow_html=True)
        with c2:
            if st.button("🏠", key="btn_home", help="Back to Home"):
                st.switch_page(PAGES["home"][0])
    show_flash()


def tile(key: str, icon: str, label: str, page: str) -> None:
    if button(f"{icon}\n{label}", key=f"tile_{key}"):
        st.switch_page(PAGES[page][0])


def status_bar(left: str, right: str | None = None, pulse: bool = True) -> None:
    wave = ('<svg class="nl-pulse" viewBox="0 0 34 22"><polyline points="0,11 7,11 10,2 15,20 19,6 22,11 34,11" fill="none" '
            'stroke="#2563eb" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>') if pulse else ""
    r = f'<span class="sep">|</span><span>{right}</span>' if right else ""
    html(f'<div class="nl-bar">{wave}<span>{left}</span>{r}</div>')


def level_badge(level: str) -> str:
    return f'<span class="nl-lvl {level}">{level.upper()}</span>'


def model_banner() -> None:
    bundle, err = get_bundle()
    if bundle is None:
        st.error(f"Helmet decoder unavailable - {err}")
    st.markdown(f'<div class="nl-banner-warn">⚠️ {render.esc(config.RELIABILITY_NOTE)}</div>', unsafe_allow_html=True)


# --------------------------------------------------------------------------- text-to-speech / alarm
_SPEAK_JS = """
function nlSpeak(text, lang, rate, pitch, vol, onend) {
  var w = window;
  try { if (window.parent && window.parent.speechSynthesis) { w = window.parent; } } catch (e) {}
  var synth = w.speechSynthesis;
  if (!synth) { if (onend) onend('unsupported'); return false; }
  try { synth.cancel(); } catch (e) {}
  var U = w.SpeechSynthesisUtterance || window.SpeechSynthesisUtterance;
  var u = new U(text); u.lang = lang; u.rate = rate; u.pitch = pitch; u.volume = vol;
  try {
    var voices = synth.getVoices() || [], lc = lang.toLowerCase();
    var v = voices.find(function (x) { return x.lang && x.lang.toLowerCase() === lc; }) ||
            voices.find(function (x) { return x.lang && x.lang.toLowerCase().indexOf(lc.slice(0, 2)) === 0; });
    if (v) { u.voice = v; }
  } catch (e) {}
  u.onend = function () { if (onend) onend('done'); };
  u.onerror = function (e) { if (onend) onend((e && e.error) ? e.error : 'error'); };
  synth.speak(u);
  return true;
}
function nlAlarm(seconds) {
  var w = window;
  try { if (window.parent && (window.parent.AudioContext || window.parent.webkitAudioContext)) { w = window.parent; } } catch (e) {}
  var C = w.AudioContext || w.webkitAudioContext;
  if (!C) { return false; }
  var ctx = new C(), osc = ctx.createOscillator(), g = ctx.createGain();
  osc.type = 'square'; g.gain.value = 0.12; osc.connect(g); g.connect(ctx.destination);
  var t = ctx.currentTime, n = Math.floor(seconds * 2);
  for (var i = 0; i < n; i++) { osc.frequency.setValueAtTime(i % 2 ? 960 : 640, t + i * 0.5); }
  osc.start(t); osc.stop(t + seconds);
  return true;
}
"""

_BAR_CSS = """
body{margin:0;font-family:'Segoe UI',system-ui,Arial,sans-serif;background:transparent}
.bar{display:flex;align-items:center;gap:16px;border-radius:16px;padding:0 18px;height:60px;box-sizing:border-box}
.bar button{border:0;border-radius:50%;width:40px;height:40px;font-size:20px;cursor:pointer;flex:none}
.txt{flex:1;min-width:0}.txt div{font-size:21px;font-weight:700;line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.txt small{font-size:13px;opacity:.85}
.bars{display:flex;align-items:flex-end;gap:4px;height:30px;flex:none}.bars span{width:7px;height:8px;background:#2563eb;border-radius:3px}
.bars.on span{animation:b 1s ease-in-out infinite}.bars span:nth-child(2){animation-delay:.15s}.bars span:nth-child(3){animation-delay:.3s}.bars span:nth-child(4){animation-delay:.45s}
@keyframes b{0%,100%{height:8px}50%{height:28px}}
"""


def _js_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False).replace("</", "<\\/")


def speech_bar_doc(text: str, lang: str, rate: float, pitch: float, volume: float, autoplay: bool) -> str:
    return """<!DOCTYPE html><html><head><meta charset="utf-8"><style>__CSS__
.bar{background:linear-gradient(180deg,#dfe7ff,#d3ddfb);border:1px solid #c5d1f6;color:#1f2a6b}.bar button{background:#2563eb;color:#fff}
</style></head><body>
<div class="bar"><button id="play" title="Speak again" aria-label="Speak again">&#128266;</button>
<div class="txt"><div id="t" dir="auto"></div><small id="s">Ready</small></div>
<div class="bars" id="bars"><span></span><span></span><span></span><span></span></div></div>
<script>__JS__
var TEXT=__TEXT__, LANG=__LANG__, RATE=__RATE__, PITCH=__PITCH__, VOL=__VOL__;
var s=document.getElementById('s'), bars=document.getElementById('bars');
document.getElementById('t').textContent=TEXT;
function run(){
  s.textContent='(Speaking...)'; bars.className='bars on';
  nlSpeak(TEXT,LANG,RATE,PITCH,VOL,function(r){
    bars.className='bars';
    if(r==='done'){s.textContent='(Done) - tap the speaker to repeat';}
    else if(r==='unsupported'){s.textContent='Speech is not supported in this browser';}
    else if(r==='not-allowed'){s.textContent='Tap the speaker to hear it';}
    else if(r==='canceled'||r==='interrupted'){s.textContent='';}
    else{s.textContent='Could not speak ('+r+') - tap the speaker to retry';}
  });
}
document.getElementById('play').onclick=run;
__START__
</script></body></html>""".replace("__CSS__", _BAR_CSS).replace("__JS__", _SPEAK_JS).replace("__TEXT__", _js_str(text)) \
        .replace("__LANG__", _js_str(lang)).replace("__RATE__", f"{rate:.2f}").replace("__PITCH__", f"{pitch:.2f}") \
        .replace("__VOL__", f"{volume:.2f}") \
        .replace("__START__", "run();" if autoplay else "s.textContent='Tap the speaker to hear it';")


def hidden_speech_doc(text: str, lang: str, rate: float, pitch: float, volume: float, alarm: bool = False) -> str:
    return ("<!DOCTYPE html><html><body><script>" + _SPEAK_JS +
            ("nlAlarm(3);" if alarm else "") +
            f"setTimeout(function(){{nlSpeak({_js_str(text)},{_js_str(lang)},{rate:.2f},{pitch:.2f},{volume:.2f},null);}},{3200 if alarm else 50});"
            "</script></body></html>")


def alarm_bar_doc(message: str, lang: str, rate: float, pitch: float, volume: float, autoplay: bool, sound: bool) -> str:
    return """<!DOCTYPE html><html><head><meta charset="utf-8"><style>__CSS__
.bar{background:#fee2e2;border:2px solid #ef4444;color:#7f1d1d}.bar button{background:#dc2626;color:#fff}
</style></head><body>
<div class="bar"><button id="play" aria-label="Play alarm">&#128266;</button>
<div class="txt"><div id="t" dir="auto"></div><small id="s">Tap the speaker to sound the alarm and speak the message</small></div></div>
<script>__JS__
var TEXT=__TEXT__, LANG=__LANG__, SOUND=__SOUND__;
document.getElementById('t').textContent=TEXT;
function run(){
  if(SOUND){nlAlarm(3);}
  setTimeout(function(){nlSpeak(TEXT,LANG,__RATE__,__PITCH__,__VOL__,null);},SOUND?3200:50);
  document.getElementById('s').textContent='Alarm / voice message played';
}
document.getElementById('play').onclick=run;
__START__
</script></body></html>""".replace("__CSS__", _BAR_CSS).replace("__JS__", _SPEAK_JS).replace("__TEXT__", _js_str(message)) \
        .replace("__LANG__", _js_str(lang)).replace("__RATE__", f"{rate:.2f}").replace("__PITCH__", f"{pitch:.2f}") \
        .replace("__VOL__", f"{volume:.2f}").replace("__SOUND__", "true" if sound else "false") \
        .replace("__START__", "run();" if autoplay else "")


def tts_lang(prefs: dict) -> str:
    return "ar-EG" if prefs.get("language") == "ar" else "en-US"


def speak(text: str, *, source: str = "communication") -> None:
    """Show the 'Speaking...' bar and speak `text` in the browser (Web Speech API)."""
    prefs = db.get_prefs()
    st.session_state["speaking"] = {"text": text, "lang": tts_lang(prefs), "ts": time.time(), "pending": True,
                                    "source": source}
    db.log_event("speak", text)


def queue_speech(text: str, *, alarm: bool = False) -> None:
    """Speak without any visible UI (reminders, safety announcements). Flushed at the end of the run."""
    st.session_state["_tts"].append({"text": text, "alarm": alarm})


def flush_tts() -> None:
    ss = st.session_state
    queue = ss.get("_tts") or []
    if not queue:
        return
    ss["_tts"] = []
    prefs = db.get_prefs()
    if not prefs.get("tts_enabled", True):
        return
    for item in queue[-3:]:
        embed_html(hidden_speech_doc(item["text"], tts_lang(prefs), prefs["tts_rate"], prefs["tts_pitch"],
                                     prefs["tts_volume"], alarm=item["alarm"] and prefs.get("alarm_sound", True)), height=1)


def speech_bar() -> None:
    """The 'I'm thirsty (Speaking...)' bar from the mock-up, with a speaker button as a fallback for
    browsers that block automatic audio."""
    prefs = db.get_prefs()
    sp = st.session_state.get("speaking")
    if not sp:
        status_bar("Select a phrase above to speak it", pulse=False)
        return
    auto = bool(sp.pop("pending", False)) and prefs.get("tts_enabled", True)
    embed_html(speech_bar_doc(sp["text"], sp["lang"], prefs["tts_rate"], prefs["tts_pitch"], prefs["tts_volume"], auto), height=64)


# --------------------------------------------------------------------------- helmet decoding
def decode_next(mode: str = "random"):
    """Replay the next recorded trial through the model. Returns a Decision (or raises RuntimeError)."""
    bundle, err = get_bundle()
    replay = get_replay()
    if bundle is None:
        raise RuntimeError(err or "Model not loaded")
    if replay is None:
        raise RuntimeError("Replay data not found in replay_data/")
    ss = st.session_state
    prefs = db.get_prefs()
    idx = replay.pick(mode, ss["replay_idx"], ss["replay_rng"])
    ss["replay_idx"] = idx
    window, truth, fid = replay.get(idx)
    d = brain.decode_window(bundle, window, prefs["confidence_gate"], source="replay", trial_id=fid, truth=truth)
    ss["last_window"] = window
    record_decision(d)
    return d


def record_decision(d: brain.Decision) -> None:
    ss = st.session_state
    ss["decisions"] = (ss["decisions"] + [d])[-40:]
    db.beat("helmet", "streaming", f"{d.source} trial {d.trial_id}")
    db.log_event("decode", {"label": d.label, "confidence": round(d.confidence, 4), "accepted": d.accepted,
                            "trial": d.trial_id, "source": d.source})


def run_decision_on_chair(d: brain.Decision) -> str:
    """Apply a decision to the simulated wheelchair and update 'Last Command'."""
    ss = st.session_state
    prefs = db.get_prefs()
    w = ss["world"]
    msg = mobility.apply_decision(w["chair"], d, prefs, w["obstacles"], w["vehicles"])
    set_last_command(f"Turn {d.label}" if d.accepted else f"Ignored ({d.label}, below gate)", d.confidence, "helmet")
    return msg


# --------------------------------------------------------------------------- reminders banner (live)
def _ack(rid: int, now_date: str) -> None:
    db.update_reminder(rid, last_ack_date=now_date, snooze_until=None)
    db.log_event("reminder_done", rid)


def _snooze(rid: int, minutes: int = 10) -> None:
    db.update_reminder(rid, snooze_until=time.time() + minutes * 60)
    db.log_event("reminder_snooze", rid)


@st.fragment(run_every=15)
def reminder_banner() -> None:
    prefs = db.get_prefs()
    now = assistant.local_now(prefs)
    due = assistant.due_reminders(db.list_reminders(), now)
    for r in due:
        k = f"{r['id']}-{now:%Y-%m-%d}-{r.get('snooze_until')}"
        if k not in st.session_state["spoken_due"]:
            st.session_state["spoken_due"].add(k)
            queue_speech(f"Reminder: {r['title']}")
            db.log_event("reminder_due", r["title"])
        icon = config.REMINDER_ICONS.get(r["kind"], "⏰")
        html(f'<div class="nl-rem due"><span class="ic">{icon}</span><span class="tt">Reminder: {render.esc(r["title"])}</span><span class="tm">{r["hhmm"]}</span></div>')
        c1, c2 = st.columns(2)
        with c1:
            button("✔ Done", key=f"rem_done_{r['id']}", on_click=_ack, args=(r["id"], f"{now:%Y-%m-%d}"))
        with c2:
            button("⏰ Snooze 10 min", key=f"rem_snooze_{r['id']}", on_click=_snooze, args=(r["id"], 10))
    flush_tts()


# --------------------------------------------------------------------------- world drawing helper
def world_html(world: dict, ctx: dict, assessment: dict, *, view_m: float = 34.0, width: int = 820, height: int = 500,
               pin: bool = False, sensors: bool = True, focus: str | None = None, route: list | None = None) -> str:
    svg = render.world_svg(ctx["pack"], world["chair"], world["obstacles"], world["vehicles"], lights=ctx["lights"],
                           walk_states=ctx["walk_states"], assessment=assessment, view_m=view_m, width=width, height=height,
                           pin=pin, show_sensors=sensors, focus_crosswalk=focus, route=route)
    return render.svg_img(svg, alt="Top-down map around the wheelchair",
                          style="width:100%;height:auto;display:block;border-radius:18px;box-shadow:0 6px 18px rgba(30,30,110,.2)")


def warnings_html(assessment: dict) -> str:
    items = assessment["warnings"]
    if not items:
        return '<div class="nl-chip green">✅ No obstacles, vehicles or hazards detected</div>'
    icon = {"danger": "⛔", "caution": "⚠️", "info": "ℹ️"}
    return "".join(f'<div class="nl-warn {w["level"]}"><span>{icon.get(w["level"], "•")}</span><span>{render.esc(w["text"])}</span></div>'
                   for w in items)


# --------------------------------------------------------------------------- preferences form (shared)
def _valid_url(u: str) -> bool:
    from urllib.parse import urlparse
    p = urlparse(u.strip())
    return p.scheme in ("http", "https") and bool(p.netloc)


def prefs_form(sections: list[str], form_key: str) -> None:
    """One form for any subset of preference sections. Saved to the shared database."""
    prefs = db.get_prefs()
    new: dict = {}
    errors: list[str] = []
    with st.form(form_key):
        if "voice" in sections:
            st.markdown("**Voice & language**")
            c = st.columns(2)
            new["language"] = "ar" if c[0].radio("Language", ["English", "العربية"], index=1 if prefs["language"] == "ar" else 0,
                                                 horizontal=True, key=f"{form_key}_lang") == "العربية" else "en"
            new["tts_enabled"] = c[1].toggle("Speak aloud (text-to-speech)", value=prefs["tts_enabled"], key=f"{form_key}_tts")
            c = st.columns(3)
            new["tts_rate"] = c[0].slider("Speech speed", 0.5, 1.6, float(prefs["tts_rate"]), 0.1, key=f"{form_key}_rate")
            new["tts_pitch"] = c[1].slider("Pitch", 0.5, 1.6, float(prefs["tts_pitch"]), 0.1, key=f"{form_key}_pitch")
            new["tts_volume"] = c[2].slider("Volume", 0.1, 1.0, float(prefs["tts_volume"]), 0.1, key=f"{form_key}_vol")
            new["alarm_sound"] = st.toggle("Play an alarm sound for emergencies", value=prefs["alarm_sound"], key=f"{form_key}_alarm")
        if "display" in sections:
            st.markdown("**Display**")
            c = st.columns(2)
            new["large_buttons"] = c[0].toggle("Extra-large buttons", value=prefs["large_buttons"], key=f"{form_key}_large")
            new["high_contrast"] = c[1].toggle("High contrast", value=prefs["high_contrast"], key=f"{form_key}_contrast")
        if "helmet" in sections:
            st.markdown("**Helmet & wheelchair**")
            c = st.columns(3)
            new["confidence_gate"] = c[0].slider("Confidence gate", 0.50, 0.95, float(prefs["confidence_gate"]), 0.01, key=f"{form_key}_gate",
                                                 help="Helmet decisions below this probability are ignored.")
            new["speed_mps"] = c[1].slider("Wheelchair speed (m/s)", 0.3, 2.0, float(prefs["speed_mps"]), 0.1, key=f"{form_key}_speed")
            new["turn_step_deg"] = c[2].slider("Turn step (degrees)", 5, 45, int(prefs["turn_step_deg"]), 5, key=f"{form_key}_turn")
            prof = get_profile()
            if prof:
                st.caption(f"On the {prof.n} recorded trials this model's top probability ranges {prof.min_conf:.3f}-{prof.max_conf:.3f}; "
                           f"a gate above {prof.max_conf:.2f} would ignore every decision.")
        if "contacts" in sections:
            st.markdown("**People & alerts**")
            c = st.columns(2)
            new["patient_name"] = c[0].text_input("Patient name", prefs["patient_name"], key=f"{form_key}_pname")
            new["caregiver_name"] = c[1].text_input("Caregiver name", prefs["caregiver_name"], key=f"{form_key}_cname")
            c = st.columns(3)
            new["caregiver_phone"] = c[0].text_input("Caregiver phone", prefs["caregiver_phone"], key=f"{form_key}_cphone", placeholder="+20 100 000 0000")
            new["caregiver_email"] = c[1].text_input("Caregiver email", prefs["caregiver_email"], key=f"{form_key}_cmail")
            new["emergency_number"] = c[2].text_input("Emergency services number", prefs["emergency_number"], key=f"{form_key}_enum")
            new["webhook_url"] = st.text_input("Alert webhook URL (optional)", prefs["webhook_url"], key=f"{form_key}_hook",
                                               placeholder="https://...  (emergency alerts are POSTed here as JSON)")
            new["notify_on_need"] = st.toggle("Needs spoken in Communication (thirsty, hungry, pain...) also notify the caregiver",
                                              value=prefs["notify_on_need"], key=f"{form_key}_need")
        if "safety" in sections:
            st.markdown("**Safety thresholds**")
            c = st.columns(2)
            new["stop_distance_m"] = c[0].slider("Stop distance to obstacles (m)", 0.5, 3.0, float(prefs["stop_distance_m"]), 0.1, key=f"{form_key}_stopd")
            new["slow_distance_m"] = c[1].slider("Warning distance to obstacles (m)", 1.0, 6.0, float(prefs["slow_distance_m"]), 0.5, key=f"{form_key}_slowd")
            c = st.columns(2)
            new["vehicle_caution_s"] = c[0].slider("Vehicle caution horizon (s)", 3.0, 15.0, float(prefs["vehicle_caution_s"]), 1.0, key=f"{form_key}_vcau")
            new["vehicle_danger_s"] = c[1].slider("Vehicle danger horizon (s)", 1.0, 10.0, float(prefs["vehicle_danger_s"]), 1.0, key=f"{form_key}_vdan")
            new["auto_stop"] = st.toggle("Automatically stop the wheelchair when unsafe", value=prefs["auto_stop"], key=f"{form_key}_auto")
        if "location" in sections:
            st.markdown("**Location**")
            c = st.columns(4)
            new["location_name"] = c[0].text_input("Place name", prefs["location_name"], key=f"{form_key}_lname")
            new["lat"] = c[1].number_input("Latitude", -90.0, 90.0, float(prefs["lat"]), 0.0001, format="%.5f", key=f"{form_key}_lat")
            new["lon"] = c[2].number_input("Longitude", -180.0, 180.0, float(prefs["lon"]), 0.0001, format="%.5f", key=f"{form_key}_lon")
            new["timezone"] = c[3].text_input("Time zone", prefs["timezone"], key=f"{form_key}_tz")
        if "security" in sections:
            st.markdown("**Caregiver PIN**")
            new["caregiver_pin"] = st.text_input("PIN to open the Caregiver Dashboard", prefs["caregiver_pin"], type="password", key=f"{form_key}_pin")
        submitted = form_submit("💾 Save", key=f"{form_key}_save")

    if submitted:
        if "webhook_url" in new and new["webhook_url"].strip() and not _valid_url(new["webhook_url"]):
            errors.append("The webhook URL must start with http:// or https://")
        if "caregiver_pin" in new and (len(new["caregiver_pin"]) < 4 or not new["caregiver_pin"].isdigit()):
            errors.append("The PIN must be at least 4 digits")
        if "caregiver_phone" in new and any(ch not in "+0123456789 -()" for ch in new["caregiver_phone"]):
            errors.append("The phone number may only contain digits, spaces and + - ( )")
        if "vehicle_danger_s" in new and new["vehicle_danger_s"] > new["vehicle_caution_s"]:
            errors.append("The vehicle danger horizon cannot be longer than the caution horizon")
        if "timezone" in new:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(new["timezone"])
            except Exception:                                  # noqa: BLE001
                errors.append(f"Unknown time zone '{new['timezone']}' (example: Africa/Cairo)")
        if errors:
            for e in errors:
                st.error(e)
        else:
            if "caregiver_phone" in new:
                new["caregiver_phone"] = new["caregiver_phone"].strip().replace(" ", "")
            db.set_prefs(**new)
            flash("success", "Saved.")
            st.rerun()
