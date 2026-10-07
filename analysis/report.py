"""Build a professional, broker-style company analysis report from real scraped data.

Pipeline:  payload (Screener) -> metrics (Python) -> scorecard (rules)
           -> forecast (scikit-learn / SciPy, from Screener history)
           -> supplementary data (other websites, only what Screener lacks)
           -> narrative (Gemini) -> structured report dict (stored in DB, rendered in UI, exported to PDF/JSON)

Screener.in is the main source.  The scorecard, the stance and every financial table use Screener data
only; values from other websites are kept in their own block with source and link.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from analysis import llm
from analysis.external import collect_supplementary
from analysis.forecast import (build_forecast, fiscal_label, forecast_tables, outlook_sentences,
                               quarter_label)
from analysis.metrics import compute_metrics, find_series
from analysis.scorecard import build_scorecard
from core.utils import fmt_num, fmt_pct, pct_change, safe_div

log = logging.getLogger(__name__)

DISCLAIMER = (
    "This report is generated automatically from publicly available data using rule-based calculations, "
    "statistical models and an AI language model for the narrative. Screener.in is the main source "
    "(company page, financial statements, exchange announcements); public news headlines are added, and "
    "a small number of figures that Screener does not publish are taken from other websites (Yahoo Finance, "
    "Value Research Online, Investing.com, Macrotrends) and are shown separately with their source. "
    "Projections are statistical extensions of past figures, not management guidance or a promise of "
    "future results. Analyst targets or ratings quoted from other websites are third-party views, not ours. "
    "This report is for educational and informational purposes only and is NOT investment advice, a research "
    "report under SEBI (Research Analysts) Regulations, or a recommendation to buy, sell or hold any security. "
    "The stance and score reflect a mechanical scorecard, not a price target. Figures may contain errors from "
    "the source or the parsing process; verify with company filings before making any decision. Consult a "
    "SEBI-registered adviser for investment advice."
)


# ------------------------------------------------------------------ narrative schema
class NarrativeSection(BaseModel):
    heading: str
    body: str


class Narrative(BaseModel):
    headline: str = Field(description="One-line report title, like a broker company update headline")
    executive_summary: str = Field(description="120-180 words summarising the investment picture")
    investment_thesis: list[str] = Field(description="3-5 crisp bullet points")
    sections: list[NarrativeSection]
    key_strengths: list[str]
    key_risks: list[str]
    monitorables: list[str] = Field(description="What to watch in coming quarters")
    stance_rationale: str
    news_takeaways: list[str]


SYSTEM_PROMPT = (
    "You are a senior sell-side equity research analyst at an Indian brokerage writing a company update. "
    "Write in a crisp, professional, factual tone (like ICICI Securities / Kotak / Motilal Oswal notes). "
    "STRICT RULES: (1) Use ONLY numbers present in the provided DATA JSON; never invent or estimate figures "
    "yourself and never use outside knowledge for numbers. (2) Always mention the period for any figure "
    "(e.g. 'Q1FY27' or 'Jun 2026 quarter', 'FY26 / Mar 2026'). (3) Amounts are INR crore unless stated. "
    "(4) Do NOT give buy/sell/hold advice and do NOT give a target price of your own; the stance is provided "
    "and must be explained, not changed. (5) SOURCES: Screener.in is the main source. DATA may also contain "
    "'supplementary_data_other_websites' with figures Screener does not publish. Use them where they add to "
    "the analysis and name the website in brackets each time, e.g. '(Yahoo Finance)'. If Screener and another "
    "website both give the same figure, use Screener's. Analyst target prices or ratings found there are "
    "third-party views: you may report them as such, attributed, never as your own view. "
    "(6) FORECASTS: DATA contains 'model_projections' computed by the system with statistical models. You may "
    "quote them, always calling them 'model projection', using the E suffix (FY27E) and giving the low-high "
    "range and the confidence level. Do not create any other forecast and do not present a projection as a "
    "fact. (7) Only when a figure is in neither Screener data nor the supplementary data may you say it was "
    "not available, and say it once, briefly. (8) For banks/NBFCs, note that Screener's 'Financing Profit' is "
    "after provisions and other operating expenses."
)

SECTION_PLAN = [
    "Business overview",
    "Earnings performance (latest quarter and full year)",
    "Profitability and return ratios",
    "Balance sheet and leverage",
    "Cash flows",
    "Valuation",
    "Shareholding trends",
    "News and corporate developments",
    "Future outlook and model projections (next three fiscal years)",
    "Key monitorables and what could change the view",
]


# ------------------------------------------------------------------ tables
def _table_from_section(payload: dict, section: str, last_n: int, include_ttm: bool = True,
                        metrics: Optional[list[str]] = None) -> dict:
    sec = payload.get("sections", {}).get(section)
    if not sec:
        return {"columns": [], "rows": []}
    idx = [i for i, c in enumerate(sec["columns"]) if c["type"] != "ttm"][-last_n:]
    if include_ttm:
        idx += [i for i, c in enumerate(sec["columns"]) if c["type"] == "ttm"]
    cols = [sec["columns"][i]["label"] for i in idx]
    rows = []
    for r in sec["rows"]:
        if metrics and r["metric"] not in metrics:
            continue
        if all(r["numbers"][i] is None for i in idx if i < len(r["numbers"])):
            continue
        rows.append({"metric": r["metric"], "values": [r["values"][i] if i < len(r["values"]) else ""
                                                       for i in idx], "bold": r.get("is_bold", False)})
    return {"columns": cols, "rows": rows}


def _key_ratio_table(payload: dict, last_n: int = 6) -> dict:
    rev = find_series(payload, "profit-loss", "Sales", "Revenue")
    np_ = find_series(payload, "profit-loss", "Net Profit")
    eps = find_series(payload, "profit-loss", "EPS in Rs", "EPS")
    opm = find_series(payload, "profit-loss", "OPM %", "Financing Margin %")
    payout = find_series(payload, "profit-loss", "Dividend Payout %")
    roe = find_series(payload, "ratios", "ROE %")
    roce = find_series(payload, "ratios", "ROCE %")
    eq = find_series(payload, "balance-sheet", "Equity Capital")
    res = find_series(payload, "balance-sheet", "Reserves")
    debt = find_series(payload, "balance-sheet", "Borrowings", "Borrowing")
    if not rev:
        return {"columns": [], "rows": []}
    labels = [l for l, _ in rev.annual][-last_n:]

    def by_label(s):
        return dict(s.annual) if s else {}

    R, N, E = by_label(rev), by_label(np_), by_label(eps)
    all_labels = [l for l, _ in rev.annual]
    prev = {l: all_labels[i - 1] for i, l in enumerate(all_labels) if i > 0}
    rows_def = [
        ("Revenue growth %", lambda l: pct_change(R.get(prev.get(l)), R.get(l)), "pct"),
        ("Net profit growth %", lambda l: pct_change(N.get(prev.get(l)), N.get(l)), "pct"),
        ("EPS growth %", lambda l: pct_change(E.get(prev.get(l)), E.get(l)), "pct"),
        ((opm.metric if opm else "Operating margin %"), lambda l: by_label(opm).get(l), "pct"),
        ("Net margin %", lambda l: (safe_div(N.get(l), R.get(l)) or 0) * 100 if N.get(l) is not None else None, "pct"),
        ("ROE %", lambda l: by_label(roe).get(l), "pct"),
        ("ROCE %", lambda l: by_label(roce).get(l), "pct"),
        ("Debt / Equity (x)", lambda l: safe_div(by_label(debt).get(l),
                                                  (by_label(eq).get(l) or 0) + (by_label(res).get(l) or 0))
         if debt and eq and res else None, "x"),
        ("Dividend payout %", lambda l: by_label(payout).get(l), "pct"),
    ]
    rows = []
    for name, fn, kind in rows_def:
        vals = [fn(l) for l in labels]
        if all(v is None for v in vals):
            continue
        rows.append({"metric": name, "values": [
            (fmt_pct(v, 1) if kind == "pct" else f"{v:.2f}") if v is not None else "–" for v in vals]})
    return {"columns": labels, "rows": rows}


def _market_data(m: dict) -> list[list[str]]:
    v, pp, meta = m["valuation"], m["price_performance"], m["meta"]
    rows = [
        ["Market Cap (₹ Cr)", fmt_num(v.get("market_cap_cr"))],
        ["CMP (₹)", fmt_num(v.get("price"), 2)],
        ["52-week High / Low (₹)", f"{fmt_num(v.get('high_52w'))} / {fmt_num(v.get('low_52w'))}"],
        ["P/E (x)", f"{v['pe']:.1f}" if v.get("pe") else "–"],
        ["5-yr median P/E (x)", f"{v['median_pe_5y']:.1f}" if v.get("median_pe_5y") else "–"],
        ["P/B (x)", f"{v['pb']:.2f}" if v.get("pb") else "–"],
        ["Book value (₹)", fmt_num(v.get("book_value"), 0)],
        ["Dividend yield", fmt_pct(v.get("dividend_yield"), 2)],
        ["ROE / ROCE", f"{fmt_pct(m['profitability'].get('roe_current'))} / "
                       f"{fmt_pct(m['profitability'].get('roce_current'))}"],
        ["Face value (₹)", fmt_num(v.get("face_value"), 2)],
        ["NSE / BSE", f"{meta.get('nse_symbol') or '–'} / {meta.get('bse_code') or '–'}"],
        ["Industry", meta.get("industry") or meta.get("broad_industry") or "–"],
    ]
    if pp.get("as_of"):
        rows.append(["Price data as of", pp["as_of"]])
    return rows


def _price_perf_rows(m: dict) -> list[list[str]]:
    pp = m["price_performance"]
    return [[k, fmt_pct(pp.get(f"return_{k}"))] for k in ("1M", "3M", "6M", "1Y", "3Y", "5Y")
            if pp.get(f"return_{k}") is not None]


def _shareholding_rows(m: dict) -> dict:
    holders = m["shareholding"].get("holders", {})
    if not holders:
        return {"columns": [], "rows": []}
    any_h = next(iter(holders.values()))
    cols = [c for c, _ in any_h["history"]][-4:]
    rows = []
    for name, h in holders.items():
        vals = [v for _, v in h["history"]][-4:]
        if name.lower().startswith("no. of"):
            rows.append({"metric": name, "values": [fmt_num(x) for x in vals]})
        else:
            rows.append({"metric": name, "values": [fmt_pct(x, 2) for x in vals]})
    return {"columns": cols, "rows": rows}


# ------------------------------------------------------------------ helpers
def _round(obj: Any, nd: int = 2) -> Any:
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, dict):
        return {k: _round(v, nd) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round(x, nd) for x in obj]
    return obj


def _fy_label(label: str) -> str:
    """'Mar 2026' -> 'FY26' (Indian fiscal year ending March)."""
    try:
        mon, yr = label.split()
        yr = int(yr)
        fy = yr if mon.lower().startswith(("jan", "feb", "mar")) else yr + 1
        return f"FY{str(fy)[-2:]}"
    except Exception:  # noqa: BLE001
        return label


def _q_label(label: str) -> str:
    """'Jun 2026' -> 'Q1FY27'."""
    try:
        mon, yr = label.split()
        yr = int(yr)
        mm = mon.lower()[:3]
        qmap = {"jun": (1, 1), "sep": (2, 1), "dec": (3, 1), "mar": (4, 0)}
        if mm not in qmap:
            return label
        q, add = qmap[mm]
        return f"Q{q}FY{str(yr + add)[-2:]}"
    except Exception:  # noqa: BLE001
        return label


# ------------------------------------------------------------------ forecast / supplementary -> prompt
def _forecast_for_llm(fc: dict) -> dict:
    """Compact view of the projections for the AI (it may quote these, nothing else)."""
    if not fc or not fc.get("ok"):
        return {"available": False, "reason": (fc or {}).get("error")}

    def blk(b: dict, lab) -> dict:
        nd = 2 if b["unit"] == "INR" else 0
        return {
            "metric": b["name"], "unit": "INR per share" if b["unit"] == "INR" else "INR crore",
            "last_reported": {"period": lab(b["last_label"]), "value": round(b["last_actual"], nd)},
            "projection": [{"period": lab(l, True), "base": round(v, nd), "low": round(lo, nd), "high": round(hi, nd),
                            "growth_pct_vs_previous": None if g is None else round(g, 1)}
                           for l, v, lo, hi, g in zip(b["labels"], b["base"], b["low"], b["high"], b["growth_pct"])],
            "growth_per_year_pct": None if b.get("cagr_pct") is None else round(b["cagr_pct"], 1),
            "confidence": b["confidence"],
            "average_past_test_error_pct": None if b.get("backtest_mape_pct") is None else round(b["backtest_mape_pct"], 1),
            "one_off_jump_adjusted": b.get("break"),
        }

    d = fc.get("derived") or {}
    return {
        "available": True, "method": fc["method"], "range_meaning": "low/high is an 80% range", "caveat": fc["caveat"],
        "overall_confidence": fc["confidence"],
        "annual": [blk(b, fiscal_label) for b in fc["annual"] if b.get("ok")],
        "quarterly": [blk(b, quarter_label) for b in fc["quarterly"] if b.get("ok")],
        "pe_on_projected_eps": [{"period": fiscal_label(x["label"], True), "value": _round(x["value"], 1)}
                                for x in d.get("forward_pe", [])],
        "projected_net_margin_pct": [{"period": fiscal_label(x["label"], True), "value": _round(x["value"], 1)}
                                     for x in d.get("net_margin_pct", [])],
        "notes": fc.get("notes", []),
    }


def _supplementary_for_llm(sup: dict) -> dict:
    if not sup or not (sup.get("items") or sup.get("estimates")):
        return {"available": False}
    return {
        "available": True,
        "rule": "Not from Screener. Name the website when you use any of these.",
        "items": [{"metric": i["metric"], "value": i["value"], "period": i.get("period"), "source": i["source"]}
                  for i in sup.get("items", [])],
        "analyst_estimates": [{"metric": i["metric"], "value": i["value"], "period": i.get("period"),
                               "analysts": i.get("analysts"), "source": i["source"]}
                              for i in sup.get("estimates", [])],
    }


# ------------------------------------------------------------------ rule-based narrative (fallback)
def _rule_based_narrative(m: dict, sc: dict, news: list[dict], announcements: list[dict],
                          fc: Optional[dict] = None, sup: Optional[dict] = None) -> dict:
    meta, g, q, p, b, c, v = (m["meta"], m["growth"], m["quarterly"], m["profitability"],
                              m["balance_sheet"], m["cash_flow"], m["valuation"])
    name = meta.get("name") or "The company"
    is_fin = m["company_type"] == "bank_or_nbfc"
    ql = q.get("latest_quarter")
    qtag = f"{_q_label(ql)} ({ql})" if ql else "the latest quarter"
    fy = g.get("revenue_latest_fy_label")
    fytag = f"{_fy_label(fy)}" if fy else "the latest year"

    if q.get("profit_yoy") is not None:
        pr = f"net profit {'up' if q['profit_yoy'] >= 0 else 'down'} {abs(q['profit_yoy']):.1f}% YoY"
    else:
        pr = f"net profit ₹{fmt_num(q.get('net_profit'))} Cr"
    headline = f"{name}: {qtag} {pr}; scorecard stance {sc['stance']} ({sc['score']:.0f}/100)"
    summary = (
        f"{name} ({meta.get('industry') or meta.get('broad_industry') or 'listed company'}) reported "
        f"{qtag} revenue of ₹{fmt_num(q.get('revenue'))} Cr ({fmt_pct(q.get('revenue_yoy'))} YoY) and net profit of "
        f"₹{fmt_num(q.get('net_profit'))} Cr ({fmt_pct(q.get('profit_yoy'))} YoY). Over five years revenue compounded at "
        f"{fmt_pct(g.get('screener_sales_5', g.get('revenue_cagr_5y')))} and profit at "
        f"{fmt_pct(g.get('screener_profit_5', g.get('profit_cagr_5y')))}. Current ROE is {fmt_pct(p.get('roe_current'))}."
    )
    if v.get("pe"):
        summary += f" The stock trades at {v['pe']:.1f}x trailing earnings"
        summary += (f" versus a 5-year median of {v['median_pe_5y']:.1f}x." if v.get("median_pe_5y") else ".")
    summary += f" The mechanical scorecard places it at {sc['score']:.0f}/100 ({sc['stance']})."

    thesis = [f"{it['name']}: {it['score']}/10 — {'; '.join(it['rationale'])}" for it in sc["items"]]
    sections = [
        {"heading": "Business overview",
         "body": (m.get("about") or f"{name} is listed on NSE"
                  + (f" and classified under {meta.get('industry')}" if meta.get("industry") else "") + ".")},
        {"heading": "Earnings performance",
         "body": (f"In {qtag}, revenue was ₹{fmt_num(q.get('revenue'))} Cr ({fmt_pct(q.get('revenue_qoq'))} QoQ, "
                  f"{fmt_pct(q.get('revenue_yoy'))} YoY) and net profit ₹{fmt_num(q.get('net_profit'))} Cr "
                  f"({fmt_pct(q.get('profit_qoq'))} QoQ, {fmt_pct(q.get('profit_yoy'))} YoY). For {fytag}, revenue was "
                  f"₹{fmt_num(g.get('revenue_latest_fy'))} Cr ({fmt_pct(g.get('revenue_yoy_latest_fy'))} YoY) and net profit "
                  f"₹{fmt_num(g.get('profit_latest_fy'))} Cr ({fmt_pct(g.get('profit_yoy_latest_fy'))} YoY).")},
        {"heading": "Profitability and return ratios",
         "body": (f"{p.get('margin_label', 'Operating margin')} was {fmt_pct(p.get('margin_latest_fy'), 0)} in {fytag} "
                  f"(5-yr average {fmt_pct(p.get('margin_avg_5y'), 0)}). Net margin was {fmt_pct(p.get('net_margin_latest_fy'))}. "
                  f"ROE stands at {fmt_pct(p.get('roe_current'))} (5-yr average {fmt_pct(p.get('roe_avg_5y'))})"
                  + (f" and ROCE at {fmt_pct(p.get('roce_current'))}." if p.get("roce_current") else "."))},
        {"heading": "Balance sheet and leverage",
         "body": ((f"Net worth is ₹{fmt_num(b.get('net_worth'))} Cr; total assets are {b['leverage_assets_to_equity']:.1f}x "
                   f"net worth. Deposits grew {fmt_pct(b.get('deposits_yoy'))} YoY." if is_fin and b.get("leverage_assets_to_equity")
                   else f"Net worth is ₹{fmt_num(b.get('net_worth'))} Cr with borrowings of ₹{fmt_num(b.get('debt'))} Cr "
                        f"(debt/equity {b['debt_to_equity']:.2f}x)." if b.get("debt_to_equity") is not None
                   else "Balance-sheet data is limited for this company."))},
        {"heading": "Cash flows",
         "body": ("For lenders, operating cash flow mainly reflects deposit and loan movements and is not a reliable "
                  "earnings-quality signal." if is_fin else
                  f"Cumulative 5-year operating cash flow was {c['cfo_to_pat_5y']:.2f}x cumulative net profit."
                  if c.get("cfo_to_pat_5y") is not None else "Cash-flow data is not available.")},
        {"heading": "Valuation",
         "body": (f"At ₹{fmt_num(v.get('price'), 2)}, the stock trades at {v['pe']:.1f}x P/E and {v['pb']:.2f}x book."
                  if v.get("pe") and v.get("pb") else "Valuation multiples are not fully available.")
                 + (f" Its 5-year median P/E is {v['median_pe_5y']:.1f}x." if v.get("median_pe_5y") else "")
                 + (f" Peer median P/E is {v['peer_median_pe']:.1f}x." if v.get("peer_median_pe") else "")},
    ]
    holders = m["shareholding"].get("holders", {})
    if holders:
        parts = [f"{k} {h['latest']:.2f}% ({h['chg_4q']:+.2f} pts over 4 quarters)" for k, h in holders.items()
                 if h.get("latest") is not None and h.get("chg_4q") is not None and not k.lower().startswith("no.")]
        if not parts:
            parts = [f"{k} {h['latest']:.2f}%" for k, h in holders.items()
                     if h.get("latest") is not None and not k.lower().startswith("no.")]
        if parts:
            sections.append({"heading": "Shareholding trends",
                             "body": f"As of {m['shareholding'].get('latest_period')}: " + "; ".join(parts) + "."})
    if announcements or news:
        items = [a["title"] for a in announcements[:3]] + [n["title"] for n in news[:3]]
        sections.append({"heading": "News and corporate developments",
                         "body": "Recent items: " + " | ".join(items)})
    outlook = outlook_sentences(fc or {})
    if outlook:
        sections.append({"heading": "Future outlook and model projections",
                         "body": " ".join(outlook) + " " + (fc or {}).get("caveat", "")})
    extra = (sup or {}).get("items") or []
    if extra:
        sections.append({"heading": "Additional data from other websites",
                         "body": "Figures Screener does not publish: " + "; ".join(
                             f"{i['metric']} {i['value']}" + (f" for {i['period']}" if i.get("period") and
                                                              i["period"] != "latest" else "") + f" ({i['source']})"
                             for i in extra[:12]) + "."})
    return {
        "headline": headline,
        "executive_summary": summary,
        "investment_thesis": thesis[:5],
        "sections": sections,
        "key_strengths": m.get("pros") or [],
        "key_risks": m.get("cons") or [],
        "monitorables": [f"Next results date: {meta.get('upcoming_result_date')}"] if meta.get("upcoming_result_date") else [],
        "stance_rationale": f"Score {sc['score']:.0f}/100 from the six-factor scorecard.",
        "news_takeaways": [n["title"] for n in news[:5]],
    }


# ------------------------------------------------------------------ main
def build_report(payload: dict, news: list[dict] | None = None, use_llm: bool = True,
                 use_external: bool = True, progress: Optional[Callable[[str], None]] = None) -> dict:
    """payload = one stored Screener capture.  use_external=False builds the report from Screener only."""
    say = progress or (lambda _msg: None)
    news = news or []
    say("Computing metrics and scorecard from the stored Screener data…")
    m = compute_metrics(payload)
    m["about"] = payload.get("about", "")
    sc = build_scorecard(m)
    announcements = (payload.get("documents") or {}).get("announcements", [])[:10]

    say("Projecting the next three years with statistical models (scikit-learn, SciPy)…")
    try:
        fc = build_forecast(payload)
    except Exception as e:  # noqa: BLE001 - the report must still be produced
        log.warning("Forecast failed: %s", e)
        fc = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if fc.get("ok"):
        fc["tables"] = forecast_tables(fc)

    if use_external:
        say("Looking up figures Screener does not publish on Yahoo Finance, Value Research, Investing.com, "
            "Macrotrends…")
        sup = collect_supplementary(payload, m, use_ai=use_llm)
    else:
        sup = {"enabled": False, "items": [], "estimates": [], "links": [],
               "notes": ["Other websites were not used for this report (switched off by the user)."]}

    data_for_llm = {
        "company": m["meta"],
        "about": payload.get("about", "")[:1500],
        "company_type": m["company_type"],
        "latest_quarter_label": m["quarterly"].get("latest_quarter"),
        "latest_quarter_fiscal_label": _q_label(m["quarterly"].get("latest_quarter") or ""),
        "latest_fy_label": m["growth"].get("revenue_latest_fy_label"),
        "latest_fy_fiscal_label": _fy_label(m["growth"].get("revenue_latest_fy_label") or ""),
        "metrics": _round({k: m[k] for k in ("growth", "quarterly", "profitability", "balance_sheet",
                                             "cash_flow", "efficiency", "valuation", "price_performance")}),
        "shareholding": _round({k: {kk: vv for kk, vv in h.items() if kk != "history"}
                                for k, h in m["shareholding"].get("holders", {}).items()}),
        "scorecard": sc,
        "screener_pros": m["pros"],
        "screener_cons": m["cons"],
        "profit_and_loss_last_years": _table_from_section(payload, "profit-loss", 6),
        "quarterly_results_last_quarters": _table_from_section(payload, "quarters", 6, include_ttm=False),
        "balance_sheet_last_years": _table_from_section(payload, "balance-sheet", 5, include_ttm=False),
        "peers": [{"name": p["name"], **p["values"]} for p in (payload.get("peers") or {}).get("rows", [])[:8]],
        "recent_exchange_announcements": [{"date": a.get("date"), "title": a["title"], "summary": a.get("summary")}
                                          for a in announcements],
        "recent_news_headlines": [{"date": str(n.get("published_at") or "")[:10], "title": n["title"],
                                   "source": n.get("source")} for n in news[:15]],
        "model_projections": _forecast_for_llm(fc),
        "supplementary_data_other_websites": _supplementary_for_llm(sup),
    }

    narrative, model_used, llm_error = None, "rule-based", None
    if use_llm and llm.is_available():
        say("Writing the narrative with Gemini…")
        prompt = (
            "Write a company update report using ONLY the DATA below.\n"
            f"The stance is fixed as '{sc['stance']}' with score {sc['score']}/100 from the scorecard; explain it.\n"
            f"Write these sections in order (150-220 words each, plain paragraphs, no markdown headings): "
            f"{json.dumps(SECTION_PLAN)}.\n"
            "In 'Future outlook and model projections' walk through model_projections for revenue, net profit and "
            "EPS (base case, low-high range, growth per year, confidence, any one-off jump that was adjusted) and "
            "what would have to go right or wrong, using only facts in DATA.\n"
            "Wherever supplementary_data_other_websites fills something Screener lacks (for a bank: NIM, NPAs, "
            "CASA, capital adequacy), use it in the relevant section and name the website.\n"
            "key_strengths / key_risks / monitorables: 4-6 bullets each, specific and numeric where the data allows.\n"
            "news_takeaways: 3-6 bullets summarising what the announcements/news imply (no speculation).\n\n"
            f"DATA:\n{json.dumps(data_for_llm, default=str)}"
        )
        try:
            narrative = llm.generate_json(prompt, Narrative, system=SYSTEM_PROMPT)
            model_used = llm.model_name()
        except Exception as e:  # noqa: BLE001
            llm_error = f"{type(e).__name__}: {e}"
            log.warning("LLM narrative failed, using rule-based text: %s", e)
    if narrative is None:
        narrative = _rule_based_narrative(m, sc, news, announcements, fc, sup)

    report = {
        "report_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model_used,
        "llm_error": llm_error,
        "company": m["meta"],
        "company_type": m["company_type"],
        "data_as_of": payload.get("meta", {}).get("captured_at"),
        "run_id": payload.get("meta", {}).get("run_id"),
        "stance": sc["stance"],
        "score": sc["score"],
        "scorecard": sc["items"],
        "headline": narrative.get("headline"),
        "executive_summary": narrative.get("executive_summary"),
        "investment_thesis": narrative.get("investment_thesis", []),
        "sections": narrative.get("sections", []),
        "key_strengths": narrative.get("key_strengths", []),
        "key_risks": narrative.get("key_risks", []),
        "monitorables": narrative.get("monitorables", []),
        "stance_rationale": narrative.get("stance_rationale"),
        "news_takeaways": narrative.get("news_takeaways", []),
        "market_data": _market_data(m),
        "price_performance": _price_perf_rows(m),
        "shareholding_table": _shareholding_rows(m),
        "tables": {
            "profit_loss": _table_from_section(payload, "profit-loss", 5),
            "quarterly": _table_from_section(payload, "quarters", 5, include_ttm=False),
            "balance_sheet": _table_from_section(payload, "balance-sheet", 5, include_ttm=False),
            "cash_flow": _table_from_section(payload, "cash-flow", 5, include_ttm=False),
            "key_ratios": _key_ratio_table(payload),
        },
        "peers": {"columns": (payload.get("peers") or {}).get("columns", []),
                  "rows": [{"name": p["name"], "values": p["values"]}
                           for p in (payload.get("peers") or {}).get("rows", [])],
                  "median": ((payload.get("peers") or {}).get("median") or {}).get("values")},
        "news": [{"title": n["title"], "url": n["url"], "source": n.get("source"),
                  "published_at": str(n.get("published_at") or "")} for n in news[:12]],
        "announcements": announcements,
        "metrics": _round(m),
        "forecast": _round(fc, 4),
        "supplementary": sup,
        "sources": {"main": "Screener.in",
                    "supplementary_used": sorted({i["source"] for i in sup.get("items", []) + sup.get("estimates", [])})},
        "disclaimer": DISCLAIMER,
    }
    return report
