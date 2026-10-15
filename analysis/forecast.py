"""Statistical projections for revenue, net profit and EPS.

Libraries: scikit-learn (robust trend regression), SciPy (parameter optimisation), NumPy.

Method (per series):
  1. Work on log values when every value is positive (growth compounds), raw values otherwise.
  2. Detect a one-off structural break (merger / demerger style jump) and level-adjust the history
     so the jump does not inflate the growth rate.
  3. Fit three models (four with the optional TimesFM AI model, see analysis/timesfm_model.py):
     robust trend (HuberRegressor), damped Holt exponential smoothing
     (parameters by SciPy optimisation) and a fading recent-momentum model.  Quarterly series add
     a same-quarter-last-year model.
  4. Walk-forward backtest every model on the company's own history; weight the models by their
     backtest accuracy and average them into the base projection.
  5. Build an 80% range from the size of the backtest errors at each horizon.

These are extrapolations of past figures.  They know nothing about management plans, interest
rates, regulation or one-off events and must be read as projections, not predictions.
"""
from __future__ import annotations

import math
import warnings
from typing import Optional

import numpy as np

from analysis.metrics import find_series, summary_value
from core.utils import fmt_num

HORIZON_YEARS = 3
HORIZON_QUARTERS = 4
Z80 = 1.2816  # two-sided 80% interval
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ------------------------------------------------------------------ individual models
def _trend_forecast(z: np.ndarray, h: int) -> np.ndarray:
    """Robust linear trend (recent points weighted more), anchored on the last actual value."""
    from sklearn.linear_model import HuberRegressor, LinearRegression

    n = len(z)
    x = np.arange(n, dtype=float).reshape(-1, 1)
    w = 0.75 ** (n - 1 - np.arange(n))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            slope = float(HuberRegressor(epsilon=1.35, alpha=0.0, max_iter=500).fit(x, z, sample_weight=w).coef_[0])
    except Exception:  # noqa: BLE001 - fall back to ordinary least squares
        slope = float(LinearRegression().fit(x, z, sample_weight=w).coef_[0])
    return z[-1] + slope * np.arange(1, h + 1)


def _holt_run(z: np.ndarray, alpha: float, beta: float, phi: float, h: int) -> tuple[np.ndarray, np.ndarray]:
    level = z[0]
    trend = float(np.mean(np.diff(z[: min(4, len(z))]))) if len(z) > 1 else 0.0
    errs = []
    for t in range(1, len(z)):
        pred = level + phi * trend
        errs.append(z[t] - pred)
        new_level = alpha * z[t] + (1 - alpha) * pred
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level
    damp = np.cumsum(phi ** np.arange(1, h + 1))
    return level + damp * trend, np.array(errs)


def _holt_forecast(z: np.ndarray, h: int) -> np.ndarray:
    """Damped-trend exponential smoothing; alpha, beta, phi chosen by SciPy to minimise squared error."""
    from scipy.optimize import minimize

    def sse(p):
        return float(np.sum(_holt_run(z, p[0], p[1], p[2], 1)[1] ** 2))

    best = None
    for x0 in ((0.5, 0.1, 0.9), (0.8, 0.2, 0.95), (0.3, 0.05, 0.85)):
        try:
            res = minimize(sse, x0, method="L-BFGS-B", bounds=[(0.05, 0.95), (0.01, 0.5), (0.80, 0.98)])
        except Exception:  # noqa: BLE001
            continue
        if best is None or res.fun < best.fun:
            best = res
    a, b, phi = best.x if best is not None else (0.5, 0.1, 0.9)
    return _holt_run(z, a, b, phi, h)[0]


def _momentum_forecast(z: np.ndarray, h: int) -> np.ndarray:
    """Recent growth that fades towards the recency-weighted long-run growth."""
    d = np.diff(z)
    w = 0.8 ** (len(d) - 1 - np.arange(len(d)))
    g_long = float(np.sum(w * d) / np.sum(w))
    g_recent = float(np.mean(d[-3:]))
    steps = g_long + (g_recent - g_long) * 0.6 ** np.arange(1, h + 1)
    return z[-1] + np.cumsum(steps)


def _seasonal_forecast(z: np.ndarray, h: int, season: int) -> np.ndarray:
    """Same period last year plus the recent year-on-year change (slightly faded)."""
    yoy = float(np.mean(z[-season:]) - np.mean(z[-2 * season:-season]))
    out = []
    for k in range(1, h + 1):
        ref = z[len(z) - season + ((k - 1) % season)]
        out.append(ref + yoy * 0.8 * (1 + (k - 1) // season))
    return np.array(out)


def _models(season: Optional[int], n: int) -> dict:
    m = {"Robust trend (recent years weighted)": _trend_forecast, "Damped Holt smoothing": _holt_forecast,
         "Fading momentum": _momentum_forecast}
    if season and n >= 2 * season:
        m["Same quarter last year + growth"] = lambda z, h: _seasonal_forecast(z, h, season)
    from analysis import timesfm_model

    if timesfm_model.enabled() and timesfm_model.load() is not None:
        m[timesfm_model.MODEL_LABEL] = timesfm_model.forecast   # tested and weighted like the others
    return m


# ------------------------------------------------------------------ structural break
def _detect_break(z: np.ndarray, log_space: bool) -> Optional[tuple[int, float]]:
    """Return (index of first post-break point, step size) for a single abnormal jump, else None."""
    d = np.diff(z)
    if len(d) < 7:
        return None
    med = float(np.median(d))
    mad = float(np.median(np.abs(d - med))) or 1e-9
    dev = np.abs(d - med)
    i = int(np.argmax(dev))
    second = float(np.sort(dev)[-2]) if len(dev) > 1 else 0.0
    isolated = dev[i] > 3 * 1.4826 * mad or dev[i] > 2.5 * second
    if log_space and dev[i] > 0.15 and isolated:
        others = np.delete(d, i)
        return i + 1, float(d[i] - np.median(others))
    return None


# ------------------------------------------------------------------ one series
def forecast_series(values: list[Optional[float]], h: int, season: Optional[int] = None,
                    min_points: int = 5) -> dict:
    """Project `h` steps ahead. Returns {'ok': False, 'reason': ...} when the history is unusable."""
    vals = list(values)
    while vals and vals[0] is None:
        vals.pop(0)
    if any(v is None for v in vals):
        last_none = max(i for i, v in enumerate(vals) if v is None)
        vals = vals[last_none + 1:]
    n = len(vals)
    if n < min_points:
        return {"ok": False, "reason": f"only {n} usable data points (need {min_points})"}
    raw = np.array(vals, dtype=float)
    log_space = bool(np.all(raw > 0))
    z = np.log(raw) if log_space else raw.copy()

    brk = _detect_break(z, log_space)
    step, break_info = 0.0, None
    if brk:
        idx, step = brk
        z = z.copy()
        z[idx:] -= step
        break_info = {"index": idx, "change_pct": round((math.exp(step) - 1) * 100, 1)}

    models = _models(season, n)
    min_train = max(min_points, (2 * season) if season else min_points)
    origins = list(range(max(min_train, n - 5), n))
    errors: dict[str, dict[int, list[float]]] = {name: {} for name in models}
    for o in origins:
        hh = min(h, n - o)
        for name, fn in models.items():
            try:
                fc = fn(z[:o], hh)
            except Exception:  # noqa: BLE001
                continue
            for k in range(hh):
                errors[name].setdefault(k + 1, []).append(float(z[o + k] - fc[k]))

    def _mae(name: str) -> Optional[float]:
        allv = [abs(e) for lst in errors[name].values() for e in lst]
        return float(np.mean(allv)) if allv else None

    maes = {name: _mae(name) for name in models}
    scale = (float(np.std(np.diff(z))) or 1e-6)
    if all(v is None for v in maes.values()):
        weights = {name: 1 / len(models) for name in models}
    else:
        inv = {name: 1 / ((maes[name] if maes[name] is not None else 10 * scale) + 0.25 * scale) for name in models}
        tot = sum(inv.values())
        weights = {name: v / tot for name, v in inv.items()}

    forecasts = {}
    for name, fn in models.items():
        try:
            forecasts[name] = fn(z, h)
        except Exception:  # noqa: BLE001
            weights[name] = 0.0
    tot = sum(weights[nm] for nm in forecasts) or 1.0
    weights = {nm: weights[nm] / tot for nm in forecasts}
    base_z = sum(weights[nm] * forecasts[nm] for nm in forecasts)

    # ensemble backtest errors per horizon (using the final weights)
    ens_err: dict[int, list[float]] = {}
    for k in range(1, h + 1):
        lens = [len(errors[nm].get(k, [])) for nm in forecasts]
        for j in range(min(lens) if lens else 0):
            ens_err.setdefault(k, []).append(sum(weights[nm] * errors[nm][k][j] for nm in forecasts))
    d = np.diff(z)
    s1 = float(np.std(d - np.median(d))) or 1e-6
    sigmas = []
    for k in range(1, h + 1):
        rmse = float(np.sqrt(np.mean(np.square(ens_err[k])))) if len(ens_err.get(k, [])) >= 2 else 0.0
        sigmas.append(max(rmse, s1 * math.sqrt(k)))
    sigmas = list(np.maximum.accumulate(sigmas))

    base_z = base_z + step
    low_z = base_z - Z80 * np.array(sigmas)
    high_z = base_z + Z80 * np.array(sigmas)
    conv = np.exp if log_space else (lambda a: a)
    base, low, high = conv(base_z), conv(low_z), conv(high_z)

    all_ens = [e for lst in ens_err.values() for e in lst]
    if log_space:
        mape = float(np.mean([abs(math.exp(e) - 1) for e in all_ens]) * 100) if all_ens else None
    else:
        denom = float(np.mean(np.abs(raw))) or 1.0
        mape = float(np.mean(np.abs(all_ens)) / denom * 100) if all_ens else None
    if mape is None or not log_space:
        confidence = "Low"
    else:
        confidence = "High" if mape < 8 else ("Medium" if mape < 18 else "Low")
        if (break_info or n < 8) and confidence == "High":
            confidence = "Medium"
        if len(all_ens) < 4:
            confidence = "Low"

    prev = [float(raw[-1])] + [float(b) for b in base[:-1]]
    growth = [float((b / p - 1) * 100) if p and p > 0 and b > 0 else None for b, p in zip(base, prev)]
    cagr = float(((float(base[-1]) / float(raw[-1])) ** (1 / h) - 1) * 100) if log_space else None

    def _model_mape(name: str) -> Optional[float]:
        allv = [e for lst in errors[name].values() for e in lst]
        if not allv:
            return None
        return float(np.mean([abs(math.exp(e) - 1) for e in allv]) * 100) if log_space else None

    tfm = None
    from analysis import timesfm_model

    if timesfm_model.MODEL_LABEL in forecasts:
        try:
            r = timesfm_model.forecast_range(z, h)
            tfm = {"base": [float(x) for x in conv(r["point"] + step)],
                   "low": [float(x) for x in conv(r["low"] + step)] if r["low"] is not None else None,
                   "high": [float(x) for x in conv(r["high"] + step)] if r["high"] is not None else None,
                   "weight_pct": round(weights[timesfm_model.MODEL_LABEL] * 100, 1),
                   "backtest_mape_pct": _model_mape(timesfm_model.MODEL_LABEL)}
        except Exception:  # noqa: BLE001 - TimesFM is optional
            tfm = None

    return {
        "ok": True, "points": n, "log_space": log_space, "last_actual": float(raw[-1]), "timesfm": tfm,
        "base": [float(x) for x in base], "low": [float(x) for x in low], "high": [float(x) for x in high],
        "growth_pct": growth, "cagr_pct": cagr, "backtest_mape_pct": mape, "backtest_samples": len(all_ens),
        "confidence": confidence, "break": break_info,
        "models": [{"name": nm, "weight_pct": round(weights[nm] * 100, 1),
                    "backtest_mape_pct": _model_mape(nm),
                    "forecast": [float(x) for x in (conv(forecasts[nm] + step))]} for nm in forecasts],
    }


# ------------------------------------------------------------------ labels
def _next_labels(last_label: str, h: int, step_months: int) -> list[str]:
    try:
        mon, yr = last_label.split()
        m = _MONTHS.index(mon[:3].title())
        y = int(yr)
    except (ValueError, IndexError):
        return [f"+{i}" for i in range(1, h + 1)]
    out = []
    for _ in range(h):
        m += step_months
        y += m // 12
        m %= 12
        out.append(f"{_MONTHS[m]} {y}")
    return out


def fiscal_label(label: str, estimate: bool = False) -> str:
    """'Mar 2027' -> 'FY27' (or 'FY27E')."""
    try:
        mon, yr = label.split()
        y = int(yr)
        fy = y if mon.lower().startswith(("jan", "feb", "mar")) else y + 1
        return f"FY{str(fy)[-2:]}{'E' if estimate else ''}"
    except (ValueError, IndexError):
        return label


def quarter_label(label: str, estimate: bool = False) -> str:
    """'Sep 2026' -> 'Q2FY27' (or 'Q2FY27E')."""
    try:
        mon, yr = label.split()
        y = int(yr)
        q, add = {"jun": (1, 1), "sep": (2, 1), "dec": (3, 1), "mar": (4, 0)}[mon.lower()[:3]]
        return f"Q{q}FY{str(y + add)[-2:]}{'E' if estimate else ''}"
    except (ValueError, IndexError, KeyError):
        return label


# ------------------------------------------------------------------ whole company
def _series_block(name: str, unit: str, pts: list[tuple[str, Optional[float]]], h: int, step_months: int,
                  season: Optional[int], min_points: int) -> Optional[dict]:
    if not pts:
        return None
    labels = [l for l, _ in pts]
    res = forecast_series([v for _, v in pts], h, season=season, min_points=min_points)
    res["name"], res["unit"] = name, unit
    res["history"] = [{"label": l, "value": v} for l, v in pts[-10:]]
    if res["ok"]:
        res["labels"] = _next_labels(labels[-1], h, step_months)
        res["last_label"] = labels[-1]
        if res.get("break"):
            i = res["break"]["index"]
            used = pts[len(pts) - res["points"]:]
            res["break"]["label"] = used[i][0] if i < len(used) else None
    return res


def method_text() -> str:
    from analysis import timesfm_model

    base = ("Weighted average of statistical models (robust trend regression, damped Holt exponential smoothing, "
            "fading momentum")
    if timesfm_model.enabled() and timesfm_model.load() is not None:
        base += ", and Google Research's TimesFM AI forecasting model"
    return (base + "), each tested on the company's own past and weighted by how accurate it was. Ranges are 80% "
            "intervals from those test errors.")


def build_forecast(payload: dict) -> dict:
    """Projections for the next 3 fiscal years and 4 quarters, from Screener history only."""
    try:
        import scipy
        import sklearn
        libs = f"scikit-learn {sklearn.__version__}, SciPy {scipy.__version__}, NumPy {np.__version__}"
        from analysis import timesfm_model

        tf = timesfm_model.status()
        if tf["loaded"]:
            libs += f", TimesFM ({tf['checkpoint']})"
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"forecast libraries missing: {e}"}

    rev = find_series(payload, "profit-loss", "Sales", "Revenue")
    np_ = find_series(payload, "profit-loss", "Net Profit")
    eps = find_series(payload, "profit-loss", "EPS in Rs", "EPS")
    qrev = find_series(payload, "quarters", "Sales", "Revenue")
    qnp = find_series(payload, "quarters", "Net Profit")

    annual, quarterly = [], []
    for s, name, unit in ((rev, rev.metric if rev else "Revenue", "INR_CRORE"), (np_, "Net Profit", "INR_CRORE"),
                          (eps, "EPS", "INR")):
        if s:
            b = _series_block(name, unit, s.annual, HORIZON_YEARS, 12, None, 5)
            if b:
                annual.append(b)
    for s, name in ((qrev, qrev.metric if qrev else "Revenue"), (qnp, "Net Profit")):
        if s:
            b = _series_block(name, "INR_CRORE", s.quarterly, HORIZON_QUARTERS, 3, 4, 8)
            if b:
                quarterly.append(b)

    ok_annual = [b for b in annual if b.get("ok")]
    if not ok_annual and not [b for b in quarterly if b.get("ok")]:
        reasons = "; ".join(f"{b['name']}: {b.get('reason')}" for b in annual + quarterly if not b.get("ok"))
        return {"ok": False, "error": f"not enough history to project ({reasons})", "libraries": libs}

    by_name = {b["name"]: b for b in ok_annual}
    derived: dict = {}
    price = summary_value(payload, "Current Price")
    e = by_name.get("EPS")
    if e and price:
        derived["forward_pe"] = [{"label": l, "value": (price / v) if v > 0 else None}
                                 for l, v in zip(e["labels"], e["base"])]
        derived["price_used"] = price
    r = by_name.get(rev.metric if rev else "Revenue")
    p = by_name.get("Net Profit")
    if r and p:
        derived["net_margin_pct"] = [{"label": l, "value": (pv / rv * 100) if rv else None}
                                     for l, pv, rv in zip(p["labels"], p["base"], r["base"])]
        if r["last_actual"]:
            derived["net_margin_latest_pct"] = p["last_actual"] / r["last_actual"] * 100

    notes = []
    for b in ok_annual:
        if b.get("break"):
            notes.append(f"{b['name']}: an unusual one-off jump of {b['break']['change_pct']:+.0f}% around "
                         f"{b['break'].get('label') or 'one year'} was treated as a level shift (for example a merger), "
                         f"so it does not inflate the projected growth rate.")
        if not b["log_space"]:
            notes.append(f"{b['name']}: history contains losses or zeros, so a simpler linear method was used and "
                         f"confidence is low.")
    for b in annual + quarterly:
        if not b.get("ok"):
            notes.append(f"{b['name']} ({'quarterly' if b in quarterly else 'annual'}): not projected, {b.get('reason')}.")

    order = {"Low": 0, "Medium": 1, "High": 2}
    main = p or r or (ok_annual[0] if ok_annual else None)
    overall = main["confidence"] if main else "Low"
    if ok_annual:
        worst = min(ok_annual, key=lambda b: order[b["confidence"]])["confidence"]
        overall = worst if order[worst] < order[overall] else overall

    tf_status = timesfm_model.status()
    tf_used = any(b.get("timesfm") for b in annual + quarterly if b.get("ok"))
    timesfm_info = {"used": tf_used, "enabled": tf_status["enabled"], "checkpoint": tf_status["checkpoint"],
                    "api": tf_status["api"],
                    "reason": None if tf_used else timesfm_model.reason_text(tf_status),
                    "how_to_enable": None if tf_used else timesfm_model.HOW_TO_ENABLE}

    return {
        "ok": True,
        "timesfm": timesfm_info,
        "libraries": libs,
        "method": method_text(),
        "horizon_years": HORIZON_YEARS, "horizon_quarters": HORIZON_QUARTERS,
        "annual": annual, "quarterly": quarterly, "derived": derived, "confidence": overall, "notes": notes,
        "caveat": ("Projections extend past figures forward. They do not know about management plans, interest "
                   "rates, regulation, competition or one-off events, and actual results can fall outside the range."),
    }


# ------------------------------------------------------------------ display tables (shared by UI and PDF)
def _n(v: Optional[float], unit: str) -> str:
    if v is None:
        return "–"
    return fmt_num(v, 1 if unit == "INR" else 0)


def _unit_tag(unit: str) -> str:
    return "₹ per share" if unit == "INR" else "₹ crore"


def forecast_tables(fc: dict) -> dict:
    """Ready-to-render tables: {'annual','quarterly','reliability','models'} each {'columns','rows'}."""
    out: dict = {}
    if not fc or not fc.get("ok"):
        return out

    def proj_table(blocks: list[dict], lab) -> dict:
        ok = [b for b in blocks if b.get("ok")]
        if not ok:
            return {"columns": [], "rows": []}
        first = ok[0]
        cols = [f"{lab(first['last_label'])} (reported)"] + [lab(l, True) for l in first["labels"]]
        annual = lab is fiscal_label
        if annual:
            cols += ["Growth per year", "Confidence"]
        rows = []
        for b in ok:
            u = b["unit"]
            tail = [f"{b['cagr_pct']:.1f}%" if b.get("cagr_pct") is not None else "–", b["confidence"]] if annual else []
            rows.append({"metric": f"{b['name']} ({_unit_tag(u)}) · base case",
                         "values": [_n(b["last_actual"], u)] + [_n(v, u) for v in b["base"]] + tail, "bold": True})
            rows.append({"metric": "low case", "values": [""] + [_n(v, u) for v in b["low"]], "indent": True})
            rows.append({"metric": "high case", "values": [""] + [_n(v, u) for v in b["high"]], "indent": True})
            if annual:
                rows.append({"metric": "growth over previous year",
                             "values": [""] + [f"{g:+.1f}%" if g is not None else "–" for g in b["growth_pct"]],
                             "indent": True})
        return {"columns": cols, "rows": rows}

    out["annual"] = proj_table(fc.get("annual", []), fiscal_label)
    out["quarterly"] = proj_table(fc.get("quarterly", []), quarter_label)

    rel_rows, model_rows = [], []
    for kind, blocks, lab in (("yearly", fc.get("annual", []), fiscal_label),
                              ("quarterly", fc.get("quarterly", []), quarter_label)):
        for b in blocks:
            if not b.get("ok"):
                continue
            brk = b.get("break")
            rel_rows.append({"metric": f"{b['name']} ({kind})", "values": [
                str(b["points"]),
                f"{b['backtest_mape_pct']:.1f}%" if b.get("backtest_mape_pct") is not None else "–",
                str(b.get("backtest_samples", 0)), b["confidence"],
                f"{brk['change_pct']:+.0f}% at {lab(brk['label']) if brk.get('label') else '–'}" if brk else "none"]})
            if kind == "yearly":
                for mdl in b["models"]:
                    model_rows.append({"metric": f"{b['name']} · {mdl['name']}", "values": [
                        f"{mdl['weight_pct']:.0f}%",
                        f"{mdl['backtest_mape_pct']:.1f}%" if mdl.get("backtest_mape_pct") is not None else "–",
                    ] + [_n(v, b["unit"]) for v in mdl["forecast"]]})
    out["reliability"] = {"columns": ["Past periods used", "Average test error", "Tests run", "Confidence",
                                      "One-off jump adjusted"], "rows": rel_rows}
    ann_ok = [b for b in fc.get("annual", []) if b.get("ok")]
    out["models"] = {"columns": ["Weight", "Test error"] + ([fiscal_label(l, True) for l in ann_ok[0]["labels"]]
                                                           if ann_ok else []), "rows": model_rows}

    # TimesFM's own forecast next to the base case of all models
    for key, blocks, lab in (("timesfm_annual", fc.get("annual", []), fiscal_label),
                             ("timesfm_quarterly", fc.get("quarterly", []), quarter_label)):
        ok = [b for b in blocks if b.get("ok") and b.get("timesfm")]
        if not ok:
            continue
        first = ok[0]
        cols = [f"{lab(first['last_label'])} (reported)"] + [lab(l, True) for l in first["labels"]] + \
               ["Weight in base case", "Past test error"]
        rows = []
        for b in ok:
            t, u = b["timesfm"], b["unit"]
            rows.append({"metric": f"{b['name']} ({_unit_tag(u)}) · TimesFM forecast", "bold": True,
                         "values": [_n(b["last_actual"], u)] + [_n(v, u) for v in t["base"]]
                         + [f"{t['weight_pct']:.0f}%",
                            f"{t['backtest_mape_pct']:.1f}%" if t.get("backtest_mape_pct") is not None else "–"]})
            if t.get("low") and t.get("high"):
                rows.append({"metric": "TimesFM range (10% – 90%)", "indent": True, "values": [""] + [
                    f"{_n(lo, u)} – {_n(hi, u)}" for lo, hi in zip(t["low"], t["high"])] + ["", ""]})
            rows.append({"metric": "base case of all models", "indent": True,
                         "values": [""] + [_n(v, u) for v in b["base"]] + ["", ""]})
        out[key] = {"columns": cols, "rows": rows}

    d = fc.get("derived") or {}
    extra = []
    if d.get("forward_pe"):
        extra.append({"metric": f"P/E on projected EPS (x), at ₹{fmt_num(d['price_used'], 2)}",
                      "values": [f"{x['value']:.1f}" if x["value"] else "–" for x in d["forward_pe"]]})
    if d.get("net_margin_pct"):
        extra.append({"metric": "Net profit as % of revenue (projected)",
                      "values": [f"{x['value']:.1f}%" if x["value"] is not None else "–" for x in d["net_margin_pct"]]})
    if extra:
        key = "forward_pe" if d.get("forward_pe") else "net_margin_pct"
        out["derived"] = {"columns": [fiscal_label(x["label"], True) for x in d[key]], "rows": extra}
    return out


def outlook_sentences(fc: dict) -> list[str]:
    """Plain-language summary of the projections (used when the AI narrative is unavailable)."""
    if not fc or not fc.get("ok"):
        return []
    out = []
    for b in fc.get("annual", []):
        if not b.get("ok"):
            continue
        u = b["unit"]
        pre, suf = "₹", ("" if u == "INR" else " crore")
        last_l, end_l = fiscal_label(b["last_label"]), fiscal_label(b["labels"][-1], True)
        g = f", about {b['cagr_pct']:.1f}% a year" if b.get("cagr_pct") is not None else ""
        out.append(f"{b['name']}: model projection of {pre}{_n(b['base'][-1], u)}{suf} in {end_l} "
                   f"(range {pre}{_n(b['low'][-1], u)} to {pre}{_n(b['high'][-1], u)}{suf}) against "
                   f"{pre}{_n(b['last_actual'], u)}{suf} reported in {last_l}{g}; confidence {b['confidence'].lower()}.")
    return out
