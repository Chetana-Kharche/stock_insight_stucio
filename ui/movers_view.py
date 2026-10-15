"""Market Movers tab: today's top gainers, top losers, stocks at 52-week highs and most active stocks."""
from __future__ import annotations

import streamlit as st

from analysis.market import LISTS, market_movers
from core import repository as repo
from core.utils import fmt_num
from ui import components as C
from ui import html as H
from ui.company_view import open_company


@st.cache_data(ttl=300, show_spinner=False)
def cached_movers() -> dict:
    return market_movers()


def render() -> None:
    C.page_header("Market Movers", "Companies at the top of today's market: biggest gainers and losers, stocks "
                  "at a 52-week high, and the most traded.")
    a, b = st.columns([4, 1], vertical_alignment="bottom")
    with a:
        kind = C.tabbar("List", list(LISTS), key="mv_kind", default="gainers", format_func=LISTS.get)
    with b:
        if st.button("⟳ Refresh", use_container_width=True):
            cached_movers.clear()
    with st.spinner("Loading market data…"):
        data = cached_movers()
    rows = data["lists"].get(kind) or []
    if not rows:
        C.empty_state("No market data right now", "NSE and the Yahoo Finance fallback could not be reached. "
                      "Try Refresh in a minute.")
        for n in data.get("notes", []):
            st.caption(n)
        return

    known = repo.companies_by_symbols([r["symbol"] for r in rows])
    table = []
    for i, r in enumerate(rows, 1):
        name = r.get("name") or (known.get(r["symbol"]) or {}).get("name") or ""
        extra = ""
        if kind == "high52":
            hi = r.get("high_52w")
            extra = H.fmt_money(hi) if hi else "–"
        elif kind == "active":
            extra = fmt_num(r.get("volume")) if r.get("volume") else "–"
        else:
            extra = fmt_num(r.get("volume")) if r.get("volume") else "–"
        table.append([f"{i}. {r['symbol']}", name, H.fmt_money(r.get("price")), H.pct_cell(r.get("change_pct")), extra])
    last_col = "52-week high" if kind == "high52" else "Volume (shares)"
    C.unit("₹ per share", "change in % from the previous close")
    st.html(H.generic_table(["NSE symbol", "Company", "Price", "Change", last_col], table, raw_html_cols=(3,)))
    st.caption(f"Source: {data.get('source') or '–'} · loaded {str(data.get('as_of'))[:16].replace('T', ' ')} UTC")
    for n in data.get("notes", []):
        st.caption(n)

    openable = {r["symbol"]: known[r["symbol"]] for r in rows if r["symbol"] in known}
    if openable:
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        sym = c1.selectbox("Open a company from this list", list(openable),
                           format_func=lambda s: f"{s} · {openable[s]['name']}", key="mv_open_sel")
        if c2.button("Open company", type="primary", use_container_width=True):
            open_company(openable[sym]["id"])
            st.rerun()
