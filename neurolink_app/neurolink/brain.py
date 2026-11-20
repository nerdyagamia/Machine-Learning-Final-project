"""Helmet / BCI side: loads the partners' model + preprocessing code UNMODIFIED and decodes EEG windows.

Nothing in `Data_for_deployment/` is edited. Where the partners' files do not line up with each
other (for example `bci_preprocess.preprocess_file` expects a config dict with the keys
`channels/fs/bandpass/notch_hz/...`, which neither JSON file contains), the glue lives HERE.

No Streamlit imports.
"""
from __future__ import annotations

import io
import json
import tempfile
import time
import types
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import config


class ModelLoadError(RuntimeError):
    """Raised when the model bundle cannot be loaded (message is safe to show to the user)."""


# --------------------------------------------------------------------------- loading
def _load_module_from_file(name: str, path: Path) -> types.ModuleType:
    """Execute a .py file into a fresh module WITHOUT writing __pycache__ next to it."""
    mod = types.ModuleType(name)
    mod.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), mod.__dict__)
    return mod


def build_preprocess_cfg(meta: dict, pre_config: dict) -> dict:
    """Adapter: build the dict `bci_preprocess.preprocess_file(path, cfg)` needs.

    `preprocessing_config.json` stores these values under different key names (`bandpass_hz`,
    `notch.hz`, `sampling_rate.value_hz`, no `channels`), so passing it straight in raises KeyError.
    The model's meta file is the authoritative source for what the model was trained on.
    """
    pre = meta.get("preprocessing", {})
    inp = meta.get("input", {})
    notch = pre.get("notch_hz", (pre_config.get("notch") or {}).get("hz"))
    return {
        "channels": list(inp["channels"]),
        "fs": float(pre.get("fs_hz", (pre_config.get("sampling_rate") or {}).get("value_hz", 250.0))),
        "bandpass": tuple(pre.get("bandpass_hz", pre_config.get("bandpass_hz", (3.0, 40.0)))),
        "notch_hz": notch,
        "notch_q": float(pre.get("notch_q", 30.0)),
        "order": int(pre.get("filter_order", 4)),
        "edge_trim_s": float(pre.get("edge_trim_s", pre_config.get("edge_trim_s", 0.5))),
        "time_col": "Time",
    }


@dataclass
class ModelBundle:
    pipeline: object
    meta: dict
    pre_config: dict
    prep: types.ModuleType
    prep_cfg: dict
    labels: dict[int, str]

    @property
    def channels(self) -> list[str]:
        return list(self.meta["input"]["channels"])

    @property
    def n_channels(self) -> int:
        return int(self.meta["input"]["n_channels"])

    @property
    def n_times(self) -> int:
        return int(self.meta["input"]["n_times"])

    @property
    def fs(self) -> float:
        return float(self.prep_cfg["fs"])

    @property
    def class_order(self) -> list[int]:
        return [int(c) for c in getattr(self.pipeline, "classes_", sorted(self.labels))]

    @property
    def welch_cfg(self) -> dict:
        return dict(self.pre_config.get("welch", {"nperseg": 512, "overlap": 0.5, "window": "hann"}))

    @property
    def bands(self) -> dict[str, tuple[float, float]]:
        b = self.pre_config.get("bands_hz", {"theta": [4, 8], "mu": [8, 13], "beta": [13, 30]})
        return {k: (float(v[0]), float(v[1])) for k, v in b.items()}

    @property
    def total_band(self) -> tuple[float, float]:
        t = self.pre_config.get("total_band_hz", [4.0, 40.0])
        return float(t[0]), float(t[1])


def load_bundle(model_dir: str | Path | None = None) -> ModelBundle:
    d = Path(model_dir or config.MODEL_DIR)
    for fn in (config.MODEL_FILE, config.META_FILE, config.PRE_CONFIG_FILE, config.PREPROCESS_MODULE_FILE):
        if not (d / fn).exists():
            raise ModelLoadError(f"Missing file: {d / fn}")
    meta = json.loads((d / config.META_FILE).read_text(encoding="utf-8"))
    pre_config = json.loads((d / config.PRE_CONFIG_FILE).read_text(encoding="utf-8"))
    prep = _load_module_from_file("bci_preprocess", d / config.PREPROCESS_MODULE_FILE)

    try:
        import joblib
        pipeline = joblib.load(d / config.MODEL_FILE)
    except ModuleNotFoundError as exc:
        want = (meta.get("versions") or {})
        raise ModelLoadError(
            f"The model needs the package '{exc.name}' to load. Install the versions it was trained with: "
            f"pip install mne=={want.get('mne', '')} scikit-learn=={want.get('sklearn', '')} "
            f"numpy scipy joblib=={want.get('joblib', '')}"
        ) from exc
    except Exception as exc:  # version mismatch etc.
        raise ModelLoadError(f"Could not load {config.MODEL_FILE}: {type(exc).__name__}: {exc}") from exc

    labels = {int(k): str(v) for k, v in meta["classes"].items()}
    return ModelBundle(pipeline, meta, pre_config, prep, build_preprocess_cfg(meta, pre_config), labels)


# --------------------------------------------------------------------------- decoding
@dataclass
class Decision:
    label: str                      # "Left" | "Right"
    confidence: float               # probability of the winning class
    proba: dict[str, float]
    accepted: bool                  # confidence >= gate
    gate: float
    source: str                     # "replay" | "upload" | "live"
    trial_id: int | None = None
    truth: str | None = None        # recorded label (replay only)
    ts: float = field(default_factory=time.time)

    @property
    def command(self) -> str:
        return "turn_left" if self.label == "Left" else "turn_right"

    @property
    def correct(self) -> bool | None:
        return None if self.truth is None else self.truth == self.label


def check_window(bundle: ModelBundle, window: np.ndarray) -> np.ndarray:
    x = np.asarray(window, dtype=np.float64)
    if x.ndim != 2 or x.shape[0] != bundle.n_channels:
        raise ValueError(f"Expected a ({bundle.n_channels} channels, n_times) window, got shape {x.shape}.")
    if x.shape[1] < int(bundle.fs):
        raise ValueError(f"Window too short ({x.shape[1]} samples); need at least {int(bundle.fs)}.")
    if not np.isfinite(x).all():
        raise ValueError("Window contains NaN/inf values.")
    return x


def decode_window(bundle: ModelBundle, window: np.ndarray, gate: float, *, source: str = "replay",
                  trial_id: int | None = None, truth: str | None = None) -> Decision:
    x = check_window(bundle, window)
    proba = np.asarray(bundle.pipeline.predict_proba(x[None])[0], dtype=float)
    order = bundle.class_order
    named = {bundle.labels[c]: float(p) for c, p in zip(order, proba)}
    label = max(named, key=named.get)
    conf = named[label]
    return Decision(label, conf, named, conf >= gate, float(gate), source, trial_id, truth)


def preprocess_upload(bundle: ModelBundle, filename: str, data: bytes) -> np.ndarray:
    """Run an uploaded raw recording (.csv/.xlsx with FZ,C3,CZ,C4 columns) through the partners'
    own `preprocess_file`. Returns (n_channels, n_times) float32."""
    suffix = Path(filename).suffix.lower() or ".csv"
    if suffix not in (".csv", ".xlsx", ".xls"):
        raise ValueError("Please upload a .csv or .xlsx recording.")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / f"upload{suffix}"
        p.write_bytes(data)
        return bundle.prep.preprocess_file(p, bundle.prep_cfg)


# --------------------------------------------------------------------------- replay "helmet"
class ReplaySource:
    """Simulated helmet: replays recorded, already-preprocessed trials (n_times, n_channels)."""

    def __init__(self, replay_dir: str | Path | None = None):
        d = Path(replay_dir or config.REPLAY_DIR)
        self.X = np.load(d / config.REPLAY_EEG, mmap_mode="r")
        self.y = np.load(d / config.REPLAY_LABELS)
        ids_path = d / config.REPLAY_IDS
        if ids_path.exists():
            import pandas as pd
            ids = pd.read_csv(ids_path)
            self.file_ids = ids["file_id"].to_numpy()
        else:
            self.file_ids = np.arange(len(self.y))

    def __len__(self) -> int:
        return int(self.X.shape[0])

    def get(self, i: int) -> tuple[np.ndarray, str, int]:
        i = int(i) % len(self)
        window = np.asarray(self.X[i], dtype=np.float32).T       # -> (n_channels, n_times)
        truth = "Left" if int(self.y[i]) == 0 else "Right"
        return window, truth, int(self.file_ids[i])

    def pick(self, mode: str, current: int, rng: np.random.Generator) -> int:
        if mode == "sequential":
            return (current + 1) % len(self)
        if mode in ("Left", "Right"):                              # random trial of that recorded class
            want = 0 if mode == "Left" else 1
            pool = np.flatnonzero(self.y == want)
            return int(rng.choice(pool))
        return int(rng.integers(len(self)))


@dataclass
class ConfidenceProfile:
    n: int
    min_conf: float
    median_conf: float
    max_conf: float
    balanced_accuracy: float
    frac_above: dict[float, float]


def confidence_profile(bundle: ModelBundle, replay: ReplaySource) -> ConfidenceProfile:
    """Run the model over the replay set once - gives caregivers an honest picture of reliability."""
    X = np.asarray(replay.X, dtype=np.float64).transpose(0, 2, 1)
    proba = np.asarray(bundle.pipeline.predict_proba(X), dtype=float)
    order = bundle.class_order
    pred = np.array(order)[proba.argmax(1)]
    conf = proba.max(1)
    y = np.asarray(replay.y).astype(int)
    recalls = [float((pred[y == c] == c).mean()) for c in np.unique(y)]
    return ConfidenceProfile(
        n=len(y), min_conf=float(conf.min()), median_conf=float(np.median(conf)), max_conf=float(conf.max()),
        balanced_accuracy=float(np.mean(recalls)),
        frac_above={g: float((conf >= g).mean()) for g in (0.5, 0.51, 0.52, 0.55, 0.6, 0.7)},
    )
