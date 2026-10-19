"""Financial health & warning signs - computed by code from the stored Screener data (and Yahoo Finance for the
dividend / split history). Nothing here is written by the AI, so every number can be traced to a source row.

What is built and why (see README "Financial health" for the reader-facing explanation):
  working_capital   debtor / inventory / payable days, cash conversion cycle - how fast sales turn into cash
  earnings_quality  other income share of profit, tax rate, interest coverage, cash profit vs reported profit
  cash_capex        operating cash flow, capital spending, free cash flow and FCF margin by year
  dupont            ROE split into margin x asset turnover x leverage - where the return comes from
  piotroski         Piotroski F-score: 9 yes/no tests of profitability, funding and efficiency
  red_flags         rule-based warning signs with the evidence that triggered each one
  risk              share price volatility and largest fall from a peak (from the stored price history)
  actions           dividends per share by year, splits / bonuses, recent corporate-action filings
  documents         latest credit ratings, annual report and earnings-call files listed on Screener

Not built on purpose:
  Altman Z-score    needs current assets and current liabilities, which Screener's balance sheet does not split out;
                    an approximation could label a healthy company as distressed (or the reverse).
  segment revenue, guidance, contingent liabilities, related-party deals - only in annual-report PDFs.
"""
from __future__ import annotations

import logging
import math
import re
import statistics
from datetime import date, timedelta
from typing import Any, Optional

from analysis.forecast import fiscal_label
from analysis.metrics import find_series
from core.utils import fmt_num, pct_change, safe_div

log = logging.getLogger(__name__)
YEARS = 6


# ------------------------------------------------------------------ helpers
def _annual(payload: dict, section: str, *names: str) -> dict[str, Optional[float]]:
    s = find_series(payload, section, *names)
    return dict(s.annual) if s else {}


def _schedule(payload: dict, section: str, parent: str, *children: str) -> dict[str, Optional[float]]:
    """Annual values of a '+' breakdown row (e.g. Cash from Investing -> Fixed assets purchased)."""
    sec = (payload.get("sections") or {}).get(section) or {}
    cols = sec.get("columns") or []
    for row in sec.get("rows", []):
        if not row["metric"].lower().startswith(parent.lower()):
            continue
        for name, sub in (row.get("schedules") or {}).items():
            if any(name.lower().startswith(c.lower()) for c in children):
                return {c["label"]: v for c, v in zip(cols, sub.get("numbers") or []) if c["type"] == "annual"}
    return {}


def _labels(payload: dict) -> list[str]:
    sec = (payload.get("sections") or {}).get("profit-loss") or {}
    return [c["label"] for c in sec.get("columns", []) if c["type"] == "annual"][-YEARS:]


def _fmt(v: Optional[float], kind: str) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "–"
    if kind == "pct":
        return f"{v:.1f}%"
    if kind == "x":
        return f"{v:.2f}x"
    if kind == "days":
        return f"{v:.0f}"
    if kind == "cr":
        return fmt_num(v, 0)
    if kind == "inr":
        return f"₹{v:.2f}"
    return str(v)


def _table(labels: list[str], rows: list[tuple[str, dict, str]]) -> dict:
    out = []
    for name, series, kind in rows:
        vals = [series.get(l) for l in labels]
        if all(v is None for v in vals):
            continue
        out.append({"metric": name, "values": [_fmt(v, kind) for v in vals],
                    "raw": [None if v is None else round(float(v), 4) for v in vals]})
    return {"columns": [fiscal_label(l) for l in labels], "rows": out}


def _equity(payload: dict) -> dict[str, Optional[float]]:
    eq, res = _annual(payload, "balance-sheet", "Equity Capital"), _annual(payload, "balance-sheet", "Reserves")
    return {l: (eq.get(l) or 0) + (res.get(l) or 0) if eq.get(l) is not None or res.get(l) is not None else None
            for l in set(eq) | set(res)}


# ------------------------------------------------------------------ 1. working capital
def working_capital(payload: dict, labels: list[str]) -> dict:
    rows = [("Debtor days (days to collect from customers)", _annual(payload, "ratios", "Debtor Days"), "days"),
            ("Inventory days (days stock is held)", _annual(payload, "ratios", "Inventory Days"), "days"),
            ("Payable days (days taken to pay suppliers)", _annual(payload, "ratios", "Days Payable"), "days"),
            ("Cash conversion cycle (days)", _annual(payload, "ratios", "Cash Conversion Cycle"), "days"),
            ("Working capital days", _annual(payload, "ratios", "Working Capital Days"), "days")]
    return _table(labels, rows)


# ------------------------------------------------------------------ 2. earnings quality
def earnings_quality(payload: dict, labels: list[str], is_fin: bool) -> dict:
    oi = _annual(payload, "profit-loss", "Other Income")
    pbt = _annual(payload, "profit-loss", "Profit before tax")
    tax = _annual(payload, "profit-loss", "Tax %")
    intr = _annual(payload, "profit-loss", "Interest")
    np_ = _annual(payload, "profit-loss", "Net Profit")
    cfo = _annual(payload, "cash-flow", "Cash from Operating Activity")
    oi_share = {l: safe_div(oi.get(l), pbt.get(l)) * 100 if oi.get(l) is not None and pbt.get(l) and pbt[l] > 0
                else None for l in labels}
    cover = {} if is_fin else {l: safe_div((pbt.get(l) or 0) + (intr.get(l) or 0), intr.get(l))
                               if intr.get(l) and intr[l] > 0 and pbt.get(l) is not None else None for l in labels}
    cash_ratio = {} if is_fin else {l: safe_div(cfo.get(l), np_.get(l)) if cfo.get(l) is not None and np_.get(l)
                                    and np_[l] > 0 else None for l in labels}
    rows = [("Other income (fees, treasury etc.) as % of profit before tax" if is_fin else
             "Other income as % of profit before tax", oi_share, "pct"),
            ("Tax rate %", tax, "pct")]
    if not is_fin:
        rows += [("Interest coverage (times interest is covered by profit)", cover, "x"),
                 ("Operating cash flow ÷ net profit", cash_ratio, "x")]
    return _table(labels, rows)


# ------------------------------------------------------------------ 3. cash & capex
def cash_capex(payload: dict, labels: list[str]) -> dict:
    cfo = _annual(payload, "cash-flow", "Cash from Operating Activity")
    capex = _schedule(payload, "cash-flow", "Cash from Investing", "Fixed assets purchased", "Purchase of fixed")
    capex = {l: abs(v) for l, v in capex.items() if v is not None}
    fcf_row = _annual(payload, "cash-flow", "Free Cash Flow")
    sales = _annual(payload, "profit-loss", "Sales", "Revenue")
    fcf = {}
    for l in labels:
        if fcf_row.get(l) is not None:
            fcf[l] = fcf_row[l]
        elif cfo.get(l) is not None and capex.get(l) is not None:
            fcf[l] = cfo[l] - capex[l]
    margin = {l: safe_div(fcf.get(l), sales.get(l)) * 100 if fcf.get(l) is not None and sales.get(l) else None
              for l in labels}
    t = _table(labels, [("Operating cash flow (₹ crore)", cfo, "cr"),
                        ("Capital spending on fixed assets (₹ crore)", capex, "cr"),
                        ("Free cash flow (₹ crore)", fcf, "cr"),
                        ("Free cash flow as % of sales", margin, "pct")])
    t["fcf_source"] = "Screener's Free Cash Flow row" if fcf_row else (
        "operating cash flow minus fixed assets purchased" if capex else "not available")
    return t


# ------------------------------------------------------------------ 4. DuPont
def dupont(payload: dict, labels: list[str]) -> dict:
    np_ = _annual(payload, "profit-loss", "Net Profit")
    sales = _annual(payload, "profit-loss", "Sales", "Revenue")
    ta = _annual(payload, "balance-sheet", "Total Assets")
    eq = _equity(payload)
    margin, turn, mult, roe = {}, {}, {}, {}
    for l in labels:
        if np_.get(l) is not None and sales.get(l):
            margin[l] = np_[l] / sales[l] * 100
        if sales.get(l) is not None and ta.get(l):
            turn[l] = sales[l] / ta[l]
        if ta.get(l) and eq.get(l):
            mult[l] = ta[l] / eq[l]
        if l in margin and l in turn and l in mult:
            roe[l] = margin[l] * turn[l] * mult[l]
    return _table(labels, [("Net profit margin %", margin, "pct"), ("× Asset turnover (sales ÷ total assets)", turn, "x"),
                           ("× Equity multiplier (total assets ÷ equity)", mult, "x"),
                           ("= Return on equity % (year-end figures)", roe, "pct")])


# ------------------------------------------------------------------ 5. Piotroski F-score
def piotroski(payload: dict) -> dict:
    """Nine yes/no tests on the last two fiscal years (Piotroski, 2000). Tests that cannot be done from Screener
    data are shown as 'not available' and left out of the denominator - never guessed."""
    np_ = _annual(payload, "profit-loss", "Net Profit")
    sales = _annual(payload, "profit-loss", "Sales", "Revenue")
    opm = _annual(payload, "profit-loss", "OPM %")
    ta = _annual(payload, "balance-sheet", "Total Assets")
    debt = _annual(payload, "balance-sheet", "Borrowings", "Borrowing")
    eqc = _annual(payload, "balance-sheet", "Equity Capital")
    cfo = _annual(payload, "cash-flow", "Cash from Operating Activity")
    labels = [l for l in _labels(payload) if np_.get(l) is not None]
    if len(labels) < 2:
        return {"available": False, "reason": "needs two full years of results"}
    cur, prev = labels[-1], labels[-2]
    C, P = fiscal_label(cur), fiscal_label(prev)
    tests = []

    def add(name: str, ok: Optional[bool], evidence: str) -> None:
        tests.append({"test": name, "result": None if ok is None else bool(ok), "evidence": evidence})

    roa_c = safe_div(np_.get(cur), ta.get(cur))
    roa_p = safe_div(np_.get(prev), ta.get(prev))
    add("Profitable (net profit above zero)", np_[cur] > 0, f"{C} net profit ₹{fmt_num(np_[cur], 0)} Cr")
    add("Positive operating cash flow", None if cfo.get(cur) is None else cfo[cur] > 0,
        f"{C} operating cash flow ₹{fmt_num(cfo[cur], 0)} Cr" if cfo.get(cur) is not None else "not reported")
    add("Return on assets improved", None if roa_c is None or roa_p is None else roa_c > roa_p,
        f"{P} {roa_p * 100:.2f}% → {C} {roa_c * 100:.2f}%" if roa_c is not None and roa_p is not None else "–")
    add("Cash flow higher than profit (good earnings quality)",
        None if cfo.get(cur) is None else cfo[cur] > np_[cur],
        f"cash ₹{fmt_num(cfo[cur], 0)} Cr vs profit ₹{fmt_num(np_[cur], 0)} Cr" if cfo.get(cur) is not None else "–")
    lev_c = safe_div(debt.get(cur), ta.get(cur))
    lev_p = safe_div(debt.get(prev), ta.get(prev))
    add("Debt fell as a share of assets", None if lev_c is None or lev_p is None else lev_c <= lev_p,
        f"{P} {lev_p * 100:.1f}% → {C} {lev_c * 100:.1f}%" if lev_c is not None and lev_p is not None else "–")
    add("Short-term liquidity (current ratio) improved", None,
        "not available: Screener does not split current assets and liabilities")
    add("No new shares issued", None if eqc.get(cur) is None or eqc.get(prev) is None else eqc[cur] <= eqc[prev] * 1.01,
        f"equity capital ₹{fmt_num(eqc[prev], 0)} → ₹{fmt_num(eqc[cur], 0)} Cr (a bonus issue also raises this)"
        if eqc.get(cur) is not None and eqc.get(prev) is not None else "–")
    add("Operating margin improved (used in place of gross margin)",
        None if opm.get(cur) is None or opm.get(prev) is None else opm[cur] > opm[prev],
        f"{P} {opm[prev]:.0f}% → {C} {opm[cur]:.0f}%" if opm.get(cur) is not None and opm.get(prev) is not None else
        "not reported (e.g. banks)")
    at_c, at_p = safe_div(sales.get(cur), ta.get(cur)), safe_div(sales.get(prev), ta.get(prev))
    add("Asset turnover improved", None if at_c is None or at_p is None else at_c > at_p,
        f"{P} {at_p:.2f}x → {C} {at_c:.2f}x" if at_c is not None and at_p is not None else "–")
    done = [t for t in tests if t["result"] is not None]
    score = sum(1 for t in done if t["result"])
    out_of = len(done)
    share = score / out_of if out_of else 0
    band = "strong" if share >= 7 / 9 else ("average" if share >= 4 / 9 else "weak")
    return {"available": True, "score": score, "out_of": out_of, "band": band, "year": C, "compared_with": P,
            "tests": tests}


# ------------------------------------------------------------------ 6. red flags
def red_flags(payload: dict, m: dict, h: dict, sup: Optional[dict], is_fin: bool) -> dict:
    """Each rule states what it looked for; 'flags' lists the ones that fired, with the numbers that fired them."""
    labels = _labels(payload)
    flags, checked = [], []

    def rule(name: str, fired: Optional[bool], evidence: str, level: str = "watch") -> None:
        if fired is None:
            return
        checked.append(name)
        if fired:
            flags.append({"flag": name, "evidence": evidence, "level": level})

    sales = _annual(payload, "profit-loss", "Sales", "Revenue")
    np_ = _annual(payload, "profit-loss", "Net Profit")
    cfo = _annual(payload, "cash-flow", "Cash from Operating Activity")
    debt = _annual(payload, "balance-sheet", "Borrowings", "Borrowing")
    eq = _equity(payload)
    eqc = _annual(payload, "balance-sheet", "Equity Capital")
    dd = _annual(payload, "ratios", "Debtor Days")
    wc = _annual(payload, "ratios", "Working Capital Days")
    last3 = labels[-3:]
    if len(labels) >= 3:
        l0, l2 = labels[-3], labels[-1]
        if not is_fin and dd.get(l0) is not None and dd.get(l2) is not None:
            rule("Customers are taking longer to pay", dd[l2] > dd[l0] + 15 and dd[l2] > dd[l0] * 1.25,
                 f"debtor days {dd[l0]:.0f} in {fiscal_label(l0)} → {dd[l2]:.0f} in {fiscal_label(l2)}")
        if not is_fin and wc.get(l0) is not None and wc.get(l2) is not None:
            rule("More money is tied up in working capital", wc[l2] > wc[l0] + 20 and wc[l2] > wc[l0] * 1.3,
                 f"working capital days {wc[l0]:.0f} → {wc[l2]:.0f}")
        if not is_fin and all(cfo.get(l) is not None and np_.get(l) is not None for l in last3):
            c, p = sum(cfo[l] for l in last3), sum(np_[l] for l in last3)
            rule("Reported profit is not turning into cash", p > 0 and c < 0.6 * p,
                 f"3-year operating cash flow ₹{fmt_num(c, 0)} Cr vs net profit ₹{fmt_num(p, 0)} Cr "
                 f"({c / p:.2f}x)" if p else "", "high")
        if all(sales.get(l) is not None and np_.get(l) is not None for l in (labels[-2], labels[-1])):
            a, b = labels[-2], labels[-1]
            rule("Profit grew while operating cash flow fell",
                 None if is_fin or cfo.get(a) is None or cfo.get(b) is None else
                 (np_[b] > np_[a] and cfo[b] < cfo[a] * 0.8),
                 f"{fiscal_label(b)}: profit {pct_change(np_[a], np_[b]):+.1f}%, operating cash flow "
                 f"{pct_change(cfo[a], cfo[b]):+.1f}%" if cfo.get(a) and cfo.get(b) is not None else "")
    if not is_fin and len(labels) >= 3:
        l0, l2 = labels[-3], labels[-1]
        if debt.get(l0) is not None and debt.get(l2) is not None and eq.get(l0) and eq.get(l2):
            dg, eg = pct_change(debt[l0], debt[l2]) if debt[l0] else None, pct_change(eq[l0], eq[l2])
            rule("Debt is growing much faster than equity",
                 None if dg is None else (dg > 50 and dg > 2 * max(eg or 0, 1) and debt[l2] > 0.3 * eq[l2]),
                 f"over 2 years debt {dg:+.0f}% vs equity {eg:+.0f}%" if dg is not None else "")
    eqt = h.get("earnings_quality", {})
    for row in eqt.get("rows", []):
        last = next((v for v in reversed(row["raw"]) if v is not None), None)
        if last is None:
            continue
        if row["metric"].startswith("Other income"):
            if is_fin:                       # for lenders fees and treasury income are core business
                continue
            rule("A large part of profit comes from other income (not the core business)", last > 25,
                 f"other income = {last:.0f}% of profit before tax in the latest year")
        elif row["metric"].startswith("Interest coverage"):
            rule("Profit covers interest less than 2 times", last < 2,
                 f"interest coverage {last:.2f}x in the latest year", "high")
        elif row["metric"].startswith("Tax rate"):
            rule("Unusual tax rate (below 15% or above 40%)", last < 15 or last > 40,
                 f"tax rate {last:.0f}% in the latest year")
    if len(labels) >= 2 and eqc.get(labels[-2]) and eqc.get(labels[-1]) is not None:
        a, b = eqc[labels[-2]], eqc[labels[-1]]
        rule("New shares issued (existing holders diluted)", b > a * 1.05,
             f"equity capital ₹{fmt_num(a, 0)} → ₹{fmt_num(b, 0)} Cr (could also be a bonus issue)")
    holders = (m.get("shareholding") or {}).get("holders") or {}
    pr = next((v for k, v in holders.items() if k.lower().startswith("promoter")), None) or {}
    if pr.get("chg_4q") is not None:
        rule("Promoters reduced their holding", pr["chg_4q"] < -2,
             f"promoter holding {pr['chg_4q']:+.2f} percentage points over 4 quarters")
    for it in (sup or {}).get("items", []):
        name = (it.get("metric") or "").lower()
        num = re.search(r"-?\d+(\.\d+)?", str(it.get("value") or ""))
        if not num:
            continue
        v = float(num.group(0))
        if "pledge" in name:
            rule("Promoter shares are pledged", v > 10, f"pledged {v:.1f}% ({it.get('source')})", "high")
        elif "gross npa" in name:
            rule("High bad loans (gross NPA above 5%)", v > 5, f"gross NPA {v:.2f}% ({it.get('source')})", "high")
        elif "capital adequacy" in name or "crar" in name:
            rule("Thin capital buffer (CRAR below 13%)", v < 13, f"CRAR {v:.1f}% ({it.get('source')})", "high")
    return {"flags": flags, "checked": checked}


# ------------------------------------------------------------------ 7. price risk
def price_risk(payload: dict, sup: Optional[dict]) -> dict:
    prices = [(date.fromisoformat(str(p["date"])[:10]), float(p["close"]))
              for p in payload.get("price_history") or [] if p.get("close")]
    out: dict[str, Any] = {}
    if len(prices) >= 30:
        last_d = prices[-1][0]
        gaps = [(b[0] - a[0]).days for a, b in zip(prices[-120:], prices[-119:])]
        per_year = 252 if statistics.median(gaps) <= 1.5 else (52 if statistics.median(gaps) <= 8 else 12)
        for key, days in (("1y", 365), ("3y", 365 * 3)):
            win = [c for d, c in prices if d >= last_d - timedelta(days=days)]
            if len(win) < 20 or prices[0][0] > last_d - timedelta(days=days - 10):
                continue
            rets = [math.log(b / a) for a, b in zip(win, win[1:]) if a > 0 and b > 0]
            if key == "1y" and len(rets) > 10:
                out["volatility_1y_pct"] = statistics.pstdev(rets) * math.sqrt(per_year) * 100
            peak, mdd = win[0], 0.0
            for c in win:
                peak = max(peak, c)
                mdd = min(mdd, c / peak - 1)
            out[f"max_drawdown_{key}_pct"] = mdd * 100
        out["as_of"] = last_d.isoformat()
    for it in (sup or {}).get("items", []):
        if (it.get("metric") or "").lower().startswith("beta"):
            num = re.search(r"-?\d+(\.\d+)?", str(it.get("value")))
            if num:
                out["beta"] = float(num.group(0))
                out["beta_source"] = it.get("source")
    rows = []
    if "volatility_1y_pct" in out:
        rows.append(["Price volatility (1 year, annualised)", f"{out['volatility_1y_pct']:.1f}%",
                     "how much the share price swings; Nifty 50 is typically 12–18%"])
    if "max_drawdown_1y_pct" in out:
        rows.append(["Largest fall from a peak (1 year)", f"{out['max_drawdown_1y_pct']:.1f}%",
                     "worst drop a buyer at the top would have seen"])
    if "max_drawdown_3y_pct" in out:
        rows.append(["Largest fall from a peak (3 years)", f"{out['max_drawdown_3y_pct']:.1f}%", ""])
    if "beta" in out:
        rows.append(["Beta vs the market", f"{out['beta']:.2f}",
                     f"1 = moves with the market, above 1 = swings more ({out.get('beta_source')})"])
    out["rows"] = rows
    return out


# ------------------------------------------------------------------ 8. corporate actions
_ACTION_RX = re.compile(r"buy[- ]?back|bonus|split|sub[- ]?division|rights issue|dividend|record date|demerger|"
                        r"merger|amalgamation", re.I)


def corporate_actions(payload: dict, labels: list[str]) -> dict:
    eps = _annual(payload, "profit-loss", "EPS in Rs", "EPS")
    payout = _annual(payload, "profit-loss", "Dividend Payout %")
    dps = {l: eps[l] * payout[l] / 100 for l in labels if eps.get(l) is not None and payout.get(l) is not None}
    table = _table(labels, [("Dividend per share (EPS × payout, ₹)", dps, "inr"),
                            ("Dividend payout %", payout, "pct")])
    out: dict[str, Any] = {"dividends": table, "yahoo": {}, "filings": []}
    for a in (payload.get("documents") or {}).get("announcements", [])[:40]:
        if _ACTION_RX.search(a.get("title", "") + " " + (a.get("summary") or "")):
            out["filings"].append({"date": (a.get("date") or "")[:10], "title": a["title"], "url": a.get("url")})
    sym = (payload.get("meta") or {}).get("nse_symbol")
    if sym:
        try:
            import yfinance as yf

            t = yf.Ticker(f"{sym}.NS")
            cutoff = date.today() - timedelta(days=365 * 5)
            divs = getattr(t, "dividends", None)
            if divs is not None and len(divs):
                by_year: dict[int, float] = {}
                for ts, v in divs.items():
                    d = ts.date() if hasattr(ts, "date") else ts
                    if d >= cutoff:
                        by_year[d.year] = by_year.get(d.year, 0) + float(v)
                out["yahoo"]["dividends_by_year"] = [{"year": y, "amount": round(v, 2)} for y, v in sorted(by_year.items())]
            spl = getattr(t, "splits", None)
            if spl is not None and len(spl):
                out["yahoo"]["splits"] = [{"date": (ts.date() if hasattr(ts, "date") else ts).isoformat(),
                                           "ratio": float(v)} for ts, v in spl.items()
                                          if (ts.date() if hasattr(ts, "date") else ts) >= cutoff - timedelta(days=365 * 5)]
        except Exception as e:  # noqa: BLE001 - Yahoo is optional
            out["yahoo"]["error"] = f"{type(e).__name__}"
    return out


# ------------------------------------------------------------------ 9. documents
def documents(payload: dict) -> dict:
    docs = payload.get("documents") or {}
    ratings = []
    for r in (docs.get("credit_ratings") or [])[:4]:
        agency = next((a for a in ("CRISIL", "ICRA", "CARE", "India Ratings", "Fitch", "Brickwork", "Acuite", "Infomerics")
                       if a.lower() in (r.get("title", "") + " " + r.get("meta", "") + " " + r.get("url", "")).lower()), "")
        ratings.append({"title": r.get("title"), "detail": r.get("meta"), "agency": agency, "url": r.get("url")})
    ar = sorted(docs.get("annual_reports") or [], key=lambda x: x.get("year") or 0, reverse=True)[:2]
    calls = (docs.get("concalls") or [])[:2]
    return {"credit_ratings": ratings, "annual_reports": ar, "concalls": calls}


# ------------------------------------------------------------------ main
_FIN_RX = re.compile(r"\bbank|nbfc|non banking|finance|financial institution|housing finance|insurance|"
                     r"asset management|broking|stock exchange", re.I)


def is_financial(payload: dict, m: dict) -> bool:
    """Banks, NBFCs, insurers and similar: working capital, capex, Piotroski and interest cover do not apply."""
    if m.get("company_type") == "bank_or_nbfc":
        return True
    meta = payload.get("meta") or {}
    text = " ".join(str(meta.get(k) or "") for k in ("broad_industry", "industry", "broad_sector"))
    return bool(_FIN_RX.search(text))


def build_health(payload: dict, m: dict, sup: Optional[dict] = None) -> dict:
    is_fin = is_financial(payload, m)
    labels = _labels(payload)
    h: dict[str, Any] = {"is_financial": is_fin, "years": [fiscal_label(l) for l in labels]}
    parts = [("working_capital", lambda: {} if is_fin else working_capital(payload, labels)),
             ("earnings_quality", lambda: earnings_quality(payload, labels, is_fin)),
             ("cash_capex", lambda: {} if is_fin else cash_capex(payload, labels)),
             ("dupont", lambda: dupont(payload, labels)),
             ("piotroski", lambda: {"available": False, "reason": "not meant for banks and NBFCs"} if is_fin
              else piotroski(payload)),
             ("risk", lambda: price_risk(payload, sup)),
             ("actions", lambda: corporate_actions(payload, labels)),
             ("documents", lambda: documents(payload))]
    for key, fn in parts:
        try:
            h[key] = fn()
        except Exception as e:  # noqa: BLE001 - one part failing must not stop the report
            log.warning("health part %s failed: %s", key, e)
            h[key] = {"error": f"{type(e).__name__}: {e}"}
    try:
        h["red_flags"] = red_flags(payload, m, h, sup, is_fin)
    except Exception as e:  # noqa: BLE001
        h["red_flags"] = {"flags": [], "checked": [], "error": str(e)}
    h["not_included"] = [
        "Altman Z-score: needs current assets and current liabilities, which Screener does not split out.",
        "Segment revenue, management guidance, contingent liabilities and related-party deals: only in annual "
        "reports (links below).",
    ]
    return h


def for_llm(h: dict) -> dict:
    """Compact, numbers-only view for the AI writer (so it may mention them; the fact-check then allows them)."""
    def last(t: dict) -> dict:
        out = {}
        for r in (t or {}).get("rows", []):
            pairs = [(c, v) for c, v in zip(t["columns"], r["raw"]) if v is not None]
            if pairs:
                out[r["metric"]] = {"latest_year": pairs[-1][0], "latest": pairs[-1][1],
                                    "first_year": pairs[0][0], "first": pairs[0][1]}
        return out
    p = h.get("piotroski") or {}
    return {
        "working_capital": last(h.get("working_capital")),
        "earnings_quality": last(h.get("earnings_quality")),
        "cash_and_capex": last(h.get("cash_capex")),
        "dupont_roe": last(h.get("dupont")),
        "piotroski_f_score": {"score": p.get("score"), "out_of": p.get("out_of"), "band": p.get("band"),
                              "year": p.get("year")} if p.get("available") else None,
        "warning_signs": [{"flag": f["flag"], "evidence": f["evidence"]} for f in (h.get("red_flags") or {}).get("flags", [])],
        "price_risk": {k: round(v, 2) for k, v in (h.get("risk") or {}).items() if isinstance(v, (int, float))},
    }
