"""Optional: Google Research's TimesFM time-series foundation model as a fourth projection model.

TimesFM is pre-trained on a very large collection of real time series and forecasts "zero-shot": it is
given the company's own history (from Screener) and returns the next values. In this project it joins the
three statistical models in analysis/forecast.py and goes through the same walk-forward test on the
company's past years, so it only gets a large weight when it was accurate for that company.

Needs PyTorch (a large download). setup_windows.bat installs it; manually:
    pip install "timesfm[torch]"
    .env:  TIMESFM_ENABLED=true
           TIMESFM_CHECKPOINT=google/timesfm-2.5-200m-pytorch   (Apache-2.0 weights)
           TIMESFM_DEVICE=cpu                                   (or cuda if you have an NVIDIA GPU)
TimesFM 3.0 weights (google/timesfm-3.0-pytorch) are licensed for non-commercial use only.

Several TimesFM releases have different Python APIs; load() tries each one and remembers which worked.
Any failure simply leaves TimesFM out of the projection - the report is still produced.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

from core.config import get_settings

log = logging.getLogger(__name__)
_LOCK = threading.Lock()
_STATE: dict = {"tried": False, "model": None, "api": None, "error": None, "checkpoint": None}
MODEL_LABEL = "TimesFM (Google Research AI model)"


def enabled() -> bool:
    return bool(get_settings().timesfm_enabled)


def _load_v3(ckpt: str, device: str):
    from timesfm3 import ModelConfig, TimesFM3Evaluator  # type: ignore

    model = TimesFM3Evaluator(ModelConfig(checkpoint_path=ckpt, per_core_batch_size=32, device=device))

    def run(series: np.ndarray, h: int):
        out = next(iter(model.predict_batch([series.astype(np.float32)], horizon=h, return_quantiles=True)))
        q = getattr(out, "quantiles", None)          # (h, 9): 10% ... 90%
        q = np.asarray(q, dtype=float) if q is not None else None
        return (np.asarray(out.forecast, dtype=float)[:h],
                q[:h, 0] if q is not None and q.ndim == 2 else None,
                q[:h, -1] if q is not None and q.ndim == 2 else None)

    return run


def _load_v25(ckpt: str, device: str):
    import timesfm  # type: ignore

    cls = getattr(timesfm, "TimesFM_2p5_200M_torch")
    model = cls.from_pretrained(ckpt)
    model.compile(timesfm.ForecastConfig(max_context=1024, max_horizon=64, normalize_inputs=True,
                                         use_continuous_quantile_head=True, fix_quantile_crossing=True))

    def run(series: np.ndarray, h: int):
        point, quant = model.forecast(horizon=h, inputs=[series.astype(np.float32)])
        return _split(point, quant, h)

    return run


def _split(point, quant, h: int):
    """point (batch, h); quant (batch, h, 10) = mean, 10%, 20% ... 90%."""
    p = np.asarray(point, dtype=float)[0][:h]
    try:
        q = np.asarray(quant, dtype=float)[0]
        return p, q[:h, 1], q[:h, -1]
    except Exception:  # noqa: BLE001
        return p, None, None


def _load_v1(ckpt: str, device: str):
    import timesfm  # type: ignore

    hp = timesfm.TimesFmHparams(backend="gpu" if device.startswith("cuda") else "cpu", per_core_batch_size=32,
                                horizon_len=64)
    if "2.0-500m" in ckpt:
        hp = timesfm.TimesFmHparams(backend="gpu" if device.startswith("cuda") else "cpu", per_core_batch_size=32,
                                    horizon_len=64, num_layers=50, use_positional_embedding=False, context_len=2048)
    model = timesfm.TimesFm(hparams=hp, checkpoint=timesfm.TimesFmCheckpoint(huggingface_repo_id=ckpt))

    def run(series: np.ndarray, h: int):
        point, quant = model.forecast([series.astype(np.float32)], freq=[1])
        return _split(point, quant, h)

    return run


def load():
    """Load the model once per process. Returns the forecast function or None."""
    with _LOCK:
        if _STATE["tried"]:
            return _STATE["model"]
        _STATE["tried"] = True
        if not enabled():
            _STATE["error"] = "switched off (TIMESFM_ENABLED=false)"
            return None
        s = get_settings()
        ckpt, device = s.timesfm_checkpoint, s.timesfm_device
        _STATE["checkpoint"] = ckpt
        loaders = [("timesfm 3.0", _load_v3)] if "3.0" in ckpt else []
        loaders += [("timesfm 2.5", _load_v25), ("timesfm 1.x/2.0", _load_v1)]
        errors = []
        for name, fn in loaders:
            try:
                _STATE["model"] = fn(ckpt, device)
                _STATE["api"] = name
                _STATE["error"] = None
                log.info("TimesFM loaded via %s (%s)", name, ckpt)
                return _STATE["model"]
            except Exception as e:  # noqa: BLE001 - try the next API
                errors.append(f"{name}: {type(e).__name__}: {str(e)[:120]}")
        _STATE["error"] = "; ".join(errors) or "not installed (pip install \"timesfm[torch]\")"
        log.warning("TimesFM not available: %s", _STATE["error"])
        return None


def forecast_range(z: np.ndarray, h: int) -> dict:
    """TimesFM's own forecast of h steps: {'point', 'low' (10%), 'high' (90%)} on the same scale as z."""
    run = load()
    if run is None:
        raise RuntimeError("TimesFM not available")
    point, low, high = run(np.asarray(z, dtype=float), h)
    point = np.asarray(point, dtype=float)
    if len(point) < h or not np.all(np.isfinite(point)):
        raise RuntimeError("TimesFM returned an incomplete forecast")
    ok = lambda a: a is not None and len(a) >= h and np.all(np.isfinite(a))  # noqa: E731
    return {"point": point[:h], "low": np.asarray(low, dtype=float)[:h] if ok(low) else None,
            "high": np.asarray(high, dtype=float)[:h] if ok(high) else None}


def forecast(z: np.ndarray, h: int) -> np.ndarray:
    """Point forecast only (used inside the walk-forward test and the weighted base case)."""
    return forecast_range(z, h)["point"]


def status() -> dict:
    """For the System status page and the report's method note."""
    if enabled() and not _STATE["tried"]:
        load()
    return {"enabled": enabled(), "loaded": _STATE["model"] is not None, "api": _STATE["api"],
            "checkpoint": _STATE["checkpoint"] or get_settings().timesfm_checkpoint, "error": _STATE["error"]}


HOW_TO_ENABLE = ('Install it once in the virtual environment: pip install "timesfm[torch]" '
                 '(downloads PyTorch), keep TIMESFM_ENABLED=true in .env and restart the app. '
                 'The first report then downloads the model weights from Hugging Face (about 1 GB).')


def reason_text(st: Optional[dict] = None) -> str:
    st = st or status()
    if not st["enabled"]:
        return "TimesFM is switched off (TIMESFM_ENABLED=false in .env)."
    err = st.get("error") or ""
    if "No module named" in err or "not installed" in err:
        return "TimesFM is not installed on this computer."
    return f"TimesFM could not be loaded ({err[:160]})."
