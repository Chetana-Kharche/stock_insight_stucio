"""Interactive Plotly charts for the Streamlit UI (scraped data only)."""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from analysis.metrics import find_series

NAVY, ORANGE, GREY, TEAL = "#1C4DA0", "#FFA41C", "#9AA3AF", "#12783C"  # Value Research palette

# unit shown above each chart in the UI (the numbers plotted are exactly what Screener reports)
UNITS = {"price": "₹ per share", "annual": "₹ crore", "quarterly": "₹ crore", "returns": "percent (%)",
         "pe": "times (x)", "shareholding": "% of shares", "scorecard": "score out of 10"}


def _layout(fig, title: str, height: int = 320):
    fig.update_layout(title=dict(text=title, font=dict(size=15, color="#163A5F")), height=height,
                      margin=dict(l=12, r=12, t=50, b=12), font=dict(family="Segoe UI, Roboto, Arial, sans-serif", color="#212529"),
                      legend=dict(orientation="h", y=-0.18), plot_bgcolor="white", hovermode="x unified")
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#F0ECE6")
    return fig


def price_chart(prices: list[dict]):
    pts = [p for p in prices if p.get("close") is not None]
    if not pts:
        return None
    d = [p["date"] for p in pts]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d, y=[p["close"] for p in pts], name="Price (NSE)", line=dict(color=NAVY, width=1.6)))
    fig.add_trace(go.Scatter(x=d, y=[p.get("dma50") for p in pts], name="50 DMA", line=dict(color=ORANGE, width=1)))
    fig.add_trace(go.Scatter(x=d, y=[p.get("dma200") for p in pts], name="200 DMA",
                             line=dict(color=GREY, width=1, dash="dash")))
    return _layout(fig, "Share price with moving averages")


def annual_chart(payload: dict):
    rev = find_series(payload, "profit-loss", "Sales", "Revenue")
    np_ = find_series(payload, "profit-loss", "Net Profit")
    if not rev or not np_:
        return None
    labels = [l for l, _ in rev.annual]
    fig = go.Figure()
    fig.add_bar(x=labels, y=[v for _, v in rev.annual], name=rev.metric, marker_color=NAVY)
    fig.add_bar(x=labels, y=[v for _, v in np_.annual], name="Net Profit", marker_color=ORANGE)
    fig.update_layout(barmode="group")
    return _layout(fig, f"{rev.metric} and Net Profit, by year")


def quarterly_chart(payload: dict):
    """Two panels side by side (same unit) instead of two y-axes on one chart."""
    rev = find_series(payload, "quarters", "Sales", "Revenue")
    np_ = find_series(payload, "quarters", "Net Profit")
    if not rev or not np_:
        return None
    labels = [l for l, _ in rev.quarterly]
    fig = make_subplots(rows=1, cols=2, subplot_titles=(rev.metric, "Net Profit"), horizontal_spacing=0.09)
    fig.add_bar(x=labels, y=[v for _, v in rev.quarterly], name=rev.metric, marker_color=NAVY, row=1, col=1)
    fig.add_bar(x=labels, y=[v for _, v in np_.quarterly], name="Net Profit", marker_color=ORANGE, row=1, col=2)
    fig.update_layout(showlegend=False)
    return _layout(fig, "Quarterly revenue and net profit")


def returns_chart(payload: dict):
    series = [s for s in (find_series(payload, "profit-loss", "OPM %", "Financing Margin %"),
                          find_series(payload, "ratios", "ROE %"), find_series(payload, "ratios", "ROCE %")) if s]
    if not series:
        return None
    fig = go.Figure()
    for s, col in zip(series, [ORANGE, NAVY, TEAL]):
        fig.add_trace(go.Scatter(x=[l for l, _ in s.annual], y=[v for _, v in s.annual], name=s.metric,
                                 mode="lines+markers", line=dict(color=col, width=2)))
    return _layout(fig, "Margins and return ratios")


def pe_chart(pe_history: dict):
    pe = (pe_history or {}).get("Price to Earning") or []
    if not pe:
        return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[a for a, _ in pe], y=[b for _, b in pe], name="P/E", line=dict(color=NAVY)))
    med = (pe_history or {}).get("Median PE") or []
    if med and med[-1][1]:
        fig.add_hline(y=float(med[-1][1]), line_dash="dash", line_color=ORANGE,
                      annotation_text=f"Median {float(med[-1][1]):.1f}")
    return _layout(fig, "Trailing P/E vs 5-year median")


def shareholding_chart(payload: dict):
    shq = (payload.get("shareholding") or {}).get("quarterly")
    if not shq:
        return None
    labels = [c["label"] for c in shq["columns"]]
    fig = go.Figure()
    for r in shq["rows"]:
        if r["unit"] == "PERCENT":
            fig.add_trace(go.Scatter(x=labels, y=r["numbers"], name=r["metric"], mode="lines+markers"))
    return _layout(fig, "Shareholding pattern")


def scorecard_chart(items: list[dict]):
    fig = go.Figure(go.Bar(x=[i["score"] for i in items], y=[i["name"] for i in items], orientation="h",
                           marker_color=[TEAL if i["score"] >= 6.5 else (ORANGE if i["score"] >= 4.5 else "#B91C1C")
                                         for i in items], text=[f"{i['score']:.1f}" for i in items],
                           textposition="outside"))
    fig.update_xaxes(range=[0, 10.5])
    fig.update_yaxes(autorange="reversed")
    return _layout(fig, "Scorecard by factor", height=300)


def facts_chart(df, title: str):
    fig = go.Figure()
    for metric, g in df.groupby("metric"):
        fig.add_trace(go.Scatter(x=g["period_label"], y=g["value"], name=metric, mode="lines+markers"))
    return _layout(fig, title)


def forecast_charts(forecast: dict) -> list[tuple]:
    """One chart per projected yearly series: [(figure, unit_text)].

    Reported history is a solid line, the model's base case a dashed line and the 80% range a shaded band.
    """
    out = []
    for b in (forecast or {}).get("annual", []):
        if not b.get("ok"):
            continue
        hist = [(h["label"], h["value"]) for h in b["history"] if h["value"] is not None][-8:]
        if not hist:
            continue

        def fy(label: str, est: bool = False) -> str:
            short = f"FY{label[-2:]}" if label.startswith("Mar ") else label
            return short + ("E" if est else "")

        hx = [fy(l) for l, _ in hist]
        fx = [hx[-1]] + [fy(l, True) for l in b["labels"]]
        last = hist[-1][1]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=fx, y=[last] + b["high"], mode="lines", line=dict(width=0), showlegend=False,
                                 hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=fx, y=[last] + b["low"], mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor="rgba(232,113,10,0.16)", name="80% range", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=hx, y=[v for _, v in hist], name="Reported", mode="lines+markers",
                                 line=dict(color=NAVY, width=2.4)))
        fig.add_trace(go.Scatter(x=fx, y=[last] + b["base"], name="Projection (base case)", mode="lines+markers",
                                 line=dict(color=ORANGE, width=2.4, dash="dash")))
        if b.get("timesfm"):
            fig.add_trace(go.Scatter(x=fx, y=[last] + b["timesfm"]["base"], name="TimesFM AI forecast",
                                     mode="lines+markers", line=dict(color="#12783C", width=2, dash="dot")))
        _layout(fig, f"{b['name']}: reported and projected", height=330)
        out.append((fig, "₹ per share" if b["unit"] == "INR" else "₹ crore"))
    return out


RANGE_DAYS = {"1M": 31, "6M": 183, "1Yr": 366, "3Yr": 1096, "5Yr": 1827, "Max": None}


def _cut(dates: list, rng: str) -> int:
    days = RANGE_DAYS.get(rng)
    if not days or not dates:
        return 0
    from datetime import date, timedelta

    last = date.fromisoformat(str(dates[-1])[:10])
    start = last - timedelta(days=days)
    for i, d in enumerate(dates):
        if date.fromisoformat(str(d)[:10]) >= start:
            return i
    return 0


def price_range_chart(prices: list[dict], rng: str = "1Yr"):
    """Screener-style price chart with 50/200-day averages and volume, for a chosen period."""
    pts = [p for p in prices if p.get("close") is not None]
    if not pts:
        return None
    pts = pts[_cut([p["date"] for p in pts], rng):]
    d = [p["date"] for p in pts]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.04)
    fig.add_trace(go.Scatter(x=d, y=[p["close"] for p in pts], name="Price on NSE", line=dict(color=NAVY, width=1.8)),
                  row=1, col=1)
    if any(p.get("dma50") for p in pts):
        fig.add_trace(go.Scatter(x=d, y=[p.get("dma50") for p in pts], name="50 DMA",
                                 line=dict(color=ORANGE, width=1.1)), row=1, col=1)
    if any(p.get("dma200") for p in pts):
        fig.add_trace(go.Scatter(x=d, y=[p.get("dma200") for p in pts], name="200 DMA",
                                 line=dict(color=GREY, width=1.1, dash="dash")), row=1, col=1)
    if any(p.get("volume") for p in pts):
        fig.add_bar(x=d, y=[p.get("volume") for p in pts], name="Volume", marker_color="#C9D7F0", row=2, col=1)
    return _layout(fig, f"Share price · {rng}", height=420)


def pe_range_chart(pe_history: dict, rng: str = "1Yr"):
    pe = (pe_history or {}).get("Price to Earning") or []
    if not pe:
        return None
    pe = pe[_cut([a for a, _ in pe], rng):]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[a for a, _ in pe], y=[b for _, b in pe], name="P/E", line=dict(color=NAVY, width=1.8)))
    med = (pe_history or {}).get("Median PE") or []
    if med and med[-1][1]:
        fig.add_hline(y=float(med[-1][1]), line_dash="dash", line_color=ORANGE,
                      annotation_text=f"Median P/E {float(med[-1][1]):.1f}")
    eps = (pe_history or {}).get("EPS") or []
    if eps:
        eps = eps[_cut([a for a, _ in eps], rng):]
    return _layout(fig, f"Price to earnings · {rng}", height=380)


def allocation_donut(labels: list[str], values: list[float]):
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.55, sort=True,
                           marker=dict(colors=[NAVY, ORANGE, TEAL, "#163A5F", "#7FA3DE", "#C77700", "#5BAE7C",
                                               "#9AA3AF", "#3D6DC0", "#FFC56B"]),
                           textinfo="percent", hovertemplate="%{label}: ₹%{value:,.0f}<extra></extra>"))
    return _layout(fig, "Allocation by current value", height=330)
