"""Interactive Plotly charts for the Streamlit UI (scraped data only)."""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from analysis.metrics import find_series

NAVY, ORANGE, GREY, TEAL = "#0B3C5D", "#E8710A", "#9CA3AF", "#1B998B"

# unit shown above each chart in the UI (the numbers plotted are exactly what Screener reports)
UNITS = {"price": "₹ per share", "annual": "₹ crore", "quarterly": "₹ crore", "returns": "percent (%)",
         "pe": "times (x)", "shareholding": "% of shares", "scorecard": "score out of 10"}


def _layout(fig, title: str, height: int = 320):
    fig.update_layout(title=dict(text=title, font=dict(size=15, color="#1D4ED8")), height=height,
                      margin=dict(l=12, r=12, t=50, b=12), font=dict(family="Inter, sans-serif"),
                      legend=dict(orientation="h", y=-0.18), plot_bgcolor="white", hovermode="x unified")
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#EEF2F7")
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
        _layout(fig, f"{b['name']}: reported and projected", height=330)
        out.append((fig, "₹ per share" if b["unit"] == "INR" else "₹ crore"))
    return out
