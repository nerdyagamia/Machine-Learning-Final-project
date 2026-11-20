"""EEG window analytics for display (PSD, band power, simple quality flags). No Streamlit imports."""
from __future__ import annotations

import numpy as np
from scipy.signal import welch


def psd(window: np.ndarray, fs: float, welch_cfg: dict | None = None):
    """Welch PSD per channel, using the partners' settings (hann, nperseg 512, 50 % overlap)."""
    cfg = welch_cfg or {}
    n = window.shape[-1]
    nperseg = int(min(cfg.get("nperseg", 512), n))
    noverlap = int(nperseg * float(cfg.get("overlap", 0.5)))
    f, p = welch(window, fs=fs, window=cfg.get("window", "hann"), nperseg=nperseg, noverlap=noverlap, axis=-1)
    return f, p


def band_shares(f: np.ndarray, p: np.ndarray, bands: dict[str, tuple[float, float]],
                total: tuple[float, float] = (4.0, 40.0)) -> dict[str, float]:
    """Share (0-1) of the 4-40 Hz power in each band, averaged over channels."""
    pm = p.mean(axis=0) if p.ndim == 2 else p
    df = float(f[1] - f[0])

    def integ(lo, hi):
        m = (f >= lo) & (f < hi)
        return float(pm[m].sum() * df)

    tot = integ(*total) or 1.0
    return {name: integ(lo, hi) / tot for name, (lo, hi) in bands.items()}


def quality(window: np.ndarray) -> tuple[float, list[str]]:
    """Heuristic signal quality 0-100 and per-channel notes (flat line / spikes)."""
    notes: list[str] = []
    ok = 0
    for i, ch in enumerate(window):
        sd = float(np.std(ch))
        if not np.isfinite(sd) or sd < 1e-6:
            notes.append(f"ch{i + 1}: flat line")
            continue
        z = np.abs((ch - np.mean(ch)) / sd).max()
        if z > 12:
            notes.append(f"ch{i + 1}: large spike")
            continue
        ok += 1
    return 100.0 * ok / max(len(window), 1), notes


def rms(window: np.ndarray) -> np.ndarray:
    return np.sqrt((window.astype(float) ** 2).mean(axis=-1))
