"""Fetch history, analysis history and the stored-data explorer (shown inside the Notebook tab)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import db
from core import repository as repo
from ui import charts_ui
from ui import components as C

SECTIONS = ["quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios", "shareholding-quarterly",
            "shareholding-yearly", "growth"]


def render(user_filter=None, tabs=None) -> None:
    """tabs: the three st.tabs containers to draw into (fetch history, analysis history, query)."""
    from ui.company_view import open_report, open_run

    t1, t2, t3 = tabs or st.tabs(["Data fetch history", "Analysis history", "Query stored data"])

    with t1:
        C.section("Data fetch history", "Each row is one Screener capture saved in scrape_runs")
        runs = repo.list_runs(user_id=user_filter, limit=300)
        if not runs:
            st.info("No fetches yet.")
        else:
            df = pd.DataFrame(runs)
            df["started_at"] = pd.to_datetime(df["started_at"]).dt.strftime("%Y-%m-%d %H:%M")
            st.dataframe(df[["id", "started_at", "nse_symbol", "company_name", "basis", "status", "facts",
                             "latest_period", "duration_ms", "error"]],
                         hide_index=True, use_container_width=True)
            ok_runs = [r for r in runs if r["status"] == "success"]
            if ok_runs:
                opts = {r["id"]: f"#{r['id']} · {r['company_name']} · {r['basis']} · {str(r['started_at'])[:16]}"
                        for r in ok_runs}
                C.subheading("Open a capture", color="green")
                c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
                with c1:
                    rid = st.selectbox("Open a stored capture", list(opts), format_func=opts.get, key="hist_run")
                with c2:
                    if st.button("Open company page", key="open_run", use_container_width=True):
                        open_run(rid)
                        st.rerun()

    with t2:
        C.section("Analysis history", "Every generated report, with its stance and score", color="green")
        reps = repo.list_reports(user_id=user_filter, limit=300)
        if not reps:
            st.info("No analysis reports yet.")
        else:
            df = pd.DataFrame(reps)
            df["created_at"] = pd.to_datetime(df["created_at"]).dt.strftime("%Y-%m-%d %H:%M")
            df["score"] = df["score"].astype(float).round(1)
            st.dataframe(df[["id", "created_at", "nse_symbol", "company_name", "stance", "score", "model", "headline"]],
                         hide_index=True, use_container_width=True)
            opts = {r["id"]: f"#{r['id']} · {r['company_name']} · {r['stance']} · {str(r['created_at'])[:16]}" for r in reps}
            C.subheading("Open a report", color="green")
            c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
            with c1:
                rid = st.selectbox("Open a report", list(opts), format_func=opts.get, key="hist_rep")
            with c2:
                if st.button("Open report", key="open_rep", use_container_width=True):
                    open_report(rid)
                    st.rerun()

    with t3:
        C.section("Query stored data", "Explore the structured financial_facts table")
        st.caption("Every scraped number is stored as one row in `financial_facts` "
                   "(company, section, metric, period, value, unit). Query the latest capture of any company:")
        comps = db.fetch_all("""select distinct c.id, c.name, c.nse_symbol from companies c
                                join scrape_runs r on r.company_id = c.id and r.status = 'success' order by c.name""")
        if not comps:
            st.info("Fetch at least one company first.")
            return
        cmap = {c["id"]: f"{c['nse_symbol'] or ''} — {c['name']}" for c in comps}
        c1, c2 = st.columns(2)
        with c1:
            cid = st.selectbox("Company", list(cmap), format_func=cmap.get, key="q_company")
        with c2:
            section = st.selectbox("Section", SECTIONS, key="q_section")
        facts = repo.query_facts(cid, section=section)
        if not facts:
            st.info("No rows for this section.")
            return
        df = pd.DataFrame(facts)
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        top = df[df["parent_metric"].isna()]["metric"].unique().tolist()
        metrics = st.multiselect("Metrics", df["metric"].unique().tolist(), default=top[:3], key="q_metrics")
        sub = df[df["metric"].isin(metrics)] if metrics else df
        order = list(dict.fromkeys(df["period_label"].tolist()))
        pivot = sub.pivot_table(index="metric", columns="period_label", values="value", aggfunc="first")
        pivot = pivot[[c for c in order if c in pivot.columns]]
        st.dataframe(pivot, use_container_width=True)
        if metrics and section != "growth":
            st.plotly_chart(charts_ui.facts_chart(sub.sort_values("period_date"), f"{cmap[cid]} · {section}"),
                            use_container_width=True)
        st.download_button("Download these rows (CSV)", sub.to_csv(index=False).encode(),
                           file_name=f"facts_{cid}_{section}.csv", mime="text/csv")
        with st.expander("Example SQL you can run in the Supabase SQL Editor"):
            st.code("""-- Net profit of every stored company, latest capture, by quarter
select nse_symbol, company_name, period_label, value
from v_latest_facts
where section = 'quarters' and metric = 'Net Profit' and parent_metric is null
order by nse_symbol, period_date;

-- ROE history for one company
select period_label, value from v_latest_facts
where nse_symbol = 'HDFCBANK' and section = 'ratios' and metric = 'ROE %'
order by period_date;

-- Compare 5-year sales CAGR across companies
select nse_symbol, value as sales_cagr_5y from v_latest_facts
where section = 'growth' and metric = 'Compounded Sales Growth' and period_label = '5 Years'
order by value desc;""", language="sql")
