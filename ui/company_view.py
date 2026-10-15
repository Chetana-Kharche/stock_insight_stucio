"""Stocks tab: find a company, then a Screener-style company page with sub-tabs.

Screener.in is the source of every table here. The "Key Ratios" tab adds a separate block of figures that
Screener does not publish (Yahoo Finance, Value Research, Investing.com, Macrotrends), each with its source.
"""
from __future__ import annotations

import io
import json
from typing import Optional

import pandas as pd
import streamlit as st

from analysis.news import SOURCE_NAMES, ai_insights, filter_company_news, group_by_source, only_five_sources
from core import repository as repo
from core.config import get_settings
from core.services import fetch_and_store, refresh_news
from core.units import CRORE_HELP
from exports.pdf_screener import build_screener_pdf, payload_to_json_bytes
from rag.sync import sync_company_async
from scraper.parser import FIN_SECTIONS
from scraper.screener_client import CompanyNotFound, ScreenerClient, ScreenerError
from ui import charts_ui
from ui import components as C
from ui import html as H
from ui import report_view

CTABS = ["Overview", "Chart", "Key Ratios", "Peers", "Quarters", "Profit & Loss", "Balance Sheet", "Cash Flow",
         "Ratios", "Shareholding", "Documents"]
# The Analysis Report is opened with its own button (not a sub-tab); general news lives in the Market News tab and
# the company's news is part of the report.
REPORT = "Analysis Report"
SECTION_FOR_TAB = {"Quarters": "quarters", "Profit & Loss": "profit-loss", "Balance Sheet": "balance-sheet",
                   "Cash Flow": "cash-flow", "Ratios": "ratios"}
STATE_KEYS = ("payload", "run_id", "report", "report_id", "news", "rag_session_id", "autofetch_for", "co_view")


# ------------------------------------------------------------------ cached helpers
@st.cache_data(ttl=3600, show_spinner=False)
def cached_companies() -> list[dict]:
    return repo.list_companies()


@st.cache_data(ttl=600, show_spinner=False)
def screener_search(q: str) -> list[dict]:
    return ScreenerClient(delay=0.3).search(q)


@st.cache_data(show_spinner=False, max_entries=12)
def screener_pdf_bytes(run_id: int, breakdowns: bool) -> bytes:
    run = repo.get_run(run_id)
    return build_screener_pdf(run["payload"], with_breakdowns=breakdowns)


@st.cache_data(show_spinner=False, max_entries=12)
def excel_bytes(run_id: int) -> bytes:
    """Every Screener table of one capture, one sheet each (like Screener's Export to Excel)."""
    payload = repo.get_run(run_id)["payload"]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame([{"Ratio": r["name"], "Value": r["value_text"]} for r in payload.get("summary_ratios", [])]
                     ).to_excel(xw, sheet_name="Summary", index=False)
        for sid in FIN_SECTIONS:
            sec = payload.get("sections", {}).get(sid)
            if not sec:
                continue
            cols = [c["label"] for c in sec["columns"]]
            rows = []
            for r in sec["rows"]:
                rows.append([r["metric"]] + list(r["numbers"]))
                for sub, sv in (r.get("schedules") or {}).items():
                    rows.append(["   " + sub] + list(sv["numbers"]))
            pd.DataFrame(rows, columns=["Metric"] + cols).to_excel(xw, sheet_name=sec.get("title", sid)[:31], index=False)
        peers = payload.get("peers") or {}
        if peers.get("rows"):
            pd.DataFrame([{"Name": p["name"], **p["values"]} for p in peers["rows"]]).to_excel(
                xw, sheet_name="Peers", index=False)
        for key in ("quarterly", "yearly"):
            sec = (payload.get("shareholding") or {}).get(key)
            if sec:
                pd.DataFrame([[r["metric"]] + list(r["numbers"]) for r in sec["rows"]],
                             columns=["Holder"] + [c["label"] for c in sec["columns"]]).to_excel(
                    xw, sheet_name=f"Shareholding {key}"[:31], index=False)
    return buf.getvalue()


def _user_id() -> Optional[str]:
    return (st.session_state.get("user") or {}).get("id")


# ------------------------------------------------------------------ state helpers (used by other pages too)
def set_company(company: dict) -> None:
    prev = st.session_state.get("company")
    if not prev or prev["id"] != company["id"]:
        for k in STATE_KEYS:
            st.session_state.pop(k, None)
    st.session_state["company"] = company


def open_company(company_id: int, tab: str = "Overview") -> None:
    """Switch to the Stocks page showing this company (call from any page, then st.rerun())."""
    comp = repo.get_company(company_id)
    if comp:
        set_company(comp)
        st.session_state["nav_request"] = "Stocks"
        st.session_state["ctab_request"] = tab


def load_run_into_state(run_id: int) -> None:
    run = repo.get_run(run_id)
    if not run or not run.get("payload"):
        st.error("That capture has no stored data.")
        return
    set_company(repo.get_company(run["company_id"]))
    payload = run["payload"]
    payload["meta"]["run_id"] = run_id
    st.session_state["payload"] = payload
    st.session_state["run_id"] = run_id
    st.session_state["news"] = repo.list_news(run["company_id"])


def open_run(run_id: int) -> None:
    load_run_into_state(run_id)
    st.session_state["nav_request"] = "Stocks"
    st.session_state["ctab_request"] = "Overview"


def open_report(report_id: int) -> None:
    report_view.load_report_into_state(report_id)
    st.session_state["nav_request"] = "Stocks"
    st.session_state["ctab_request"] = "Analysis Report"


def do_fetch(company: dict, basis: str, breakdowns: bool = True) -> bool:
    with st.status(f"Fetching {company['name']} from Screener…", expanded=True) as status:
        bar = st.progress(0.0)
        line = st.empty()

        def prog(msg: str, frac: float):
            bar.progress(max(0.0, min(frac, 1.0)))
            line.caption(msg)

        try:
            run_id, payload = fetch_and_store(company, basis, _user_id(), include_schedules=breakdowns, progress=prog)
        except CompanyNotFound:
            status.update(label="Company page not found on Screener", state="error")
            st.error(f"Screener has no page for “{company.get('nse_symbol') or company.get('screener_slug')}”. "
                     "Try the Screener search below the search box.")
            return False
        except Exception as e:  # noqa: BLE001
            status.update(label="Fetch failed", state="error")
            st.error(f"{type(e).__name__}: {e}")
            return False
        line.caption("Fetching latest news (NSE + BSE filings and 11 news websites)…")
        try:
            news = refresh_news(company)
        except Exception:  # noqa: BLE001
            news = repo.list_news(company["id"])
        status.update(label=f"Stored {payload['meta'].get('facts_stored', 0):,} numbers (capture #{run_id})",
                      state="complete", expanded=False)
    st.session_state["company"] = repo.get_company(company["id"])
    st.session_state["payload"] = payload
    st.session_state["run_id"] = run_id
    st.session_state["news"] = news
    for k in ("report", "report_id"):
        st.session_state.pop(k, None)
    repo.log_activity(_user_id(), company["id"], f"Fetched data from Screener ({basis}, capture #{run_id})")
    sync_company_async(company["id"])
    return True


def ensure_payload(company: dict) -> Optional[dict]:
    """Use the stored capture if there is one; otherwise fetch from Screener once."""
    if st.session_state.get("payload"):
        return st.session_state["payload"]
    run = repo.latest_run(company["id"], st.session_state.get("basis", "consolidated")) or repo.latest_run(company["id"])
    if run:
        load_run_into_state(run["id"])
        rep = repo.latest_report(company["id"])
        if rep and rep.get("run_id") == run["id"]:
            st.session_state["report"], st.session_state["report_id"] = rep["report"], rep["id"]
        return st.session_state.get("payload")
    if st.session_state.get("autofetch_for") != company["id"]:
        st.session_state["autofetch_for"] = company["id"]
        if do_fetch(company, st.session_state.get("basis", "consolidated")):
            return st.session_state.get("payload")
    return None


# ------------------------------------------------------------------ search
def search_bar() -> None:
    companies = cached_companies()
    labels = {c["id"]: f"{c['name']}  ·  {c['nse_symbol'] or c['screener_slug']}" for c in companies}
    ids = [c["id"] for c in companies]

    def _picked():
        cid = st.session_state.get("stock_search")
        if cid:
            set_company(repo.get_company(cid))
            st.session_state["ctab"] = "Overview"
            st.session_state["stock_search"] = None

    with st.container(border=True):
        a, b = st.columns([4, 1.3], vertical_alignment="bottom")
        with a:
            st.selectbox("Search for a company", ids, index=None, format_func=lambda i: labels.get(i, i),
                         placeholder=f"🔍  Type a company name or NSE symbol ({len(ids):,} NSE companies)",
                         key="stock_search", on_change=_picked, label_visibility="collapsed")
        with b:
            with st.popover("Not in the list?", use_container_width=True):
                q = st.text_input("Search Screener by name or BSE code", key="scr_q", placeholder="e.g. 500180")
                if q.strip():
                    try:
                        results = screener_search(q.strip())
                    except ScreenerError as e:
                        results = []
                        st.error(f"Screener search failed: {e}")
                    for i, r in enumerate(results[:8]):
                        if st.button(f"{r['name']}  ({r['slug']})", key=f"scr_res_{i}", use_container_width=True):
                            comp = repo.add_company_from_search(r["slug"], r["name"], r.get("id"))
                            cached_companies.clear()
                            set_company(comp)
                            st.rerun()
                    if not results:
                        st.caption("No match on Screener.")
        if not companies:
            st.warning("The company list is empty. Open **Profile → System status** and load the NSE list.")


def landing() -> None:
    uid = _user_id()
    C.empty_state("Search any NSE company", "Pick a company above. Stored data opens instantly; a company you "
                  "have never opened is fetched from Screener automatically.",
                  [("Overview", "Price, ratios, about, pros and cons"),
                   ("Statements", "Quarters, P&L, balance sheet, cash flow, ratios"),
                   ("Key Ratios", "Screener ratios plus missing ones from other websites"),
                   ("Analysis Report", "Broker-style report with projections and news")])
    a, b = st.columns(2, gap="large")
    with a:
        C.subheading("Recently opened by you")
        recent = repo.recent_companies(uid) if uid else []
        if not recent:
            st.caption("Nothing yet.")
        for r in recent:
            if st.button(f"{r['name']} · {r['nse_symbol'] or ''}", key=f"rec_{r['id']}", use_container_width=True):
                open_company(r["id"])
                st.rerun()
    with b:
        C.subheading("Your watchlist", color="green")
        try:
            wl = repo.list_watchlist(uid) if uid else []
        except Exception:  # noqa: BLE001 - migration not run
            wl = []
        if not wl:
            st.caption("Follow a company with the ★ Follow button to see it here.")
        for w in wl:
            if st.button(f"★ {w['name']} · {w['nse_symbol'] or ''}", key=f"wl_{w['company_id']}", use_container_width=True):
                open_company(w["company_id"])
                st.rerun()


# ------------------------------------------------------------------ header + actions
def header_and_actions(company: dict, payload: Optional[dict]) -> None:
    uid = _user_id()
    closes = repo.last_closes([company["id"]]).get(company["id"])
    st.html(H.company_header(payload or {}, company, closes))
    try:
        following = bool(uid) and repo.is_in_watchlist(uid, company["id"])
    except Exception:  # noqa: BLE001 - tables not created yet
        following = None
    c1, c2, c3, c4, c5 = st.columns([1, 1, 1.2, 1.2, 1.1], vertical_alignment="center")
    with c1:
        if following is not None:
            if st.button("★ Following" if following else "☆ Follow", use_container_width=True,
                         type="secondary" if following else "primary"):
                if following:
                    repo.remove_from_watchlist(uid, company["id"])
                    repo.log_activity(uid, company["id"], "Removed from watchlist")
                else:
                    repo.add_to_watchlist(uid, company["id"])
                    repo.log_activity(uid, company["id"], "Added to watchlist")
                st.rerun()
    with c2:
        with st.popover("✎ Add note", use_container_width=True):
            with st.form("co_note", clear_on_submit=True, border=False):
                kind = st.selectbox("Type", ["text", "outlook", "action"],
                                    format_func={"text": "Text note", "outlook": "Outlook", "action": "Action"}.get)
                txt = st.text_area("Note", placeholder="Your view, a reminder, something to check…")
                if st.form_submit_button("Save note", type="primary", use_container_width=True) and txt.strip():
                    try:
                        repo.add_note(uid, company["id"], txt, kind)
                        st.success("Saved to your notebook.")
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Could not save the note ({e}). Restart the app so it can create the tables.")
    with c3:
        basis = st.selectbox("Basis", ["consolidated", "standalone"], key="basis", label_visibility="collapsed")
    with c4:
        if st.button("⟳ Refresh from Screener", use_container_width=True):
            if do_fetch(company, basis):
                st.rerun()
    with c5:
        run_id = st.session_state.get("run_id")
        with st.popover("⤓ Export", use_container_width=True, disabled=not payload):
            if payload:
                sym = payload["meta"].get("nse_symbol") or "company"
                st.download_button("Screener data · JSON", payload_to_json_bytes(payload),
                                   file_name=f"{sym}_screener_{run_id}.json", mime="application/json",
                                   use_container_width=True)
                try:
                    xls = excel_bytes(run_id)
                except ImportError:
                    xls = None
                if xls:
                    st.download_button("Screener data · Excel", xls, file_name=f"{sym}_screener_{run_id}.xlsx",
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                       use_container_width=True)
                else:
                    st.caption("Excel export needs the openpyxl package: run `pip install openpyxl` "
                               "in the project's virtual environment.")
                if st.button("Build PDF", use_container_width=True, key="build_scr_pdf"):
                    st.session_state["scr_pdf_for"] = run_id
                if st.session_state.get("scr_pdf_for") == run_id:
                    st.download_button("Download PDF", screener_pdf_bytes(run_id, True),
                                       file_name=f"{sym}_screener_{run_id}.pdf", mime="application/pdf",
                                       type="primary", use_container_width=True)
    if payload and basis != payload["meta"].get("basis"):
        st.caption(f"Showing the stored {payload['meta'].get('basis')} capture. Click “Refresh from Screener” to "
                   f"fetch {basis} figures.")


# ------------------------------------------------------------------ tabs
def tab_overview(payload: dict) -> None:
    st.html(H.ratio_box(payload))
    if payload.get("about") or payload.get("pros") or payload.get("cons"):
        a, b = st.columns([1.2, 1], gap="large")
        with a:
            with st.container(border=True):
                C.subheading("About")
                st.write(payload.get("about") or "–")
        with b:
            with st.container(border=True):
                C.subheading("Pros", color="green")
                C.bullet_list(payload.get("pros", []), "ok")
                C.subheading("Cons")
                C.bullet_list(payload.get("cons", []), "risk")
                st.caption("Pros and cons are machine generated by Screener.")
    fig = charts_ui.price_range_chart(payload.get("price_history") or [], "1Yr")
    if fig:
        C.unit(charts_ui.UNITS["price"], "price; volume in number of shares")
        st.plotly_chart(fig, use_container_width=True)
    if payload.get("growth"):
        C.subheading("Compounded growth and returns")
        C.unit_for("growth")
        st.html(H.growth_tables(payload["growth"]))


def tab_chart(payload: dict) -> None:
    a, b = st.columns([2, 1])
    with a:
        rng = C.tabbar("Period", list(charts_ui.RANGE_DAYS), key="chart_range", default="1Yr")
    with b:
        kind = C.tabbar("Chart", ["Price", "PE Ratio"], key="chart_kind", default="Price")
    if kind == "Price":
        fig = charts_ui.price_range_chart(payload.get("price_history") or [], rng)
        C.unit(charts_ui.UNITS["price"], "price; volume in number of shares")
    else:
        fig = charts_ui.pe_range_chart(payload.get("pe_history") or {}, rng)
        C.unit(charts_ui.UNITS["pe"])
    if fig:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Screener did not return chart data for this company.")


def tab_key_ratios(payload: dict, company: dict) -> None:
    from analysis.external import get_supplementary
    from analysis.metrics import compute_metrics
    from analysis.report import _key_ratio_table

    a, b = st.columns([1, 1.4], gap="large")
    with a:
        C.subheading("Screener ratios")
        rows = [[r["name"], r["value_text"], H.UNIT_LABEL.get(r["unit"], r["unit"])] for r in payload.get("summary_ratios", [])]
        st.html(H.generic_table(["Ratio", "Value", "Unit"], rows))
    with b:
        C.subheading("Calculated from Screener statements")
        kr = _key_ratio_table(payload)
        if kr.get("rows"):
            C.unit_for("key_ratios")
            st.html(H.simple_table(kr["columns"], kr["rows"]))
        else:
            st.caption("Not enough statement data to calculate.")

    C.section("From other websites", "Only figures Screener does not publish · NSE, Value Research Online, Yahoo "
              "Finance, Investing.com, Macrotrends · each value shows its source", color="green")
    if not get_settings().external_enabled:
        st.info("Other websites are switched off (EXTERNAL_SOURCES_ENABLED=false in .env).")
        return
    key = f"sup_{company['id']}"
    force = st.button("⟳ Look up again now", key="sup_refresh")
    if force or key not in st.session_state:
        with st.spinner("Reading NSE, Value Research and Yahoo Finance, then searching the other websites…"):
            m = compute_metrics(payload)
            st.session_state[key] = get_supplementary(payload, m, company["id"], use_ai=True, force=force)
    report_view.render_supplementary(st.session_state[key])
    sup = st.session_state[key]
    if sup.get("cached_at"):
        st.caption(f"Saved lookup from {str(sup['cached_at'])[:16]} UTC (refreshed at most once a day).")
    _vr_link_box(company, key)


def _vr_link_box(company: dict, sup_key: str) -> None:
    """Show which Value Research page is used, and let the user paste the right one."""
    from analysis.valueresearch import SITE, _canonical

    try:
        current = repo.get_link(company["id"], SITE)
    except Exception:  # noqa: BLE001
        current = None
    with st.expander("Value Research stock page used for this company"):
        if current:
            st.markdown(f"Using: [{current}]({current})")
        else:
            st.caption("Not found automatically yet. Open valueresearchonline.com, search the company, and paste "
                       "the address of its stock page here (it looks like valueresearchonline.com/stocks/12345/name/).")
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        with c1:
            pasted = st.text_input("Value Research stock page address", key=f"vr_url_{company['id']}",
                                   placeholder="https://www.valueresearchonline.com/stocks/…/…/")
        with c2:
            if st.button("Save", key=f"vr_save_{company['id']}", use_container_width=True):
                url = _canonical(pasted or "")
                if not url:
                    st.warning("That is not a Value Research stock page address.")
                else:
                    repo.save_link(company["id"], SITE, url, "user")
                    st.session_state.pop(sup_key, None)
                    st.success("Saved. Click “Look up again now” to read it.")


def tab_peers(payload: dict) -> None:
    peers = payload.get("peers") or {}
    if not peers.get("rows"):
        st.info("Screener did not return a peer list for this company.")
        return
    st.html(H.peers_card(peers, payload["meta"]))


def tab_section(payload: dict, tab: str) -> None:
    key = SECTION_FOR_TAB[tab]
    sec = payload.get("sections", {}).get(key)
    if not sec:
        st.info(f"Screener has no {tab} table for this company.")
        return
    show_bd = st.toggle("Show “+” breakdown rows", value=True, key=f"bd_{key}")
    if key == "quarters":
        fig = charts_ui.quarterly_chart(payload)
        if fig:
            C.unit(charts_ui.UNITS["quarterly"])
            st.plotly_chart(fig, use_container_width=True)
    if key == "profit-loss":
        fig = charts_ui.annual_chart(payload)
        if fig:
            C.unit(charts_ui.UNITS["annual"])
            st.plotly_chart(fig, use_container_width=True)
    st.caption(CRORE_HELP)
    st.html(H.section_card(sec, key, payload["meta"].get("basis", ""), show_bd))
    if key == "profit-loss" and payload.get("growth"):
        C.subheading("Compounded growth and returns")
        C.unit_for("growth")
        st.html(H.growth_tables(payload["growth"]))
    if key == "ratios":
        fig = charts_ui.returns_chart(payload)
        if fig:
            C.unit(charts_ui.UNITS["returns"])
            st.plotly_chart(fig, use_container_width=True)


def tab_shareholding(payload: dict) -> None:
    shp = payload.get("shareholding") or {}
    if not (shp.get("quarterly") or shp.get("yearly")):
        st.info("Screener has no shareholding data for this company.")
        return
    fig = charts_ui.shareholding_chart(payload)
    if fig:
        C.unit(charts_ui.UNITS["shareholding"])
        st.plotly_chart(fig, use_container_width=True)
    keys = [k for k in ("quarterly", "yearly") if shp.get(k)]
    for t, k in zip(st.tabs([k.title() for k in keys]), keys):
        with t:
            C.unit_for("shareholding")
            sec = shp[k]
            st.html(H.data_table([c["label"] for c in sec["columns"]], sec["rows"], False))
    if shp.get("note"):
        st.html(f'<div class="sis-note">{H.e(shp["note"])}</div>')


def tab_documents(payload: dict) -> None:
    docs = payload.get("documents") or {}
    if not any(docs.values()):
        st.info("Screener lists no documents for this company.")
        return
    st.html(H.documents_card(docs))


def tab_news(company: dict, payload: dict) -> None:
    cid = company["id"]
    news = st.session_state.get("news")
    if news is None:
        news = repo.list_news(cid)
    if not news and st.session_state.get(f"news_tried_{cid}") is None:
        st.session_state[f"news_tried_{cid}"] = True
        with st.spinner("Fetching news (NSE + BSE filings and 11 news websites)…"):
            try:
                news = refresh_news(company)
            except Exception as e:  # noqa: BLE001
                st.warning(f"News fetch failed: {e}")
    st.session_state["news"] = news
    news = filter_company_news(only_five_sources(news or []), company["name"], company.get("nse_symbol"))
    a, b = st.columns([3, 1], vertical_alignment="bottom")
    with a:
        C.section("Latest news", "Headlines about " + company["name"] + " from " + ", ".join(SOURCE_NAMES))
    with b:
        if st.button("⟳ Refresh news", use_container_width=True):
            with st.spinner("Fetching news…"):
                try:
                    st.session_state["news"] = refresh_news(company)
                    news = filter_company_news(only_five_sources(st.session_state["news"]), company["name"],
                                               company.get("nse_symbol"))
                    st.session_state.pop(f"insights_{cid}", None)
                    sync_company_async(cid)
                except Exception as e:  # noqa: BLE001
                    st.error(f"News fetch failed: {e}")
    left, right = st.columns([1.6, 1], gap="large")
    with left:
        if news:
            C.news_grouped(list(group_by_source(news).items()))
        else:
            C.empty_state("No recent headlines", "No headline naming this company was found on NSE, BSE or the news websites in "
                          "the last 90 days, or the sites could not be reached.")
    with right:
        with st.container(border=True):
            C.subheading("Key insights from the news")
            ins = st.session_state.get(f"insights_{cid}")
            if st.button("Summarise the news", type="primary", use_container_width=True, disabled=not news):
                with st.spinner("Reading the headlines…"):
                    pts, method = ai_insights(news, company["name"])
                st.session_state[f"insights_{cid}"] = ins = (pts, method)
            if ins:
                C.bullet_list(ins[0], "watch")
                st.caption(f"Written by: {ins[1]} · from headlines only")
            else:
                st.caption("Click to get 4–6 key points from these headlines.")
        anns = (payload.get("documents") or {}).get("announcements") or []
        if anns:
            with st.container(border=True):
                C.subheading("Exchange announcements", color="green")
                C.news_list([{"title": x.get("title"), "url": x.get("url"), "source": "NSE/BSE filing",
                              "published_at": x.get("date")} for x in anns[:8]])


# ------------------------------------------------------------------ page
def render() -> None:
    C.page_header("Stocks", "Company data from Screener.in, stored in your database · missing figures from other "
                  "websites · AI-assisted analysis report")
    search_bar()
    company = st.session_state.get("company")
    if not company:
        landing()
        return
    payload = ensure_payload(company)
    header_and_actions(company, payload)
    if not payload:
        C.empty_state(f"No data for {company['name']} yet", "Click “Refresh from Screener” to fetch it.")
        return
    for w in payload.get("warnings", []):
        st.warning(w)
    req = st.session_state.pop("ctab_request", None)
    if req == REPORT:
        st.session_state["co_view"] = "report"
    elif req:
        st.session_state["co_view"] = "data"
        st.session_state["ctab"] = req if req in CTABS else "Overview"

    if st.session_state.get("co_view") == "report":
        a, b = st.columns([5, 1.7], vertical_alignment="center")
        with a:
            st.html('<div class="vr-report-title">Analysis Report</div>')
        with b:
            if st.button("← Back to company data", key="back_data", use_container_width=True):
                st.session_state["co_view"] = "data"
                st.rerun()
        report_view.render_analysis(payload)
        return

    a, b = st.columns([5, 1.7], vertical_alignment="center")
    with b:
        if st.button("📊  Analysis Report", key="go_report", type="primary", use_container_width=True,
                     help="Scorecard, projections (incl. TimesFM), peers, data from other websites and news"):
            st.session_state["co_view"] = "report"
            st.rerun()
    with a:
        st.caption("Company data from Screener. Open the Analysis Report for the full broker-style report.")
    tab = C.tabbar("Section", CTABS, key="ctab", default="Overview")
    C.spacer(2)
    if tab == "Overview":
        tab_overview(payload)
    elif tab == "Chart":
        tab_chart(payload)
    elif tab == "Key Ratios":
        tab_key_ratios(payload, company)
    elif tab == "Peers":
        tab_peers(payload)
    elif tab in SECTION_FOR_TAB:
        tab_section(payload, tab)
    elif tab == "Shareholding":
        tab_shareholding(payload)
    elif tab == "Documents":
        tab_documents(payload)
    else:
        tab_overview(payload)
