"""Analysis Report tab: generate, reopen and display the broker-style report (and its exports)."""
from __future__ import annotations

import json
from typing import Optional

import streamlit as st

from analysis.news import group_by_source
from analysis.report import build_report
from core import repository as repo
from core.config import get_settings
from core.services import refresh_news
from core.units import CRORE_HELP
from exports.pdf_report import build_report_pdf
from rag.sync import sync_company_async
from ui import charts_ui
from ui import components as C
from ui import html as H


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


def load_report_into_state(report_id: int) -> None:
    from ui.company_view import load_run_into_state, set_company

    rep = repo.get_report(report_id)
    if not rep:
        return
    if rep.get("run_id"):
        load_run_into_state(rep["run_id"])
    else:
        set_company(repo.get_company(rep["company_id"]))
    st.session_state["report"] = rep["report"]
    st.session_state["report_id"] = report_id


def _export_bar(json_bytes: bytes, json_name: str, prep_key: str, state_key: str, ident, pdf_fn, pdf_name: str) -> None:
    with st.container(border=True):
        a, b, c, d = st.columns([2.2, 1, 1, 1.2], vertical_alignment="center")
        with a:
            st.html('<div style="font-weight:700;color:#163A5F">Export this report</div>'
                    '<div style="font-size:.8rem;color:#595959">JSON (all data) or a formatted broker-style PDF</div>')
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


def render_analysis(payload: dict) -> None:
    company = st.session_state["company"]
    news = st.session_state.get("news") or repo.list_news(company["id"])

    with st.container(border=True):
        C.section("Analysis report", "Scorecard and projections are calculated in Python from the stored "
                  "Screener data; Gemini writes the narrative using only those numbers.")
        c1, c2, c3 = st.columns([1.4, 1.5, 1.9], vertical_alignment="bottom")
        with c1:
            gen = st.button("Generate analysis report", type="primary", use_container_width=True)
        with c2:
            refresh = st.checkbox("Refresh news first (NSE, BSE + 11 news websites, up to 15 each)", value=True)
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
            repo.log_activity(_user_id(), company["id"],
                              f"Generated analysis report #{rid}: {report['stance']} ({report['score']:.0f}/100)")
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
        st.caption("Solid line = reported by the company · dashed line = base case of all models · dotted green line = "
                   "TimesFM AI forecast (when installed) · shaded band = 80% range")

    render_timesfm(fc)

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


def render_timesfm(fc: dict) -> None:
    """Google Research's TimesFM AI model: its own forecast for this company, next to the base case."""
    info = fc.get("timesfm") or {}
    ft = fc.get("tables") or {}
    C.subheading("TimesFM AI forecast (Google Research)")
    if not info.get("used"):
        st.html(f'<div class="sis-note"><b>TimesFM was not used for this report.</b> {H.e(info.get("reason") or "")} '
                f'{H.e(info.get("how_to_enable") or "")}</div>')
        return
    st.caption(f"Model: {info.get('checkpoint')} · TimesFM is pre-trained on a very large collection of time series "
               "and forecasts this company's own Screener history directly. Its range comes from the model's own "
               "quantiles (10% and 90%).")
    for key, label, unit_key in (("timesfm_annual", "By fiscal year", "forecast_annual"),
                                 ("timesfm_quarterly", "Next four quarters", "forecast_quarterly")):
        t = ft.get(key) or {}
        if t.get("rows"):
            st.html(f'<div style="font-weight:600;color:#163A5F;margin:6px 0 2px">{label}</div>')
            C.unit_for(unit_key)
            st.html(H.indent_table(t["columns"], t["rows"]))
    st.caption("Weight = share TimesFM got in the base case, based on how accurate it was on this company's past "
               "years. Test error = its average miss in those tests. A model projection, not a target or advice.")
    C.spacer(6)


def render_supplementary(sup: dict) -> None:
    """Figures taken from other websites because Screener does not publish them."""
    if not sup or not (sup.get("items") or sup.get("estimates") or sup.get("links") or sup.get("notes")):
        return
    used = sup.get("sources_used") or sorted({i.get("source") for i in sup.get("items", []) if i.get("source")})
    C.section("Additional data from other websites",
              "Only what Screener does not publish · not part of the scorecard · every value shows its source"
              + (" · sources this time: " + ", ".join(used) if used else ""), color="green")
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
    if sup.get("notes"):
        with st.expander("How each website answered"):
            for note in sup["notes"]:
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

    render_report_peers(report)
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

    render_report_news(report)
    C.spacer(6)
    st.html(f'<div class="sis-note">{H.e(report.get("disclaimer", ""))}</div>')


def render_report_peers(report: dict) -> None:
    peers = report.get("peers") or {}
    C.section("Peer comparison", "Companies in the same industry, as listed by Screener")
    if not peers.get("rows"):
        st.caption("Screener did not return a peer list for this company in this capture.")
        return
    cols = peers["columns"][2:] if len(peers.get("columns", [])) > 2 else peers.get("columns", [])
    rows = [{"metric": p["name"], "values": [p["values"].get(c, "") for c in cols]} for p in peers["rows"]]
    if peers.get("median"):
        rows.append({"metric": "Median", "values": [peers["median"].get(c, "") for c in cols], "bold": True})
    C.unit_for("peers")
    st.html(H.simple_table(cols, rows))


def render_report_news(report: dict) -> None:
    groups = report.get("news_by_source") or []
    if not groups and report.get("news"):  # reports made before v3
        tmp: dict = {}
        for n in report["news"]:
            tmp.setdefault(n.get("source") or "Other", []).append(n)
        groups = [{"source": k, "items": v[:6]} for k, v in tmp.items()]
    anns = report.get("announcements") or []
    if not (groups or anns or report.get("news_takeaways")):
        return
    srcs = report.get("news_sources") or [g["source"] for g in groups]
    C.section("News and announcements", "Latest headlines from " + ", ".join(srcs))
    from analysis.report import counts_line

    if counts_line(report):
        st.caption(counts_line(report))
    left, right = st.columns([1.5, 1], gap="large")
    with left:
        if groups:
            C.news_grouped([(g["source"], g["items"]) for g in groups])
            allnews = report.get("news") or []
            shown = sum(len(g["items"]) for g in groups)
            if len(allnews) > shown:
                with st.expander(f"All {len(allnews)} headlines found"):
                    C.news_grouped(list(group_by_source(allnews).items()))
        else:
            st.caption("No recent headlines were found on these websites.")
    with right:
        with st.container(border=True):
            C.subheading("Key insights from the news")
            C.bullet_list(report.get("news_takeaways") or [], "watch")
        if anns:
            with st.container(border=True):
                C.subheading("Exchange announcements", color="green")
                C.news_list([{"title": a.get("title"), "url": a.get("url"), "source": "NSE/BSE filing",
                              "published_at": a.get("date")} for a in anns[:8]])
