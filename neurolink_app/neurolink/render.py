"""Pure-Python SVG / HTML renderers (no Streamlit imports, no third-party plotting libraries).

All pictures are returned as SVG strings; `svg_img()` wraps one in a base64 <img> tag, which renders
reliably inside st.markdown(unsafe_allow_html=True).
"""
from __future__ import annotations

import base64
import html as _html
import math

import numpy as np

from . import guidance, safety

FONT = "'Segoe UI', system-ui, -apple-system, Roboto, Arial, sans-serif"
CH_COLORS = ["#86efac", "#60a5fa", "#fb923c", "#c084fc", "#f472b6", "#facc15", "#22d3ee", "#a3e635"]


def esc(s) -> str:
    return _html.escape(str(s), quote=True)


def svg_img(svg: str, *, alt: str = "", style: str = "width:100%;height:auto;display:block") -> str:
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f'<img alt="{esc(alt)}" style="{style}" src="data:image/svg+xml;base64,{b64}">'


def collapse_html(s: str) -> str:
    """Markdown treats indented / blank-line-separated HTML as code - flatten it."""
    return "\n".join(line.strip() for line in s.strip().splitlines() if line.strip())


# --------------------------------------------------------------------------- brand art
def logo_svg(size: int = 64) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{size}" height="{size}">
<defs><filter id="g" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="1.6" result="b"/>
<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
<g fill="none" stroke="#22d3ee" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" filter="url(#g)">
<path d="M32 9 C23 5 12 10 13 21 C6 24 7 36 14 38 C12 47 20 55 28 50 C30 52 32 53 32 53"/>
<path d="M32 9 C41 5 52 10 51 21 C58 24 57 36 50 38 C52 47 44 55 36 50 C34 52 32 53 32 53"/>
<path d="M32 9 V53"/><path d="M13 21 C20 21 22 27 28 27"/><path d="M14 38 C20 37 22 33 28 34"/>
<path d="M51 21 C44 21 42 27 36 27"/><path d="M50 38 C44 37 42 33 36 34"/>
</g><g fill="#a5f3fc"><circle cx="21" cy="17" r="2"/><circle cx="43" cy="17" r="2"/><circle cx="20" cy="44" r="2"/><circle cx="44" cy="44" r="2"/></g></svg>"""


def avatar_svg(size: int = 56) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 56 56" width="{size}" height="{size}">
<defs><linearGradient id="a" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#8b5cf6"/><stop offset="1" stop-color="#4338ca"/></linearGradient></defs>
<circle cx="28" cy="28" r="27" fill="url(#a)" stroke="#c7d2fe" stroke-width="2"/>
<circle cx="28" cy="21" r="8.5" fill="#fff"/><path d="M11 47c2-10 9-15 17-15s15 5 17 15c-5 5-11 7-17 7s-12-2-17-7z" fill="#fff"/></svg>"""


def wheelchair_svg() -> str:
    spokes = "".join(
        f'<line x1="{96 + 38 * math.cos(math.radians(a)):.1f}" y1="{118 + 38 * math.sin(math.radians(a)):.1f}" '
        f'x2="{96 + 6 * math.cos(math.radians(a)):.1f}" y2="{118 + 6 * math.sin(math.radians(a)):.1f}" stroke="#6366f1" stroke-width="1.6"/>'
        for a in range(0, 360, 30))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 210">
<defs><linearGradient id="pl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e0e7ff"/><stop offset="1" stop-color="#a5b4fc"/></linearGradient></defs>
<ellipse cx="130" cy="186" rx="112" ry="17" fill="#818cf8" opacity=".35"/><ellipse cx="130" cy="178" rx="108" ry="15" fill="url(#pl)"/>
<circle cx="96" cy="118" r="50" fill="none" stroke="#1e1b4b" stroke-width="8"/><circle cx="96" cy="118" r="40" fill="none" stroke="#4f46e5" stroke-width="3"/>
{spokes}<circle cx="96" cy="118" r="7" fill="#1e1b4b"/>
<circle cx="196" cy="156" r="16" fill="#1e1b4b"/><circle cx="196" cy="156" r="7" fill="#6366f1"/>
<path d="M98 118 L150 118" stroke="#312e81" stroke-width="6" stroke-linecap="round"/>
<path d="M150 118 L190 150" stroke="#312e81" stroke-width="6" stroke-linecap="round"/><path d="M186 152 L210 152" stroke="#1e1b4b" stroke-width="8" stroke-linecap="round"/>
<path d="M82 94 L156 94 L156 104 L82 104 Z" fill="#1e3a8a"/><path d="M84 94 L68 36" stroke="#1e1b4b" stroke-width="12" stroke-linecap="round"/>
<path d="M66 30 L46 28" stroke="#1e1b4b" stroke-width="7" stroke-linecap="round"/><path d="M78 74 L128 74" stroke="#312e81" stroke-width="7" stroke-linecap="round"/>
<path d="M84 94 L98 118" stroke="#312e81" stroke-width="6"/></svg>"""


# --------------------------------------------------------------------------- world / map view
def _fmt(v: float) -> str:
    return f"{v:.1f}"


def world_svg(pack: dict | None, chair: dict, obstacles: list[dict], vehicles: list[dict], *,
              lights: dict | None = None, walk_states: dict | None = None, assessment: dict | None = None,
              view_m: float = 38.0, width: int = 820, height: int = 500, show_sensors: bool = True,
              show_trail: bool = True, pin: bool = False, focus_crosswalk: str | None = None,
              route: list | None = None) -> str:
    """Top-down view centred on the wheelchair. x east / y north; heading clockwise from north."""
    s = height / (2.0 * view_m)                    # pixels per metre
    cx, cy = chair["x"], chair["y"]

    def X(x): return width / 2 + (x - cx) * s
    def Y(y): return height / 2 - (y - cy) * s

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" font-family="{FONT}">',
         f'<rect width="{width}" height="{height}" fill="#e3ece1"/>']
    if pack:
        for b in pack.get("blocks", []):
            x0, y0, x1, y1 = b[:4]
            o.append(f'<rect x="{_fmt(X(x0))}" y="{_fmt(Y(y1))}" width="{_fmt((x1 - x0) * s)}" height="{_fmt((y1 - y0) * s)}" '
                     f'rx="{_fmt(1.2 * s)}" fill="#cbd5e1" stroke="#94a3b8" stroke-width="1.5"/>')
        for r in pack.get("roads", []):
            pts = " ".join(f"{_fmt(X(px))},{_fmt(Y(py))}" for px, py in r["points"])
            o.append(f'<polyline points="{pts}" fill="none" stroke="#d3d9e2" stroke-width="{_fmt((r["width"] + 5) * s)}" stroke-linejoin="round"/>')
        for r in pack.get("roads", []):
            pts = " ".join(f"{_fmt(X(px))},{_fmt(Y(py))}" for px, py in r["points"])
            o.append(f'<polyline points="{pts}" fill="none" stroke="#4b5563" stroke-width="{_fmt(r["width"] * s)}" stroke-linejoin="round"/>')
        for r in pack.get("roads", []):
            pts = " ".join(f"{_fmt(X(px))},{_fmt(Y(py))}" for px, py in r["points"])
            col = "#facc15" if not r.get("oneway") else "#f8fafc"
            o.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="{_fmt(max(1.0, 0.25 * s))}" stroke-dasharray="{_fmt(3 * s)} {_fmt(3 * s)}"/>')
        # junction box to hide dashes inside the intersection (demo pack: two crossing roads)
        for it in pack.get("intersections", []):
            ws = [r["width"] for r in pack["roads"]]
            if len(ws) >= 2 and it.get("signalized"):
                w1, w2 = sorted(ws, reverse=True)[:2]
                o.append(f'<rect x="{_fmt(X(it["x"] - w2 / 2))}" y="{_fmt(Y(it["y"] + w1 / 2))}" width="{_fmt(w2 * s)}" height="{_fmt(w1 * s)}" fill="#4b5563"/>')
        # crosswalks
        for cw in pack.get("crosswalks", []):
            focus = cw["id"] == focus_crosswalk
            walk = (walk_states or {}).get(cw["id"])
            L, T = cw["len"], 3.0
            n = int(L / 1.2)
            for k in range(n):
                off = -L / 2 + 0.6 + k * 1.2
                if cw["orient"] == "ew":
                    x0, y0, w, h = cw["x"] + off - 0.3, cw["y"] - T / 2, 0.6, T
                else:
                    x0, y0, w, h = cw["x"] - T / 2, cw["y"] + off - 0.3, T, 0.6
                o.append(f'<rect x="{_fmt(X(x0))}" y="{_fmt(Y(y0 + h))}" width="{_fmt(w * s)}" height="{_fmt(h * s)}" fill="#f8fafc" opacity=".95"/>')
            if walk is not None:
                col = "#22c55e" if walk else "#ef4444"
                ox, oy = (cw["x"] - L / 2 - 2.6, cw["y"]) if cw["orient"] == "ew" else (cw["x"], cw["y"] - L / 2 - 2.6)
                o.append(f'<rect x="{_fmt(X(ox) - 4)}" y="{_fmt(Y(oy) - 7)}" width="8" height="14" rx="4" fill="#0f172a" opacity=".9"/>'
                         f'<circle cx="{_fmt(X(ox))}" cy="{_fmt(Y(oy))}" r="2.8" fill="{col}"/>')
            if focus:
                bx, by = (cw["x"] - L / 2, cw["y"] + T / 2) if cw["orient"] == "ew" else (cw["x"] - T / 2, cw["y"] + L / 2)
                bw, bh = (L, T) if cw["orient"] == "ew" else (T, L)
                o.append(f'<rect x="{_fmt(X(bx))}" y="{_fmt(Y(by))}" width="{_fmt(bw * s)}" height="{_fmt(bh * s)}" fill="none" stroke="#2563eb" stroke-width="3" stroke-dasharray="6 4" rx="4"/>')
        # stop lines for vehicles (road markings) and kerb ramps at the ends of each crossing
        for sl in guidance.stop_lines(pack):
            o.append(f'<line x1="{_fmt(X(sl["x1"]))}" y1="{_fmt(Y(sl["y1"]))}" x2="{_fmt(X(sl["x2"]))}" y2="{_fmt(Y(sl["y2"]))}" '
                     f'stroke="#f8fafc" stroke-width="{_fmt(max(2.5, 0.45 * s))}" opacity=".95"/>')
        for cw in pack.get("crosswalks", []):
            if cw.get("ramp"):
                for end in guidance.crosswalk_ends(cw):
                    o.append(f'<rect x="{_fmt(X(end[0]) - 4)}" y="{_fmt(Y(end[1]) - 4)}" width="8" height="8" rx="2" fill="#38bdf8" stroke="#fff" stroke-width="1"/>')
        # traffic lights (demo pack geometry: roads 'main' and 'cross')
        ids = {r["id"]: r for r in pack.get("roads", [])}
        if lights and "main" in ids and "cross" in ids and pack.get("intersections"):
            it = pack["intersections"][0]
            mw, cw_ = ids["main"]["width"], ids["cross"]["width"]
            spots = [(it["x"] - cw_ / 2 - 1.2, it["y"] - mw / 2 - 1.2, "main"), (it["x"] + cw_ / 2 + 1.2, it["y"] + mw / 2 + 1.2, "main"),
                     (it["x"] + cw_ / 2 + 1.2, it["y"] - mw / 2 - 1.2, "cross"), (it["x"] - cw_ / 2 - 1.2, it["y"] + mw / 2 + 1.2, "cross")]
            colr = {"green": "#22c55e", "yellow": "#facc15", "red": "#ef4444"}
            for x, y, road in spots:
                o.append(f'<rect x="{_fmt(X(x) - 8)}" y="{_fmt(Y(y) - 8)}" width="16" height="16" rx="4" fill="#0f172a" stroke="#fff" stroke-width="1.5"/>'
                         f'<circle cx="{_fmt(X(x))}" cy="{_fmt(Y(y))}" r="5.2" fill="{colr[lights.get(road, "red")]}"/>')

    if show_trail and len(chair.get("trail", [])) > 1:
        pts = " ".join(f"{_fmt(X(px))},{_fmt(Y(py))}" for px, py in chair["trail"][-250:])
        o.append(f'<polyline points="{pts}" fill="none" stroke="#6366f1" stroke-width="3" stroke-dasharray="2 6" stroke-linecap="round" opacity=".8"/>')

    if route and len(route) >= 2:
        pts = " ".join(f"{_fmt(X(px))},{_fmt(Y(py))}" for px, py in route)
        o.append(f'<polyline points="{pts}" fill="none" stroke="#ffffff" stroke-width="9" stroke-linecap="round" stroke-linejoin="round" opacity=".75"/>'
                 f'<polyline points="{pts}" fill="none" stroke="#2563eb" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="1 9"/>')
        for i, (px, py) in enumerate(route[1:], start=1):
            o.append(f'<circle cx="{_fmt(X(px))}" cy="{_fmt(Y(py))}" r="{7 if i == 1 else 5}" fill="{"#2563eb" if i == 1 else "#fff"}" stroke="#2563eb" stroke-width="3"/>')

    for ob in obstacles:
        r = max(5.0, ob["r"] * s)
        col = {"pothole": "#1f2937", "pole": "#64748b", "bicycle": "#f59e0b"}.get(ob.get("kind"), "#f97316")
        o.append(f'<circle cx="{_fmt(X(ob["x"]))}" cy="{_fmt(Y(ob["y"]))}" r="{_fmt(r)}" fill="{col}" stroke="#fff" stroke-width="2"/>'
                 f'<text x="{_fmt(X(ob["x"]))}" y="{_fmt(Y(ob["y"]) - r - 4)}" text-anchor="middle" font-size="12" fill="#1f2937" font-weight="600">{esc(ob["label"])}</text>')

    threat_ids = {t["vehicle"]: t for t in (assessment or {}).get("threats", [])}
    for v in vehicles:
        ang = math.degrees(math.atan2(v["vx"], v["vy"]))
        l, w = (11.0 if v["kind"] == "bus" else 4.6 if v["kind"] == "car" else 5.4), 2.0
        col = {"car": "#0ea5e9", "van": "#8b5cf6", "bus": "#f59e0b"}.get(v["kind"], "#0ea5e9")
        th = threat_ids.get(v["id"])
        if th:
            o.append(f'<circle cx="{_fmt(X(v["x"]))}" cy="{_fmt(Y(v["y"]))}" r="{_fmt(max(14, l * s * 0.8))}" fill="none" '
                     f'stroke="{"#ef4444" if th["level"] == "danger" else "#f59e0b"}" stroke-width="3" opacity=".9"/>')
        o.append(f'<g transform="translate({_fmt(X(v["x"]))} {_fmt(Y(v["y"]))}) rotate({ang:.1f})">'
                 f'<rect x="{_fmt(-w * s / 2)}" y="{_fmt(-l * s / 2)}" width="{_fmt(w * s)}" height="{_fmt(l * s)}" rx="{_fmt(0.4 * s)}" fill="{col}" stroke="#0f172a" stroke-width="1.5"/>'
                 f'<rect x="{_fmt(-w * s * 0.38)}" y="{_fmt(-l * s * 0.42)}" width="{_fmt(w * s * 0.76)}" height="{_fmt(l * s * 0.18)}" fill="#e0f2fe"/></g>')

    if show_sensors and assessment:
        for name, ang in safety.SENSOR_ANGLES.items():
            d = assessment["sensors"][name]["dist"]
            reach = safety.SENSOR_RANGE if d is None else d
            h = math.radians(chair["heading"] + ang)
            x2, y2 = chair["x"] + math.sin(h) * reach, chair["y"] + math.cos(h) * reach
            col = "#22c55e" if d is None else ("#ef4444" if d < 1.5 else "#f59e0b")
            o.append(f'<line x1="{_fmt(X(chair["x"]))}" y1="{_fmt(Y(chair["y"]))}" x2="{_fmt(X(x2))}" y2="{_fmt(Y(y2))}" stroke="{col}" stroke-width="2.5" stroke-dasharray="{"" if d is not None else "5 4"}" opacity=".9"/>')
            if d is not None:
                o.append(f'<circle cx="{_fmt(X(x2))}" cy="{_fmt(Y(y2))}" r="4" fill="{col}"/>')

    # wheelchair marker
    lvl = (assessment or {}).get("level", "clear")
    if lvl in ("caution", "danger"):
        c = "#ef4444" if lvl == "danger" else "#f59e0b"
        o.append(f'<circle cx="{_fmt(X(cx))}" cy="{_fmt(Y(cy))}" r="24" fill="{c}" opacity=".18" stroke="{c}" stroke-width="2.5"/>')
    o.append(f'<g transform="translate({_fmt(X(cx))} {_fmt(Y(cy))}) rotate({chair["heading"]:.1f})">'
             '<polygon points="0,-20 8,-9 -8,-9" fill="#1e1b4b"/><circle r="10" fill="#4f46e5" stroke="#fff" stroke-width="3"/>'
             '<rect x="-4" y="-3" width="8" height="8" rx="2" fill="#fff"/></g>')
    if pin:
        px_, py_ = X(cx), Y(cy) - 28
        o.append(f'<g transform="translate({_fmt(px_)} {_fmt(py_)})"><path d="M0 22 C-14 4 -14 -14 0 -14 C14 -14 14 4 0 22Z" fill="#2563eb" stroke="#fff" stroke-width="2.5"/>'
                 '<circle cy="-3" r="5" fill="#fff"/></g>')
    # compass + scale bar
    o.append(f'<g transform="translate({width - 34} 34)"><circle r="20" fill="#fff" opacity=".85"/><polygon points="0,-15 6,3 0,0 -6,3" fill="#ef4444"/>'
             '<text y="16" text-anchor="middle" font-size="11" font-weight="700" fill="#334155">N</text></g>')
    bar = 10.0 * s
    o.append(f'<g transform="translate(18 {height - 22})"><rect x="-6" y="-14" width="{_fmt(bar + 52)}" height="26" rx="8" fill="#fff" opacity=".85"/>'
             f'<line x1="0" y1="0" x2="{_fmt(bar)}" y2="0" stroke="#334155" stroke-width="3"/><text x="{_fmt(bar + 6)}" y="4" font-size="12" fill="#334155" font-weight="600">10 m</text></g>')
    o.append("</svg>")
    return "".join(o)


# --------------------------------------------------------------------------- EEG traces + spectrum
def eeg_svg(window: np.ndarray, ch_names: list[str], fs: float, *, width: int = 900, height: int = 300,
            title: str | None = None) -> str:
    n_ch, n = window.shape
    left, top, bottom = 54, 26 if title else 10, 26
    plot_h = height - top - bottom
    row_h = plot_h / n_ch
    pts_n = min(n, 500)
    idx = np.linspace(0, n - 1, pts_n).astype(int)
    dur = n / fs
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" font-family="{FONT}">',
         f'<rect width="{width}" height="{height}" rx="14" fill="#0f172a"/>']
    if title:
        o.append(f'<text x="{left}" y="18" font-size="13" fill="#94a3b8" font-weight="600">{esc(title)}</text>')
    pw = width - left - 12
    for sec in range(int(dur) + 1):
        x = left + pw * sec / dur
        o.append(f'<line x1="{_fmt(x)}" y1="{top}" x2="{_fmt(x)}" y2="{height - bottom}" stroke="#1e293b" stroke-width="1"/>'
                 f'<text x="{_fmt(x)}" y="{height - 8}" font-size="11" fill="#64748b" text-anchor="middle">{sec}s</text>')
    for i in range(n_ch):
        ch = window[i].astype(float)
        ch = ch - ch.mean()
        amp = max(float(np.percentile(np.abs(ch), 99)), 1e-9)
        yc = top + row_h * (i + 0.5)
        o.append(f'<line x1="{left}" y1="{_fmt(yc)}" x2="{width - 12}" y2="{_fmt(yc)}" stroke="#1e293b" stroke-width="1" stroke-dasharray="3 5"/>')
        pts = " ".join(f"{_fmt(left + pw * k / (pts_n - 1))},{_fmt(yc - np.clip(ch[j] / amp, -1.3, 1.3) * row_h * 0.42)}"
                       for k, j in enumerate(idx))
        col = CH_COLORS[i % len(CH_COLORS)]
        o.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.4" stroke-linejoin="round"/>'
                 f'<text x="10" y="{_fmt(yc + 4)}" font-size="13" font-weight="700" fill="{col}">{esc(ch_names[i])}</text>'
                 f'<text x="{width - 14}" y="{_fmt(yc - row_h * 0.36)}" font-size="10" fill="#64748b" text-anchor="end">±{amp:.0f}</text>')
    o.append(f'<text x="{width - 14}" y="18" font-size="11" fill="#64748b" text-anchor="end">{fs:.0f} Hz</text></svg>')
    return "".join(o)


def psd_svg(freqs: np.ndarray, psd_mean: np.ndarray, bands: dict[str, tuple[float, float]], *, width: int = 420,
            height: int = 190, fmax: float = 45.0) -> str:
    m = (freqs >= 1.0) & (freqs <= fmax)
    f = freqs[m]
    db = 10 * np.log10(np.maximum(psd_mean[m], 1e-12))
    lo, hi = float(db.min()), float(db.max())
    pad = 8
    L, R, T, B = 36, 8, 16, 24
    pw, ph = width - L - R, height - T - B

    def X(v): return L + pw * (v - 1.0) / (fmax - 1.0)
    def Y(v): return T + ph * (1 - (v - lo) / max(hi - lo, 1e-9))

    cols = ["#6366f1", "#10b981", "#f59e0b", "#ef4444"]
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" font-family="{FONT}">',
         f'<rect width="{width}" height="{height}" rx="12" fill="#0f172a"/>']
    for k, (name, (b0, b1)) in enumerate(bands.items()):
        o.append(f'<rect x="{_fmt(X(b0))}" y="{T}" width="{_fmt(X(min(b1, fmax)) - X(b0))}" height="{ph}" fill="{cols[k % 4]}" opacity=".16"/>'
                 f'<text x="{_fmt((X(b0) + X(min(b1, fmax))) / 2)}" y="{T + 11}" font-size="10" text-anchor="middle" fill="{cols[k % 4]}" font-weight="700">{esc(name)}</text>')
    pts = " ".join(f"{_fmt(X(a))},{_fmt(Y(b))}" for a, b in zip(f, db))
    o.append(f'<polyline points="{pts}" fill="none" stroke="#22d3ee" stroke-width="2"/>')
    for hz in (10, 20, 30, 40):
        o.append(f'<text x="{_fmt(X(hz))}" y="{height - 8}" font-size="10" fill="#64748b" text-anchor="middle">{hz}</text>')
    o.append(f'<text x="{pad}" y="{height - 8}" font-size="10" fill="#64748b">Hz</text>'
             f'<text x="4" y="{T + ph / 2}" font-size="10" fill="#64748b" transform="rotate(-90 8 {T + ph / 2})" text-anchor="middle">dB</text></svg>')
    return "".join(o)


def probability_bar_html(proba: dict[str, float], gate: float) -> str:
    rows = []
    for name, p in proba.items():
        col = "#6366f1" if name == "Left" else "#0ea5e9"
        rows.append(f'<div class="nl-prob"><span>P({esc(name)})</span><div class="nl-prob-track"><div style="width:{p * 100:.1f}%;background:{col}"></div>'
                    f'<i style="left:{gate * 100:.1f}%"></i></div><b>{p:.1%}</b></div>')
    return "".join(rows)
