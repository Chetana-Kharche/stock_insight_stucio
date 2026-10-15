"""Portfolio tab: the user's own holdings and watchlist (stored in Supabase, nothing pre-filled)."""
from __future__ import annotations

from datetime import date
from typing import Optional

import streamlit as st

from core import repository as repo
from core.utils import fmt_num
from ui import charts_ui
from ui import components as C
from ui import html as H
from ui.company_view import cached_companies, open_company


def _uid() -> Optional[str]:
    return (st.session_state.get("user") or {}).get("id")


@st.cache_data(ttl=900, show_spinner=False)
def yahoo_prices(symbols: tuple[str, ...]) -> dict[str, dict]:
    """Latest daily close and previous close from Yahoo Finance (delayed). {} if unavailable."""
    if not symbols:
        return {}
    try:
        import yfinance as yf

        data = yf.download([f"{s}.NS" for s in symbols], period="7d", interval="1d", group_by="ticker",
                           auto_adjust=False, progress=False, threads=True)
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for s in symbols:
        try:
            try:
                df = data[f"{s}.NS"]
            except KeyError:
                df = data
            df = df.dropna(subset=["Close"])
            if len(df) >= 1:
                out[s] = {"close": float(df["Close"].iloc[-1]),
                          "prev_close": float(df["Close"].iloc[-2]) if len(df) > 1 else None,
                          "trade_date": str(df.index[-1])[:10], "source": "Yahoo Finance"}
        except (KeyError, AttributeError, IndexError):
            continue
    return out


def current_prices(rows: list[dict]) -> dict[int, dict]:
    """Price per company id: Yahoo Finance (delayed) if reachable, else the last Screener close stored."""
    syms = tuple(sorted({r["nse_symbol"] for r in rows if r.get("nse_symbol")}))
    yp = yahoo_prices(syms)
    stored = repo.last_closes([r["company_id"] for r in rows])
    out = {}
    for r in rows:
        p = yp.get(r.get("nse_symbol") or "")
        if p:
            out[r["company_id"]] = p
        elif r["company_id"] in stored:
            out[r["company_id"]] = {**stored[r["company_id"]], "source": "Screener (last stored close)"}
    return out


def _add_holding_form(uid: str) -> None:
    companies = cached_companies()
    labels = {c["id"]: f"{c['name']} · {c['nse_symbol'] or c['screener_slug']}" for c in companies}
    with st.form("add_holding", clear_on_submit=True, border=False):
        cid = st.selectbox("Company", [c["id"] for c in companies], index=None, format_func=lambda i: labels.get(i, i),
                           placeholder="Search a company…")
        a, b, c = st.columns(3)
        qty = a.number_input("Quantity (shares)", min_value=0.0, step=1.0, format="%.0f")
        price = b.number_input("Average buy price (₹)", min_value=0.0, step=1.0, format="%.2f")
        bdate = c.date_input("Buy date", value=date.today(), max_value=date.today())
        if st.form_submit_button("Add to portfolio", type="primary", use_container_width=True):
            if not cid or qty <= 0 or price <= 0:
                st.warning("Choose a company and enter a quantity and price above zero.")
            else:
                repo.add_holding(uid, cid, qty, price, bdate)
                repo.log_activity(uid, cid, f"Added {qty:,.0f} shares at ₹{price:,.2f} to portfolio")
                st.success("Added.")
                st.rerun()


def render() -> None:
    uid = _uid()
    C.page_header("Portfolio", "Your holdings and watchlist. Values use the latest available price.")
    try:
        holdings = repo.list_holdings(uid)
        watch = repo.list_watchlist(uid)
    except Exception as e:  # noqa: BLE001
        st.error(f"Portfolio tables are missing. Restart the app so it can create them, or run sql/schema.sql in the Supabase SQL Editor. ({e})")
        return

    top_l, top_r = st.columns([3, 1.2], vertical_alignment="bottom")
    with top_r:
        with st.popover("＋ Add holding", use_container_width=True):
            _add_holding_form(uid)
    with top_l:
        if st.button("⟳ Update prices", help="Prices come from Yahoo Finance (delayed); if it cannot be reached, "
                                              "the last Screener close stored for the company is used."):
            yahoo_prices.clear()

    prices = current_prices([{"company_id": h["company_id"], "nse_symbol": h["nse_symbol"]} for h in holdings] +
                            [{"company_id": w["company_id"], "nse_symbol": w["nse_symbol"]} for w in watch])

    C.section("Holdings")
    if not holdings:
        C.empty_state("No holdings yet", "Add the shares you own with “＋ Add holding”. Nothing is pre-filled.")
    else:
        rows, invested, value, priced = [], 0.0, 0.0, 0
        alloc_l, alloc_v = [], []
        for h in holdings:
            qty, avg = float(h["quantity"]), float(h["avg_price"])
            inv = qty * avg
            p = prices.get(h["company_id"])
            cur = p["close"] if p else None
            val = qty * cur if cur is not None else None
            pnl = (val - inv) if val is not None else None
            invested += inv
            if val is not None:
                value += val
                priced += 1
                alloc_l.append(h["nse_symbol"] or h["name"])
                alloc_v.append(val)
            rows.append([h["name"], h["nse_symbol"] or "", fmt_num(qty), H.fmt_money(avg), H.fmt_money(cur),
                         f"{p['source']} · {p['trade_date']}" if p else "no price yet", H.fmt_money(inv, 0),
                         H.fmt_money(val, 0),
                         (f'<td class="{"up" if pnl >= 0 else "dn"}">{"+" if pnl >= 0 else "−"}₹{fmt_num(abs(pnl), 0)}</td>'
                          if pnl is not None else "<td>–</td>"),
                         H.pct_cell((pnl / inv * 100) if pnl is not None and inv else None)])
        pnl_t = value - sum(float(h["quantity"]) * float(h["avg_price"]) for h in holdings
                            if prices.get(h["company_id"]))
        inv_priced = sum(float(h["quantity"]) * float(h["avg_price"]) for h in holdings if prices.get(h["company_id"]))
        C.tiles([("Invested", H.fmt_money(invested, 0), f"{len(holdings)} holding(s)", None),
                 ("Current value", H.fmt_money(value, 0), f"{priced} of {len(holdings)} priced", None),
                 ("Profit / loss", f"{'+' if pnl_t >= 0 else '−'}₹{fmt_num(abs(pnl_t), 0)}", "on priced holdings",
                  "up" if pnl_t >= 0 else "dn"),
                 ("Return", f"{(pnl_t / inv_priced * 100):+.2f}%" if inv_priced else "–", "on priced holdings",
                  "up" if pnl_t >= 0 else "dn")])
        C.spacer(4)
        a, b = st.columns([2.2, 1], gap="large")
        with a:
            C.unit("₹ (rupees)", "quantity in shares")
            st.html(H.generic_table(["Company", "NSE", "Qty", "Avg price", "Price", "Price source", "Invested",
                                     "Value", "P&L", "P&L %"], rows, raw_html_cols=(8, 9)))
            opts = {h["id"]: f"{h['name']} · {fmt_num(float(h['quantity']))} @ ₹{float(h['avg_price']):,.2f}" for h in holdings}
            c1, c2, c3 = st.columns([2.2, 1, 1], vertical_alignment="bottom")
            sel = c1.selectbox("Select a holding", list(opts), format_func=opts.get, key="hold_sel")
            if c2.button("Open company", use_container_width=True, key="hold_open"):
                h = next(x for x in holdings if x["id"] == sel)
                open_company(h["company_id"])
                st.rerun()
            if c3.button("Remove", use_container_width=True, key="hold_del"):
                h = next(x for x in holdings if x["id"] == sel)
                repo.delete_holding(uid, sel)
                repo.log_activity(uid, h["company_id"], "Removed a holding from portfolio")
                st.rerun()
        with b:
            if alloc_v:
                C.unit("% of current value")
                st.plotly_chart(charts_ui.allocation_donut(alloc_l, alloc_v), use_container_width=True)

    C.section("Watchlist", "Companies you follow (use ☆ Follow on any company page)", color="green")
    if not watch:
        st.caption("No companies followed yet.")
        return
    rows = []
    for w in watch:
        p = prices.get(w["company_id"])
        chg = ((p["close"] / p["prev_close"] - 1) * 100) if p and p.get("prev_close") else None
        rows.append([w["name"], w["nse_symbol"] or "", w.get("industry") or "", H.fmt_money(p["close"] if p else None),
                     H.pct_cell(chg), f"{p['source']} · {p['trade_date']}" if p else "no price yet",
                     str(w["added_at"])[:10]])
    C.unit("₹ per share", "day change in %")
    st.html(H.generic_table(["Company", "NSE", "Industry", "Price", "Day change", "Price source", "Following since"],
                            rows, raw_html_cols=(4,)))
    opts = {w["company_id"]: w["name"] for w in watch}
    c1, c2, c3 = st.columns([2.2, 1, 1], vertical_alignment="bottom")
    sel = c1.selectbox("Select a company", list(opts), format_func=opts.get, key="wl_sel")
    if c2.button("Open company", use_container_width=True, key="wl_open"):
        open_company(sel)
        st.rerun()
    if c3.button("Unfollow", use_container_width=True, key="wl_del"):
        repo.remove_from_watchlist(uid, sel)
        repo.log_activity(uid, sel, "Removed from watchlist")
        st.rerun()
