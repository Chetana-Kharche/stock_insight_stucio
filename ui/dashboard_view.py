"""Page 2: company picker -> fetch -> Screener-style data view, analysis report, news."""
from __future__ import annotations

import json
from typing import Optional

import streamlit as st

from analysis.report import build_report
from core import repository as repo
from core.config import get_settings
from core.units import CRORE_HELP
from core.services import fetch_and_store, refresh_news
from exports.pdf_report import build_report_pdf
from exports.pdf_screener import build_screener_pdf, payload_to_json_bytes
from rag.sync import sync_company_async
from scraper.screener_client import CompanyNotFound, ScreenerClient, ScreenerError
from ui import charts_ui
from ui import components as C
from ui import html as H

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
def report_pdf_bytes(report_id: int) -> bytes:
    rep = repo.get_report(report_id)
    payload = None
    if rep.get("run_id"):
        run = repo.get_run(rep["run_id"])
        payload = run["payload"] if run else None
    return build_report_pdf(rep["report"], payload)


def _user_id() -> Optional[str]:
    return (st.session_state.get("user") or {}).get("id")


def _set_company(company: dict) -> None:
    prev = st.session_state.get("company")
    if not prev or prev["id"] != company["id"]:
        for k in ("payload", "run_id", "report", "report_id", "news", "rag_session_id"):
            st.session_state.pop(k, None)
    st.session_state["company"] = company


def load_run_into_state(run_id: int) -> None:
    run = repo.get_run(run_id)
    if not run or not run.get("payload"):
        st.error("That run has no stored data.")
        return
    _set_company(repo.get_company(run["company_id"]))
    payload = run["payload"]
    payload["meta"]["run_id"] = run_id
    st.session_state["payload"] = payload
    st.session_state["run_id"] = run_id
    st.session_state["news"] = repo.list_news(run["company_id"])


def load_report_into_state(report_id: int) -> None:
    rep = repo.get_report(report_id)
    if not rep:
        return
    if rep.get("run_id"):
        load_run_into_state(rep["run_id"])
    else:
        _set_company(repo.get_company(rep["company_id"]))
    st.session_state["report"] = rep["report"]
    st.session_state["report_id"] = report_id


# ------------------------------------------------------------------ picker
def company_picker() -> None:
    companies = cached_companies()
    labels = {c["id"]: f"{c['nse_symbol'] or c['screener_slug']} — {c['name']}" for c in companies}
    ids = [c["id"] for c in companies]
    current = st.session_state.get("company")
    idx = ids.index(current["id"]) if current and current["id"] in ids else None

    with st.container(border=True):
        C.section("Select a company", "Pick from the NSE list or type a symbol / name — then fetch live data "
                  "or open the last stored capture.", color="green", step=1)
        if not companies:
            st.warning("The company list is empty. Open **System status** in the sidebar and load the NSE list "
                       "(or run `python -m scripts.load_companies`).")
        c1, c2, c3 = st.columns([2.2, 1.6, 1], gap="medium")
        with c1:
            sel = st.selectbox("NSE company", ids, index=idx, format_func=lambda i: labels.get(i, i),
                               placeholder=f"Search {len(ids):,} companies…", key="picker_select")
        with c2:
            typed = st.text_input("Or type NSE symbol / company name", placeholder="e.g. HDFCBANK or Infosys",
                                  key="picker_text")
        with c3:
            basis = st.selectbox("Statement basis", ["consolidated", "standalone"], key="basis")

        company = None
        if typed.strip():
            company = repo.find_company(typed.strip())
            if company is None:
                try:
                    results = screener_search(typed.strip())
                except ScreenerError as e:
                    results = []
                    st.error(f"Screener search failed: {e}")
                if results:
                    s1, s2 = st.columns([3, 1], vertical_alignment="bottom")
                    with s1:
                        pick = st.selectbox("Matches on Screener", range(len(results)),
                                            format_func=lambda i: f"{results[i]['name']}  ({results[i]['slug']})",
                                            key="picker_search")
                    with s2:
                        use = st.button("Use this company", use_container_width=True)
                    if use:
                        r = results[pick]
                        company = repo.add_company_from_search(r["slug"], r["name"], r.get("id"))
                        cached_companies.clear()
                        _set_company(company)
                        st.rerun()
                else:
                    st.info("No match in the NSE list or on Screener.")
        elif sel is not None:
            company = repo.get_company(sel)

        if company:
            _set_company(company)

        C.spacer(4)
        b1, b2, b3 = st.columns([1.3, 1, 2.7], vertical_alignment="center")
        with b1:
            fetch = st.button("Fetch from Screener", type="primary", use_container_width=True,
                              disabled=st.session_state.get("company") is None)
        with b2:
            load = st.button("Load stored", use_container_width=True,
                             disabled=st.session_state.get("company") is None)
        with b3:
            breakdowns = st.checkbox("Include “+” breakdown rows (slower, more data)", value=True,
                                     key="with_breakdowns")

    if fetch and st.session_state.get("company"):
        do_fetch(st.session_state["company"], basis, breakdowns)
    if load and st.session_state.get("company"):
        run = repo.latest_run(st.session_state["company"]["id"], basis) or repo.latest_run(st.session_state["company"]["id"])
        if run:
            load_run_into_state(run["id"])
            rep = repo.latest_report(st.session_state["company"]["id"])
            if rep:
                st.session_state["report"], st.session_state["report_id"] = rep["report"], rep["id"]
        else:
            st.info("Nothing stored yet for this company — click **Fetch from Screener**.")


def do_fetch(company: dict, basis: str, breakdowns: bool) -> None:
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
                     "Try the text box to search by name.")
            return
        except Exception as e:  # noqa: BLE001
            status.update(label="Fetch failed", state="error")
            st.error(f"{type(e).__name__}: {e}")
            return
        line.caption("Fetching latest news…")
        try:
            news = refresh_news(company)
        except Exception:  # noqa: BLE001
            news = repo.list_news(company["id"])
        status.update(label=f"Stored {payload['meta'].get('facts_stored', 0):,} facts (run #{run_id})",
                      state="complete", expanded=False)
    st.session_state["company"] = repo.get_company(company["id"])
    st.session_state["payload"] = payload
    st.session_state["run_id"] = run_id
    st.session_state["news"] = news
    for k in ("report", "report_id"):
        st.session_state.pop(k, None)
    sync_company_async(company["id"])


# ------------------------------------------------------------------ small layout helpers
def _export_bar(json_bytes: bytes, json_name: str, prep_key: str, state_key: str, ident, pdf_fn, pdf_name: str) -> None:
    with st.container(border=True):
        a, b, c, d = st.columns([2.2, 1, 1, 1.2], vertical_alignment="center")
        with a:
            st.html('<div style="font-weight:700;color:#0B3C5D">Export</div>'
                    '<div style="font-size:.8rem;color:#64748B">Download this view as JSON or a formatted PDF</div>')
        with b:
            st.download_button("JSON", json_bytes, file_name=json_name, mime="application/json",
                               use_container_width=True)
        with c:
            if st.button("Prepare PDF", use_container_width=True, key=prep_key):
                st.session_state[state_key] = ident
        with d:
            if ident and st.session_state.get(state_key) == ident:
                with st.spinner("Building PDF…"):
                    data = pdf_fn()
                st.download_button("Download PDF", data, file_name=pdf_name, mime="application/pdf",
                                   type="primary", use_container_width=True)
            else:
                st.caption("Click “Prepare PDF” first")


# ------------------------------------------------------------------ screener view
def render_screener(payload: dict) -> None:
    run_id = st.session_state.get("run_id")
    meta = payload["meta"]
    sym = meta.get("nse_symbol") or meta.get("screener_slug") or "company"

    _export_bar(payload_to_json_bytes(payload), f"{sym}_screener_{run_id}.json", "prep_scr_pdf", "scr_pdf_for",
                run_id, lambda: screener_pdf_bytes(run_id, st.session_state.get("with_breakdowns", True)),
                f"{sym}_screener_{run_id}.pdf")

    for w in payload.get("warnings", []):
        st.warning(w)

    C.section("Company overview", "Identity, classification and capture details")
    st.html(H.header_card(payload, {"id": run_id}))

    C.section("Summary ratios", "Key valuation and return metrics as shown on Screener", color="green")
    st.html(H.ratio_grid(payload))

    if payload.get("about") or payload.get("pros") or payload.get("cons"):
        C.section("About the company", "Business description and Screener's machine-generated pros & cons")
        with st.container(border=True):
            a, b = st.columns([1.3, 1], gap="large")
            with a:
                C.subheading("About")
                st.write(payload.get("about") or "–")
            with b:
                C.subheading("Pros", color="green")
                C.bullet_list(payload.get("pros", []), "ok")
                C.subheading("Cons")
                C.bullet_list(payload.get("cons", []), "risk")
                st.caption("Pros/cons are machine generated by Screener.")

    fig = charts_ui.price_chart(payload.get("price_history") or [])
    if fig:
        C.section("Price chart", "Five-year share price with 50 and 200-day moving averages", color="green")
        C.unit(charts_ui.UNITS["price"])
        st.plotly_chart(fig, use_container_width=True)

    if (payload.get("peers") or {}).get("rows"):
        C.section("Peer comparison", "Companies in the same industry, as listed by Screener")
        st.html(H.peers_card(payload.get("peers") or {}, meta))

    C.section("Financial statements", "The unit is shown above each table · rows marked + have breakdowns",
              color="green")
    st.caption(CRORE_HELP)
    show_bd = st.toggle("Show “+” breakdown rows", value=True, key="show_bd")
    for key in ("quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios"):
        sec = payload.get("sections", {}).get(key)
        if not sec:
            continue
        st.html(H.section_card(sec, key, meta.get("basis", ""), show_bd))
        if key == "profit-loss" and payload.get("growth"):
            C.subheading("Compounded growth & returns", color="green")
            C.unit_for("growth")
            st.html(H.growth_tables(payload["growth"]))
            C.spacer(10)

    shp = payload.get("shareholding") or {}
    if shp.get("quarterly") or shp.get("yearly"):
        C.section("Shareholding pattern", "Percentage of shares held by each investor group")
        with st.container(border=True):
            C.unit_for("shareholding")
            keys = [k for k in ("quarterly", "yearly") if shp.get(k)]
            for t, k in zip(st.tabs([k.title() for k in keys]), keys):
                with t:
                    sec = shp[k]
                    st.html(H.data_table([c["label"] for c in sec["columns"]], sec["rows"], False))
            if shp.get("note"):
                st.html(f'<div class="sis-note">{H.e(shp["note"])}</div>')

    docs = payload.get("documents") or {}
    if any(docs.values()):
        C.section("Filings & documents", "Exchange announcements, annual reports, credit ratings and concalls",
                  color="green")
        st.html(H.documents_card(docs))


# ------------------------------------------------------------------ analysis
def render_analysis(payload: dict) -> None:
    company = st.session_state["company"]
    news = st.session_state.get("news") or repo.list_news(company["id"])

    with st.container(border=True):
        C.section("Generate analysis report", "Scorecard and projections are calculated in Python from the stored "
                  "Screener data; Gemini writes the narrative using only those numbers.", color="green", step=2)
        c1, c2, c3 = st.columns([1.4, 1.5, 1.9], vertical_alignment="bottom")
        with c1:
            gen = st.button("Generate analysis report", type="primary", use_container_width=True)
        with c2:
            refresh = st.checkbox("Refresh news first", value=True)
            use_external = st.checkbox(
                "Fill gaps from other websites", value=get_settings().external_enabled,
                disabled=not get_settings().external_enabled,
                help="Screener stays the main source. Only figures Screener does not publish (or extra points that "
                     "matter for the analysis) are taken from Yahoo Finance, Value Research Online, Investing.com "
                     "and Macrotrends, and each one is shown with its source. This never changes the stored "
                     "Screener data or the scorecard.")
        with c3:
            prev = repo.list_reports(company_id=company["id"], limit=30)
            if prev:
                opts = {r["id"]: f"#{r['id']} · {str(r['created_at'])[:16]} · {r['stance']} "
                                 f"{float(r['score'] or 0):.0f}/100" for r in prev}

                def _open_prev():
                    if st.session_state.get("prev_report"):
                        load_report_into_state(st.session_state["prev_report"])

                st.selectbox("Previous reports for this company", list(opts), format_func=opts.get,
                             index=None, placeholder="Open a previous report…", key="prev_report",
                             on_change=_open_prev)

    if gen:
        with st.status("Building analysis report…", expanded=True) as status:
            if refresh:
                st.write("Fetching latest news…")
                try:
                    news = refresh_news(company)
                    st.session_state["news"] = news
                except Exception as e:  # noqa: BLE001
                    st.write(f"News unavailable: {e}")
            report = build_report(payload, news, use_external=use_external, progress=st.write)
            rid = repo.save_report(company["id"], st.session_state.get("run_id"), _user_id(), report)
            st.session_state["report"], st.session_state["report_id"] = report, rid
            status.update(label=f"Report #{rid} ready ({report['model']})", state="complete", expanded=False)
        if report.get("llm_error"):
            st.warning(f"Gemini narrative failed, used rule-based text instead: {report['llm_error']}")
        if (report.get("forecast") or {}).get("error"):
            st.warning(f"Projections were not produced: {report['forecast']['error']}")
        sync_company_async(company["id"])

    report = st.session_state.get("report")
    if not report:
        C.empty_state("No report yet", "Generate a broker-style company update from the stored data.",
                      [("Scorecard", "Six factors scored 0–10 from real numbers"),
                       ("Projections", "Next three years from statistical models"),
                       ("Gap filling", "Missing figures from four other websites, with source"),
                       ("Export", "Download as a formatted PDF or JSON")])
        return
    render_report(report, payload)


def render_forecast(fc: dict) -> None:
    """Future outlook: projections for the next three fiscal years (stored inside the report)."""
    if not fc:
        return  # report generated before this feature existed
    C.section("Future outlook: model projections",
              "Next three fiscal years, projected in Python from the company's own Screener history")
    if not fc.get("ok"):
        st.info(f"Projections were not produced: {fc.get('error', 'not enough history')}.")
        return
    ft = fc.get("tables") or {}
    st.html(f'''<div class="sis-summary">{H.e(fc.get("method"))}
        <br><b>Overall confidence: {H.e(fc.get("confidence"))}</b> · Python libraries: {H.e(fc.get("libraries"))}</div>''')
    C.spacer(8)
    figs = charts_ui.forecast_charts(fc)
    if figs:
        cols = st.columns(len(figs), gap="medium")
        for col, (fig, unit_text) in zip(cols, figs):
            with col:
                C.unit(unit_text)
                st.plotly_chart(fig, use_container_width=True)
        st.caption("Solid line = reported by the company · dashed line = model's base case · shaded band = 80% range")

    names = [("annual", "By fiscal year", "forecast_annual"), ("quarterly", "Next four quarters", "forecast_quarterly"),
             ("derived", "What it implies", None), ("reliability", "How reliable?", None),
             ("models", "Models used", "forecast_annual")]
    names = [n for n in names if (ft.get(n[0]) or {}).get("rows")]
    if names:
        for tab, (key, _, unit_key) in zip(st.tabs([n[1] for n in names]), names):
            with tab:
                if unit_key:
                    C.unit_for(unit_key)
                elif key == "derived":
                    C.unit("times (x) and %", "first row in times, second row in percent")
                else:
                    C.unit("count and %", "test error in percent")
                st.html(H.indent_table(ft[key]["columns"], ft[key]["rows"]))
                if key in ("annual", "quarterly"):
                    st.caption("E = estimate by the model. Base case = weighted average of the models; low and high "
                               "case = 80% range from each model's past test errors.")
                elif key == "derived":
                    st.caption("P/E on projected EPS uses today's share price. It is arithmetic on the projection, "
                               "not a valuation call or a target price.")
                elif key == "reliability":
                    st.caption("Test error = average gap between what the method would have projected in earlier "
                               "years and what was actually reported. Below 8% = High, 8–18% = Medium, above 18% = "
                               "Low confidence.")
                else:
                    st.caption("Weight = share of each model in the base case; models that were more accurate in "
                               "the past get a higher weight.")
    if fc.get("notes"):
        C.bullet_list(fc["notes"], "watch")
    st.html(f'<div class="sis-note"><b>Read with care:</b> {H.e(fc.get("caveat", ""))}</div>')


def render_supplementary(sup: dict) -> None:
    """Figures taken from other websites because Screener does not publish them."""
    if not sup or not (sup.get("items") or sup.get("estimates") or sup.get("links") or sup.get("notes")):
        return
    C.section("Additional data from other websites",
              "Only what Screener does not publish · not part of the scorecard · every value shows its source",
              color="green")
    if sup.get("items"):
        C.subheading("Figures not available on Screener")
        C.unit_for("supplementary")
        st.html(H.supplementary_table(sup["items"]))
    if sup.get("estimates"):
        C.subheading("Analysts' estimates (third-party views, not ours)", color="green")
        C.unit("₹ per share", "revenue estimates in ₹ crore")
        st.html(H.supplementary_table(sup["estimates"], "Basis"))
    if sup.get("links"):
        C.spacer(6)
        st.html(H.source_links(sup["links"]))
    for note in sup.get("notes", []):
        st.caption(note)


def render_report(report: dict, payload: Optional[dict]) -> None:
    rid = st.session_state.get("report_id")
    comp = report.get("company", {})
    sym = comp.get("nse_symbol") or "company"
    _export_bar(json.dumps(report, indent=2, default=str, ensure_ascii=False).encode(),
                f"{sym}_analysis_{rid}.json", "prep_rep_pdf", "rep_pdf_for", rid,
                lambda: report_pdf_bytes(rid), f"{sym}_analysis_{rid}.pdf")

    stance = report.get("stance", "Neutral")
    st.html(f"""<div class="sis-card"><div class="sis-head"><div>
        <span class="sis-badge sis-{H.e(stance)}">{H.e(stance.upper())}</span>
        <span class="sis-mono" style="margin-left:10px">Score {float(report.get('score', 0)):.0f}/100 ·
          generated {H.e(str(report.get('generated_at'))[:16])} · narrative: {H.e(report.get('model'))}</span>
        <div class="name" style="margin-top:10px">{H.e(comp.get('name'))}</div>
        <div class="sis-sub">{H.e(' · '.join(x for x in [comp.get('broad_industry'), comp.get('industry')] if x))}</div>
        </div></div>
        <div class="sis-banner">{H.e(report.get('headline'))}</div>
        <div class="sis-summary">{H.e(report.get('executive_summary'))}</div></div>""")

    left, right = st.columns([1.75, 1], gap="large")
    with left:
        if report.get("investment_thesis"):
            C.subheading("Investment thesis", color="green")
            C.bullet_list(report["investment_thesis"], "watch")
        if report.get("stance_rationale"):
            C.subheading(f"Why {stance}?")
            st.write(report["stance_rationale"])
        for s in report.get("sections", []):
            C.subheading(s.get("heading", ""))
            st.write(s.get("body", ""))
    with right:
        with st.container(border=True):
            C.subheading("Market data")
            st.html(H.kv_rows_table(report.get("market_data") or []))
            if report.get("price_performance"):
                C.subheading("Price performance", color="green")
                C.unit("% change", "in share price")
                st.html(H.kv_rows_table(report["price_performance"]))
            sh = report.get("shareholding_table") or {}
            if sh.get("rows"):
                C.subheading("Shareholding")
                C.unit_for("shareholding")
                st.html(H.simple_table(sh["columns"], sh["rows"]))
        C.subheading("Scorecard", color="green")
        C.unit_for("scorecard")
        st.plotly_chart(charts_ui.scorecard_chart(report.get("scorecard", [])), use_container_width=True)
        with st.expander("Scorecard evidence"):
            for it in report.get("scorecard", []):
                st.markdown(f"**{it['name']}** ({it['weight']}%): {it['score']}/10  \n" + "; ".join(it["rationale"]))

    if payload:
        C.section("Exhibits", "Charts built from the scraped Screener data · the unit is shown above each chart",
                  color="green")
        figs = [(charts_ui.annual_chart(payload), "annual"), (charts_ui.quarterly_chart(payload), "quarterly"),
                (charts_ui.returns_chart(payload), "returns"),
                (charts_ui.pe_chart(payload.get("pe_history") or {}), "pe"),
                (charts_ui.shareholding_chart(payload), "shareholding")]
        figs = [(f, k) for f, k in figs if f]
        cols = st.columns(2, gap="medium")
        for i, (f, k) in enumerate(figs):
            with cols[i % 2]:
                C.unit(charts_ui.UNITS[k])
                st.plotly_chart(f, use_container_width=True)

    render_forecast(report.get("forecast") or {})

    tabs_def = [("Profit & Loss", "profit_loss"), ("Quarterly", "quarterly"), ("Balance Sheet", "balance_sheet"),
                ("Cash Flow", "cash_flow"), ("Key ratios", "key_ratios")]
    tables = report.get("tables", {})
    tabs_def = [(t, k) for t, k in tabs_def if (tables.get(k) or {}).get("rows")]
    if tabs_def:
        C.section("Financial summary", "Source: company filings via Screener.in · " + CRORE_HELP)
        for tab, (_, key) in zip(st.tabs([t for t, _ in tabs_def]), tabs_def):
            with tab:
                C.unit_for(key)
                st.html(H.simple_table(tables[key]["columns"], tables[key]["rows"]))

    render_supplementary(report.get("supplementary") or {})

    C.section("Strengths, risks & what to watch", color="green")
    a, b, c = st.columns(3, gap="medium")
    with a:
        with st.container(border=True):
            C.subheading("Key strengths", color="green")
            C.bullet_list(report.get("key_strengths") or [], "ok")
    with b:
        with st.container(border=True):
            C.subheading("Key risks")
            C.bullet_list(report.get("key_risks") or [], "risk")
    with c:
        with st.container(border=True):
            C.subheading("Monitorables")
            C.bullet_list(report.get("monitorables") or [], "watch")

    if report.get("news_takeaways") or report.get("news"):
        C.section("News & developments", "What recent announcements and headlines imply")
        if report.get("news_takeaways"):
            C.bullet_list(report["news_takeaways"], "watch")
        if report.get("news"):
            with st.expander("News used in this report"):
                for n in report["news"]:
                    C.news_item(n["title"], n["url"], n.get("source") or "", str(n.get("published_at"))[:10])
    C.spacer(6)
    st.html(f'<div class="sis-note">{H.e(report.get("disclaimer", ""))}</div>')


# ------------------------------------------------------------------ news
def render_news() -> None:
    company = st.session_state["company"]
    h1, h2 = st.columns([4, 1], vertical_alignment="bottom")
    with h1:
        C.section("Latest news", f"Recent headlines about {company['name']} (Google News)")
    with h2:
        if st.button("Refresh news", use_container_width=True):
            with st.spinner("Fetching news…"):
                try:
                    st.session_state["news"] = refresh_news(company)
                    sync_company_async(company["id"])
                except Exception as e:  # noqa: BLE001
                    st.error(f"News fetch failed: {e}")
    news = st.session_state.get("news") or repo.list_news(company["id"])
    if not news:
        C.empty_state("No news stored yet", "Click “Refresh news” to fetch the latest headlines.")
    for n in news:
        C.news_item(n["title"], n["url"], n.get("source") or "", str(n.get("published_at") or "")[:16])
    st.caption("Exchange announcements are in the Screener data tab → Filings & documents.")


# ------------------------------------------------------------------ page
def render() -> None:
    C.page_header("Company Dashboard",
                  "Fetch live fundamentals from Screener, store them in Supabase and generate an AI-assisted "
                  "company analysis report.",
                  eyebrow="Stock Insight Studio",
                  chips=["Screener.in data", "Supabase PostgreSQL", "Gemini narrative", "Model projections",
                         "RAGFlow chatbot"])
    company_picker()
    payload = st.session_state.get("payload")
    company = st.session_state.get("company")
    if not company:
        C.empty_state("Choose a company to begin", "Select any NSE-listed company above.",
                      [("1 · Select", "Pick from the dropdown or type a symbol"),
                       ("2 · Fetch", "Scrape live data and store it in the database"),
                       ("3 · Analyse", "Generate and export a broker-style report")])
        return
    if not payload:
        C.empty_state(f"{company['name']} selected",
                      "Click “Fetch from Screener” to capture fresh data, or “Load stored” to open the last capture.")
        return
    C.spacer(6)
    t1, t2, t3 = st.tabs(["Screener data", "Analysis report", "News"])
    with t1:
        render_screener(payload)
    with t2:
        render_analysis(payload)
    with t3:
        render_news()
