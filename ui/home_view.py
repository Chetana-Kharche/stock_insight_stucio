"""Home page (after sign-in): live market overview in the style of a broker's explore page.

Indices with intraday sparklines, a large index chart (1D to 5Y), market breadth, popular companies on
Stock Insight Studio, top gainers / losers / volume shockers / most traded / 52-week highs and lows, top companies
by market cap, sectors today, your watchlist and the latest market news.
Data: NSE India (live) with Yahoo Finance for charts and as fallback - see analysis/home_data.py.
"""
from __future__ import annotations

from datetime import datetime
from datetime import timedelta, timezone
from typing import Optional

import plotly.graph_objects as go
import streamlit as st

from analysis import home_data as HD
from core import repository as repo
from ui import components as C
from ui.html import e

UP, DOWN, FLAT = "#12783C", "#C62828", "#595959"
IST = timezone(timedelta(hours=5, minutes=30))   # India time (no daylight saving)

CSS = """
<style>
.hm-hello{font-size:.95rem;color:var(--vr-muted);margin:2px 0 2px}
.hm-h{font-size:1.18rem;font-weight:800;color:var(--vr-navy);margin:22px 0 10px;display:flex;align-items:baseline;gap:10px}
.hm-h small{font-size:.8rem;font-weight:500;color:var(--vr-muted)}
.hm-strip{display:flex;gap:12px;overflow-x:auto;padding:2px 2px 10px}
.hm-idx{flex:0 0 205px;background:#fff;border:1px solid var(--vr-line);border-radius:12px;padding:12px 14px;
  box-shadow:var(--vr-shadow)}
.hm-idx .n{font-size:.78rem;font-weight:700;letter-spacing:.03em;color:var(--vr-navy)}
.hm-idx .v{font-size:1.15rem;font-weight:800;color:var(--vr-ink);margin-top:4px}
.hm-idx .c{font-size:.82rem;font-weight:600}
.hm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(205px,1fr));gap:12px}
.hm-card{background:#fff;border:1px solid var(--vr-line);border-radius:12px;padding:12px 14px;box-shadow:var(--vr-shadow)}
.hm-card .logo{width:34px;height:34px;border-radius:9px;display:flex;align-items:center;justify-content:center;
  font-weight:800;font-size:.8rem;color:#fff;background:var(--vr-blue)}
.hm-card .nm{font-weight:700;color:var(--vr-ink);font-size:.9rem;margin-top:8px;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.hm-card .sy{font-size:.72rem;color:var(--vr-muted)}
.hm-card .p{font-size:1.02rem;font-weight:800;margin-top:6px;color:var(--vr-ink)}
.hm-card .c{font-size:.8rem;font-weight:600}
.hm-card .x{font-size:.72rem;color:var(--vr-muted);margin-top:2px}
.hm-up{color:#12783C}.hm-dn{color:#C62828}.hm-fl{color:#595959}
.hm-tbl{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--vr-line);border-radius:12px;
  overflow:hidden;font-size:.88rem}
.hm-tbl th{background:var(--vr-cream);color:var(--vr-muted);font-weight:600;text-align:right;padding:9px 12px;
  border-bottom:1px solid var(--vr-line)}
.hm-tbl th:first-child,.hm-tbl td:first-child{text-align:left}
.hm-tbl td{padding:9px 12px;border-bottom:1px solid var(--vr-line-2);text-align:right}
.hm-tbl td .sub{display:block;font-size:.72rem;color:var(--vr-muted)}
.hm-sec{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.hm-sec div{border-radius:10px;padding:10px 12px;font-weight:700;font-size:.86rem;color:var(--vr-ink)}
.hm-sec div span{display:block;font-size:.95rem;margin-top:3px}
.hm-stat{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed var(--vr-line);font-size:.88rem}
.hm-stat b{color:var(--vr-ink)}
.hm-bar{display:flex;height:9px;border-radius:6px;overflow:hidden;margin:8px 0 4px}
.hm-wl{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px dashed var(--vr-line)}
.hm-wl .nm{font-weight:600;font-size:.88rem}
.tk-wrap{overflow:hidden;white-space:nowrap;background:#0F1B2D;border-radius:8px;margin:6px 0 14px;
  border:1px solid #1E2B40;position:relative}
.tk-track{display:inline-flex;gap:28px;padding:8px 0;animation:tk-move var(--tk-speed,180s) linear infinite}
.tk-wrap:hover .tk-track{animation-play-state:paused}
.tk-item{display:inline-flex;gap:8px;font-size:.86rem;font-weight:600;color:#E8EDF5;align-items:baseline}
.tk-item .v{color:#C9D3E3;font-weight:500}
.tk-item .u{color:#2ECC71}.tk-item .d{color:#FF5C5C}.tk-sep{color:#3A4A63}
@keyframes tk-move{from{transform:translateX(0)}to{transform:translateX(-50%)}}
/* bottom of Home: the right column (watchlist + news) ends exactly where "Sectors today" ends */
@media (min-width: 768px){
  .st-key-hm_bottom [data-testid="stHorizontalBlock"]{align-items:stretch !important}
  .st-key-hm_bottom [data-testid="stColumn"]:has(.st-key-hm_side){position:relative;align-self:stretch !important}
  .st-key-hm_side{position:absolute !important;inset:0;overflow-y:auto;overflow-x:hidden;padding-right:4px;
    display:flex !important;flex-direction:column}
  /* the news card grows to the bottom of the column; "All market news" sits at its foot */
  .st-key-hm_side div:has(.st-key-hm_news){display:flex !important;flex-direction:column;flex:1 1 auto}
  .st-key-hm_news{flex:1 1 auto}
  .st-key-hm_news > :last-child{margin-top:auto}
}
.gen-title{font-size:1.15rem;font-weight:800;color:var(--vr-navy);margin-bottom:2px}
.gen-sub{font-size:.86rem;color:var(--vr-muted);margin-bottom:8px}
</style>
"""


# ------------------------------------------------------------------ cached data
@st.cache_data(ttl=240, show_spinner=False)
def _overview() -> dict:
    return HD.market_overview()


@st.cache_data(ttl=240, show_spinner=False)
def _stocks(extra: tuple[str, ...]) -> dict:
    return HD.stocks_overview(extra)


@st.cache_data(ttl=240, show_spinner=False)
def _world() -> list[dict]:
    return HD.world_quotes()


def _extra_symbols() -> tuple[str, ...]:
    """Popular and watchlist companies, priced together with the NIFTY 100 (one download for all pages)."""
    extra = {p["nse_symbol"] for p in _popular() if p.get("nse_symbol")}
    uid = (st.session_state.get("user") or {}).get("id")
    try:
        extra |= {w["nse_symbol"] for w in (repo.list_watchlist(uid) if uid else []) if w.get("nse_symbol")}
    except Exception:  # noqa: BLE001
        pass
    return tuple(sorted(extra))


REFRESH_SECONDS = 300   # market data on Home and the ticker reload themselves every 5 minutes


@st.fragment(run_every=REFRESH_SECONDS)
def ticker_tape() -> None:
    """Thin, continuously scrolling line of live prices (shown under the top bar on every page)."""
    st.markdown(CSS, unsafe_allow_html=True)
    try:
        items = HD.ticker_items(_overview(), _stocks(_extra_symbols())["stocks"], _world())
    except Exception:  # noqa: BLE001
        items = []
    if not items:
        return
    parts = []
    for i in items:
        p = i.get("change_pct")
        cls, arrow = ("u", "▲") if (p or 0) >= 0 else ("d", "▼")
        pct = f'<span class="{cls}">{arrow} {abs(p):.2f}%</span>' if p is not None else ""
        parts.append(f'<span class="tk-item">{e(i["name"])} <span class="v">{_num(i["last"])}</span> {pct}</span>'
                     '<span class="tk-sep">•</span>')
    row = "".join(parts)
    speed = max(60, len(items) * 3)      # seconds for one full loop: about 3 s per item
    st.html(f'<div class="tk-wrap"><div class="tk-track" style="--tk-speed:{speed}s">{row}{row}</div></div>')


@st.cache_data(ttl=120, show_spinner=False)
def _history(ticker: str, rng: str) -> list[dict]:
    return HD.index_history(ticker, rng)


@st.cache_data(ttl=600, show_spinner=False)
def _news() -> dict:
    from analysis.news import fetch_market_news

    return fetch_market_news(days=2)


@st.cache_data(ttl=600, show_spinner=False)
def _popular() -> list[dict]:
    try:
        return repo.popular_companies()
    except Exception:  # noqa: BLE001
        return []


# ------------------------------------------------------------------ small html helpers
def _cls(v: Optional[float]) -> str:
    return "hm-fl" if v is None or abs(v) < 1e-9 else ("hm-up" if v > 0 else "hm-dn")


def _num(v: Optional[float], nd: int = 2) -> str:
    return "–" if v is None else f"{v:,.{nd}f}"


def _chg(change: Optional[float], pct: Optional[float]) -> str:
    if pct is None:
        return "–"
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "")
    head = f"{change:+,.2f} " if change is not None else ""
    return f"{arrow} {head}({pct:+.2f}%)"


def _ist(iso: Optional[str]) -> str:
    """'12 Nov 2026, 02:35 PM IST' from a UTC ISO timestamp."""
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        ts = datetime.now(IST)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


def _cr(v: Optional[float]) -> str:
    if not v:
        return "–"
    return f"₹{v / 1e5:,.2f} L Cr" if v >= 1e5 else f"₹{v:,.0f} Cr"


def spark_svg(values: list[float], w: int = 120, h: int = 36, color: Optional[str] = None) -> str:
    vals = [v for v in values or [] if v is not None]
    if len(vals) < 2:
        return f'<svg width="{w}" height="{h}"></svg>'
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    pts = " ".join(f"{i * (w - 2) / (len(vals) - 1) + 1:.1f},{h - 2 - (v - lo) / span * (h - 4):.1f}"
                   for i, v in enumerate(vals))
    col = color or (UP if vals[-1] >= vals[0] else DOWN)
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><polyline fill="none" stroke="{col}" '
            f'stroke-width="1.6" stroke-linejoin="round" points="{pts}"/></svg>')


def _initials(name: str) -> str:
    words = [w for w in (name or "?").replace("Ltd", "").replace(".", " ").split() if w[:1].isalpha()]
    return "".join(w[0] for w in words[:2]).upper() or "?"


_LOGO_COLORS = ["#1C4DA0", "#12783C", "#A86200", "#6A3FB5", "#00838F", "#C2185B", "#455A64", "#E65100"]


def _stock_card(r: dict, extra: str = "") -> str:
    col = _LOGO_COLORS[sum(map(ord, r["symbol"])) % len(_LOGO_COLORS)]
    return f"""<div class="hm-card"><div style="display:flex;justify-content:space-between;align-items:center">
        <div class="logo" style="background:{col}">{e(_initials(r.get('name') or r['symbol']))}</div>
        {spark_svg(r.get('spark') or [], 90, 30)}</div>
      <div class="nm" title="{e(r.get('name'))}">{e(r.get('name') or r['symbol'])}</div>
      <div class="sy">{e(r['symbol'])}</div>
      <div class="p">₹{_num(r.get('price'))}</div>
      <div class="c {_cls(r.get('change_pct'))}">{_chg(r.get('change'), r.get('change_pct'))}</div>
      {f'<div class="x">{extra}</div>' if extra else ''}</div>"""


def _open_picker(rows: list[dict], key: str) -> None:
    """Pick a company shown above and open its Screener data or AI report."""
    known = repo.companies_by_symbols([r["symbol"] for r in rows])
    opts = [r["symbol"] for r in rows if r["symbol"] in known]
    if not opts:
        return
    a, b, c = st.columns([3, 1.2, 1.2], vertical_alignment="bottom")
    sym = a.selectbox("Open a company from this list", opts, key=f"pick_{key}",
                      format_func=lambda s: f"{known[s]['name']} · {s}")
    if b.button("📊 Screener data", key=f"scr_{key}", use_container_width=True):
        go_to(known[sym]["id"], "data")
    if c.button("🤖 AI report", key=f"ai_{key}", type="primary", use_container_width=True):
        go_to(known[sym]["id"], "report")


# ------------------------------------------------------------------ sections
def _index_strip(ov: dict) -> None:
    cards = []
    for r in ov["indices"]:
        cards.append(f"""<div class="hm-idx"><div class="n">{e(r['name'])}</div>
            <div class="v">{_num(r.get('last'))}</div>
            <div class="c {_cls(r.get('change_pct'))}">{_chg(r.get('change'), r.get('change_pct'))}</div>
            <div style="margin-top:6px">{spark_svg(r.get('spark') or [], 175, 38)}</div></div>""")
    if cards:
        st.html(f'<div class="hm-strip">{"".join(cards)}</div>')
    else:
        C.empty_state("Index data is not available right now", "It will load again automatically in a few minutes.")


def _breaks(rng: str) -> list:
    """Hide weekends (and nights for the 1-week intraday chart) so the line has no flat gaps."""
    if rng == "1D":
        return []
    out = [dict(bounds=["sat", "mon"])]
    if rng == "1W":
        out.append(dict(bounds=[15.5, 9.25], pattern="hour"))
    return out


def _index_chart(ov: dict) -> None:
    names = [r["name"] for r in ov["indices"]] or [n for n, _, _ in HD.INDICES]
    by_name = {r["name"]: r for r in ov["indices"]}
    tickers = {n: t for n, t, _ in HD.INDICES}
    left, right = st.columns([2.3, 1], gap="large")
    with left:
        with st.container(border=True):
            idx = C.tabbar("Index", names, key="hm_idx", default=names[0])
            rng = C.tabbar("Range", list(HD.RANGES), key="hm_rng", default="1D")
            pts = _history(tickers[idx], rng)
            q = by_name.get(idx, {})
            if pts:
                first, last = pts[0]["close"], pts[-1]["close"]
                ref = q.get("prev_close") if rng == "1D" and q.get("prev_close") else first
                ch = last - ref
                col = UP if ch >= 0 else DOWN
                st.html(f'<div style="display:flex;gap:14px;align-items:baseline"><span style="font-size:1.6rem;'
                        f'font-weight:800;color:var(--vr-ink)">{_num(q.get("last") or last)}</span>'
                        f'<span class="{_cls(ch)}" style="font-weight:700">{_chg(ch, ch / ref * 100 if ref else None)}'
                        f'</span><span style="color:var(--vr-muted);font-size:.85rem">{e(rng)}</span></div>')
                fig = go.Figure(go.Scatter(
                    x=[p["t"] for p in pts], y=[p["close"] for p in pts], mode="lines",
                    line=dict(color=col, width=2), fill="tozeroy",
                    fillcolor=("rgba(18,120,60,.08)" if ch >= 0 else "rgba(198,40,40,.08)"),
                    hovertemplate="%{x}<br>%{y:,.2f}<extra></extra>"))
                if rng == "1D" and q.get("prev_close"):
                    fig.add_hline(y=q["prev_close"], line_dash="dot", line_color="#9AA3AF",
                                  annotation_text="prev. close", annotation_font_size=10)
                ys = [p["close"] for p in pts]
                pad = (max(ys) - min(ys)) * 0.08 or max(ys) * 0.002
                fig.update_layout(height=320, margin=dict(l=8, r=8, t=8, b=8), plot_bgcolor="white",
                                  showlegend=False, hovermode="x unified",
                                  yaxis=dict(range=[min(ys + [ref]) - pad, max(ys + [ref]) + pad],
                                             gridcolor="#F0ECE6", side="right"),
                                  xaxis=dict(showgrid=False, rangebreaks=_breaks(rng)))
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("Chart data is not available for this index right now.")
    with right:
        with st.container(border=True):
            q = by_name.get(idx, {})
            st.html(f'<div style="font-weight:800;color:var(--vr-navy);margin-bottom:6px">{e(idx)} · today</div>')
            stats = [("Open", q.get("open")), ("High", q.get("high")), ("Low", q.get("low")),
                     ("Previous close", q.get("prev_close")), ("52-week high", q.get("year_high")),
                     ("52-week low", q.get("year_low"))]
            st.html("".join(f'<div class="hm-stat"><span>{k}</span><b>{_num(v)}</b></div>' for k, v in stats
                            if v is not None) or '<div class="hm-stat"><span>Day figures</span><b>–</b></div>')
            br = ov.get("breadth")
            if br:
                tot = (br["advances"] + br["declines"] + br["unchanged"]) or 1
                st.html(f"""<div style="margin-top:12px;font-weight:700;color:var(--vr-navy)">Market breadth ·
                    {e(br['index'])}</div><div class="hm-bar">
                    <div style="width:{br['advances'] / tot * 100:.1f}%;background:{UP}"></div>
                    <div style="width:{br['unchanged'] / tot * 100:.1f}%;background:#C9CED6"></div>
                    <div style="width:{br['declines'] / tot * 100:.1f}%;background:{DOWN}"></div></div>
                    <div style="display:flex;justify-content:space-between;font-size:.8rem">
                    <span class="hm-up">{br['advances']:.0f} rising</span>
                    <span class="hm-dn">{br['declines']:.0f} falling</span></div>""")


def _popular_section(st_data: dict) -> None:
    pop = _popular()
    rows = []
    by_sym = {r["symbol"]: r for r in st_data["stocks"]}
    for p in pop:
        r = by_sym.get(p["nse_symbol"]) or st_data["extra"].get(p["nse_symbol"])
        if r and r.get("price") is not None:
            rows.append({**r, "name": p["name"], "views": p["n"]})
    title, sub = "Popular on Stock Insight Studio", "most opened and analysed in the last 30 days"
    if len(rows) < 4:   # new installation: show the most traded large companies instead
        rows = HD.lists_from(st_data["stocks"], 8)["traded"]
        title, sub = "Most traded today", "NIFTY 100 companies with the highest traded value"
    rows = rows[:8]
    if not rows:
        return
    st.html(f'<div class="hm-h">{title}<small>{sub}</small></div>'
            f'<div class="hm-grid">{"".join(_stock_card(r) for r in rows)}</div>')


MOVER_TABS = {"gainers": "Top gainers", "losers": "Top losers", "volume": "Volume shockers",
              "traded": "Most traded", "high52": "Near 52-week high", "low52": "Near 52-week low"}


def _movers(lists: dict) -> None:
    st.html('<div class="hm-h">Top movers today<small>NIFTY 100 companies</small></div>')
    kind = C.tabbar("Movers", list(MOVER_TABS), key="hm_mv", default="gainers", format_func=MOVER_TABS.get)
    rows = lists.get(kind) or []
    if not rows:
        st.caption("No companies in this list right now.")
        return

    def extra(r: dict) -> str:
        if kind == "volume" and r.get("vol_ratio"):
            return f"Volume {r['vol_ratio']:.1f}× the 20-day average"
        if kind == "traded" and r.get("value"):
            return f"Traded value {_cr(r['value'] / 1e7)}"
        if kind == "high52" and r.get("year_high"):
            return f"52-week high ₹{_num(r['year_high'])}"
        if kind == "low52" and r.get("year_low"):
            return f"52-week low ₹{_num(r['year_low'])}"
        return e(r.get("industry") or "")

    st.html(f'<div class="hm-grid">{"".join(_stock_card(r, extra(r)) for r in rows[:10])}</div>')


def _market_cap(lists: dict) -> None:
    rows = lists.get("mcap") or []
    if not rows:
        return
    kind = "free-float " if rows[0].get("mcap_kind") == "free-float" else ""
    st.html(f'<div class="hm-h">Top companies by market cap<small>{kind}market capitalisation</small></div>')
    body = "".join(f"""<tr><td><b>{i}. {e(r.get('name') or r['symbol'])}</b><span class="sub">{e(r['symbol'])}
        {(' · ' + e(r['industry'])) if r.get('industry') else ''}</span></td>
        <td>{spark_svg(r.get('spark') or [], 100, 28)}</td>
        <td><b>₹{_num(r.get('price'))}</b></td>
        <td class="{_cls(r.get('change_pct'))}">{('%+.2f%%' % r['change_pct']) if r.get('change_pct') is not None else '–'}</td>
        <td>{_cr(r.get('mcap_cr'))}</td></tr>""" for i, r in enumerate(rows, 1))
    st.html(f'<table class="hm-tbl"><tr><th>Company</th><th>1 month</th><th>Price</th><th>Today</th>'
            f'<th>Market cap</th></tr>{body}</table>')


def _sectors(ov: dict, stocks: list[dict]) -> None:
    rows = [(r["name"], r.get("change_pct")) for r in ov.get("sectors", [])]
    sub = "sector indices"
    if not rows:
        rows = [(r["industry"], r["change_pct"]) for r in HD.sector_breakdown(stocks)]
        sub = "average move of NIFTY 100 companies per industry"
    if not rows:
        return

    def bg(p: Optional[float]) -> str:
        if p is None:
            return "#F3F4F6"
        a = min(abs(p) / 3, 1) * 0.35 + 0.08
        return f"rgba(18,120,60,{a:.2f})" if p >= 0 else f"rgba(198,40,40,{a:.2f})"

    tiles = "".join(f'<div style="background:{bg(p)}">{e(n)}<span class="{_cls(p)}">'
                    f'{("%+.2f%%" % p) if p is not None else "–"}</span></div>' for n, p in rows)
    st.html(f'<div class="hm-h">Sectors today<small>{sub}</small></div><div class="hm-sec">{tiles}</div>')


def _watchlist(st_data: dict) -> None:
    uid = (st.session_state.get("user") or {}).get("id")
    try:
        wl = repo.list_watchlist(uid) if uid else []
    except Exception:  # noqa: BLE001
        wl = []
    with st.container(border=True):
        C.subheading("Your watchlist", color="green")
        if not wl:
            st.caption("No companies in your watchlist yet.")
            return
        by_sym = {r["symbol"]: r for r in st_data["stocks"]}
        html = []
        for w in wl[:10]:
            r = by_sym.get(w.get("nse_symbol") or "") or st_data["extra"].get(w.get("nse_symbol") or "") or {}
            html.append(f"""<div class="hm-wl"><div><div class="nm">{e(w['name'])}</div>
                <div style="font-size:.72rem;color:var(--vr-muted)">{e(w.get('nse_symbol') or '')}</div></div>
                <div style="text-align:right"><b>₹{_num(r.get('price'))}</b><div class="{_cls(r.get('change_pct'))}"
                style="font-size:.78rem">{('%+.2f%%' % r['change_pct']) if r.get('change_pct') is not None else ''}
                </div></div></div>""")
        st.html("".join(html))


def _news_box() -> None:
    with st.container(border=True, key="hm_news"):
        C.subheading("Market news")
        try:
            items = _news().get("items", [])[:6]
        except Exception:  # noqa: BLE001
            items = []
        if items:
            C.news_list(items)
        else:
            st.caption("Headlines are not available right now.")
        if st.button("All market news →", key="hm_news", use_container_width=True):
            st.session_state["nav_request"] = "Market News"
            st.rerun()


# ------------------------------------------------------------------ generate box
def go_to(company_id: int, kind: str) -> None:
    """Open the Screener data page, or generate an AI report (Plans page first if the user has no access)."""
    from core import billing
    from ui.company_view import set_company

    set_company(repo.get_company(company_id))
    if kind == "data":
        st.session_state["screener_request"] = company_id
        st.session_state["nav_request"] = "Screener Data"
    else:
        access = billing.access_for(st.session_state["user"]["id"])
        if not access.can_generate:      # stay on Home and open the plans popup
            st.session_state["plans_popup"] = access.message if "limit" in access.message.lower() else \
                "Your free report is used. Choose a plan to generate your next report."
            st.session_state["nav_request"] = "Home"
        else:
            st.session_state["report_request"] = company_id
            st.session_state["nav_request"] = "AI Analysis Report"
    st.rerun()


def _generate_box() -> None:
    from ui.company_view import cached_companies

    companies = cached_companies()
    labels = {c["id"]: f"{c['name']}  ·  {c['nse_symbol'] or c['screener_slug']}" for c in companies}
    with st.container(border=True):
        st.html('<div class="gen-title">Generate data and AI analysis report</div>'
                '<div class="gen-sub">Type a company name, then choose what you want.</div>')
        cid = st.selectbox("Company", [c["id"] for c in companies], index=None, key="home_company",
                           format_func=lambda i: labels.get(i, i), label_visibility="collapsed",
                           placeholder=f"🔍  Type a company name or NSE symbol ({len(companies):,} companies)")
        a, b = st.columns(2, gap="medium")
        go_data = a.button("📊  Generate company data", key="gen_data", use_container_width=True, disabled=not cid)
        go_report = b.button("🤖  Generate AI analysis report", key="gen_report", type="primary",
                             use_container_width=True, disabled=not cid)
        if not companies:
            st.warning("The company list is empty. Open **Profile → System status** and load the NSE list.")
    if go_data or go_report:
        go_to(cid, "data" if go_data else "report")


# ------------------------------------------------------------------ page
def render() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    user = st.session_state.get("user") or {}
    if st.session_state.get("payment_ok"):
        st.success(f"Payment received. {st.session_state.pop('payment_ok')} is now active. "
                   "You can generate your report below.")
    _generate_box()
    popup = st.session_state.pop("plans_popup", None)
    if popup:
        from ui.plans_view import plans_dialog

        plans_dialog(popup)

    _market_sections()


@st.fragment(run_every=REFRESH_SECONDS)
def _market_sections() -> None:
    """Everything below the Generate box. Reloads itself every 5 minutes (no button needed)."""
    with st.spinner("Loading market data…"):
        ov = _overview()
    st.html('<div class="hm-h" style="margin-top:26px">Markets today'
            f'<small>Last updated: {_ist(ov.get("as_of"))}</small></div>')
    _index_strip(ov)
    _index_chart(ov)

    with st.spinner("Loading companies…"):
        st_data = _stocks(_extra_symbols())
    lists = HD.lists_from(st_data["stocks"], 10)

    _popular_section(st_data)
    _movers(lists)

    with st.container(key="hm_bottom"):
        left, right = st.columns([2.3, 1], gap="large")
        with left:
            _market_cap(lists)
            _sectors(ov, st_data["stocks"])
        with right:
            with st.container(key="hm_side"):     # same height as the left side (see CSS), news scrolls inside
                C.spacer(18)
                _watchlist(st_data)
                _news_box()

    for n in ov.get("notes", []) + st_data.get("notes", []):
        HD.log.info("home data note: %s", n)
    st.caption("Prices may be delayed by up to 15 minutes · for education, not investment advice.")
