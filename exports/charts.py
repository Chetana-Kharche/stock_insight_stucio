"""Matplotlib charts for the PDF reports.

Every chart function returns {"png": bytes, "unit": "…"} (or None when there is no data).
The unit string is printed above the chart, e.g. "₹ thousand crore", "₹ per share", "% of shares".
"""
from __future__ import annotations

import io
from datetime import date
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from analysis.metrics import find_series  # noqa: E402

NAVY = "#0B3C5D"
ORANGE = "#E8710A"
GREY = "#8A94A6"
TEAL = "#1B998B"
PALETTE = [NAVY, ORANGE, TEAL, "#C3423F", "#6C5B7B", GREY]

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": "#B0B7C3",
    "axes.titleweight": "bold",
    "axes.titlesize": 9,
    "axes.titlecolor": NAVY,
    "legend.frameon": False,
    "legend.fontsize": 7,
    "xtick.color": "#4A5568",
    "ytick.color": "#4A5568",
    "grid.color": "#E2E8F0",
})


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=170)
    plt.close(fig)
    return buf.getvalue()


def money_scale(values) -> tuple[float, str]:
    """Pick a readable unit for amounts stored in ₹ crore: (divisor, unit label)."""
    vals = [abs(v) for v in values if v is not None]
    mx = max(vals) if vals else 0
    if mx >= 1e5:
        return 1e5, "₹ lakh crore"
    if mx >= 1e3:
        return 1e3, "₹ thousand crore"
    return 1.0, "₹ crore"


def _fy(label: str) -> str:
    return label.replace("Mar ", "FY") if label.startswith("Mar ") else label


def annual_revenue_profit(payload: dict, size=(6.2, 2.6)) -> Optional[dict]:
    rev = find_series(payload, "profit-loss", "Sales", "Revenue")
    np_ = find_series(payload, "profit-loss", "Net Profit")
    if not rev or not np_:
        return None
    pts = [(l, r, n) for (l, r), (_, n) in zip(rev.annual, np_.annual) if r is not None][-10:]
    if not pts:
        return None
    div, unit = money_scale([p[1] for p in pts])
    fig, ax = plt.subplots(figsize=size)
    x = range(len(pts))
    ax.bar([i - 0.2 for i in x], [p[1] / div for p in pts], 0.38, color=NAVY, label=rev.metric)
    ax.bar([i + 0.2 for i in x], [(p[2] or 0) / div for p in pts], 0.38, color=ORANGE, label="Net Profit")
    ax.set_xticks(list(x), [_fy(p[0]) for p in pts])
    ax.set_title(f"{rev.metric} and Net Profit, by year")
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    ax.legend(loc="upper left")
    return {"png": _png(fig), "unit": unit}


def quarterly_trend(payload: dict, size=(6.2, 2.6)) -> Optional[dict]:
    rev = find_series(payload, "quarters", "Sales", "Revenue")
    np_ = find_series(payload, "quarters", "Net Profit")
    if not rev or not np_:
        return None
    pts = [(l, r, n) for (l, r), (_, n) in zip(rev.quarterly, np_.quarterly)]
    if not pts:
        return None
    div, unit = money_scale([p[2] for p in pts] or [p[1] for p in pts])
    fig, axes = plt.subplots(1, 2, figsize=size)
    for ax, idx, title, col in ((axes[0], 1, rev.metric, NAVY), (axes[1], 2, "Net Profit", ORANGE)):
        ax.bar(range(len(pts)), [(p[idx] or 0) / div for p in pts], 0.6, color=col)
        ax.set_xticks(range(len(pts)), [p[0] for p in pts], rotation=60, ha="right", fontsize=6)
        ax.set_title(f"{title}, by quarter")
        ax.grid(axis="y")
        ax.set_axisbelow(True)
    return {"png": _png(fig), "unit": unit}


def margins_returns(payload: dict, size=(6.2, 2.6)) -> Optional[dict]:
    opm = find_series(payload, "profit-loss", "OPM %", "Financing Margin %")
    roe = find_series(payload, "ratios", "ROE %")
    roce = find_series(payload, "ratios", "ROCE %")
    series = [s for s in (opm, roe, roce) if s and any(v is not None for v in s.values())]
    if not series:
        return None
    fig, ax = plt.subplots(figsize=size)
    for s, col in zip(series, [ORANGE, NAVY, TEAL]):
        pts = s.annual[-10:]
        ax.plot([_fy(l) for l, _ in pts], [v for _, v in pts], marker="o", lw=1.8, color=col, label=s.metric)
    ax.set_title("Margins and return ratios")
    ax.grid(axis="y")
    ax.legend(loc="best")
    return {"png": _png(fig), "unit": "percent (%)"}


def shareholding_trend(payload: dict, size=(6.2, 2.6)) -> Optional[dict]:
    shq = (payload.get("shareholding") or {}).get("quarterly")
    if not shq:
        return None
    labels = [c["label"] for c in shq["columns"]]
    fig, ax = plt.subplots(figsize=size)
    n = 0
    for r, col in zip([r for r in shq["rows"] if r["unit"] == "PERCENT"], PALETTE):
        ax.plot(labels, r["numbers"], marker="o", ms=3, lw=1.6, color=col, label=r["metric"])
        n += 1
    if not n:
        plt.close(fig)
        return None
    ax.set_title("Shareholding pattern")
    ax.grid(axis="y")
    ax.tick_params(axis="x", rotation=45)
    ax.legend(loc="center left", bbox_to_anchor=(1, 0.5))
    return {"png": _png(fig), "unit": "% of total shares"}


def price_chart(prices: list[dict], size=(6.2, 2.6)) -> Optional[dict]:
    pts = [p for p in prices if p.get("close") is not None]
    if len(pts) < 5:
        return None
    d = [date.fromisoformat(str(p["date"])[:10]) for p in pts]
    fig, ax = plt.subplots(figsize=size)
    ax.plot(d, [p["close"] for p in pts], color=NAVY, lw=1.2, label="Close")
    if any(p.get("dma50") for p in pts):
        ax.plot(d, [p.get("dma50") for p in pts], color=ORANGE, lw=0.9, label="50-day average")
    if any(p.get("dma200") for p in pts):
        ax.plot(d, [p.get("dma200") for p in pts], color=GREY, lw=0.9, ls="--", label="200-day average")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b-%y"))
    ax.set_title("Share price on NSE")
    ax.grid(axis="y")
    ax.legend(loc="upper left")
    return {"png": _png(fig), "unit": "₹ per share"}


def pe_chart(pe_history: dict, size=(6.2, 2.6)) -> Optional[dict]:
    pe = [(date.fromisoformat(str(a)[:10]), b) for a, b in (pe_history or {}).get("Price to Earning", []) if b]
    if len(pe) < 5:
        return None
    fig, ax = plt.subplots(figsize=size)
    ax.plot([x for x, _ in pe], [y for _, y in pe], color=NAVY, lw=1.2, label="P/E")
    med = (pe_history or {}).get("Median PE") or []
    if med and med[-1][1]:
        ax.axhline(float(med[-1][1]), color=ORANGE, ls="--", lw=1, label=f"Median P/E {float(med[-1][1]):.1f}")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b-%y"))
    ax.set_title("Trailing P/E")
    ax.grid(axis="y")
    ax.legend(loc="upper left")
    return {"png": _png(fig), "unit": "times (x)"}


def _fy_short(label: str, estimate: bool = False) -> str:
    """'Mar 2027' -> 'FY27' / 'FY27E'."""
    if label.startswith("Mar ") and label[4:].isdigit():
        return f"FY{label[-2:]}{'E' if estimate else ''}"
    return label + ("E" if estimate else "")


def forecast_chart(forecast: dict, size=(6.6, 2.5)) -> Optional[dict]:
    """History (solid) + base projection (dashed) + 80% range (shaded) for each annual series."""
    blocks = [b for b in (forecast or {}).get("annual", []) if b.get("ok")]
    if not blocks:
        return None
    money = [b for b in blocks if b["unit"] == "INR_CRORE"]
    # one scale for all rupee panels, chosen from the smallest series so no panel reads 0.x
    div, money_unit = money_scale([min(b["last_actual"] for b in money)] if money else [0])
    fig, axes = plt.subplots(1, len(blocks), figsize=(size[0], size[1]), squeeze=False)
    for ax, b in zip(axes[0], blocks):
        is_money = b["unit"] == "INR_CRORE"
        d = div if is_money else 1.0
        unit = money_unit if is_money else "₹ per share"
        hist = [(h["label"], h["value"]) for h in b["history"] if h["value"] is not None][-6:]
        hx = list(range(len(hist)))
        fx = [hx[-1] + i for i in range(len(b["base"]) + 1)]
        ax.plot(hx, [v / d for _, v in hist], color=NAVY, lw=1.8, marker="o", ms=3, label="Reported")
        ax.plot(fx, [hist[-1][1] / d] + [v / d for v in b["base"]], color=ORANGE, lw=1.8, ls="--", marker="o", ms=3,
                label="Projection")
        ax.fill_between(fx, [hist[-1][1] / d] + [v / d for v in b["low"]],
                        [hist[-1][1] / d] + [v / d for v in b["high"]], color=ORANGE, alpha=0.15, lw=0,
                        label="80% range")
        if b.get("timesfm"):
            ax.plot(fx, [hist[-1][1] / d] + [v / d for v in b["timesfm"]["base"]], color="#12783C", lw=1.4, ls=":",
                    marker="s", ms=2.5, label="TimesFM")
        labels = [_fy_short(l) for l, _ in hist] + [_fy_short(l, True) for l in b["labels"]]
        ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right", fontsize=6)
        ax.set_title(f"{b['name']} ({unit})", fontsize=8)
        ax.grid(axis="y")
        ax.set_axisbelow(True)
    axes[0][0].legend(loc="upper left", fontsize=6)
    has_eps = any(b["unit"] != "INR_CRORE" for b in blocks)
    if money:
        unit = money_unit + (" · EPS in ₹ per share" if has_eps else "")
    else:
        unit = "₹ per share"
    return {"png": _png(fig), "unit": unit}
