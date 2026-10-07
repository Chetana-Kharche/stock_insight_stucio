"""Deterministic financial metrics computed ONLY from scraped Screener data.

Nothing here is estimated or invented: every figure is either read from the payload
or calculated from it with a transparent formula.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean
from typing import Any, Optional

from core.utils import cagr, pct_change, safe_div


# ------------------------------------------------------------------ accessors
class Series:
    """A metric row as aligned (label, date, type, value) points."""

    def __init__(self, metric: str, points: list[tuple[str, Optional[str], str, Optional[float]]]):
        self.metric = metric
        self.points = points

    @property
    def annual(self) -> list[tuple[str, Optional[float]]]:
        return [(l, v) for l, d, t, v in self.points if t == "annual"]

    @property
    def quarterly(self) -> list[tuple[str, Optional[float]]]:
        return [(l, v) for l, d, t, v in self.points if t == "quarter"]

    @property
    def ttm(self) -> Optional[float]:
        for l, d, t, v in self.points:
            if t == "ttm":
                return v
        return None

    def values(self, kind: str = "annual") -> list[Optional[float]]:
        src = self.annual if kind == "annual" else self.quarterly
        return [v for _, v in src]

    def last(self, kind: str = "annual") -> Optional[float]:
        vals = [v for v in self.values(kind) if v is not None]
        return vals[-1] if vals else None

    def last_label(self, kind: str = "annual") -> Optional[str]:
        src = self.annual if kind == "annual" else self.quarterly
        for l, v in reversed(src):
            if v is not None:
                return l
        return None


def find_series(payload: dict, section: str, *names: str) -> Optional[Series]:
    sec = payload.get("sections", {}).get(section)
    if section.startswith("shareholding"):
        sec = payload.get("shareholding", {}).get(section.split("-", 1)[1])
    if not sec:
        return None
    wanted = [n.lower() for n in names]
    rows = sec.get("rows", [])
    for w in wanted:  # exact first, then prefix match
        for r in rows:
            if r["metric"].lower() == w:
                return _to_series(sec, r)
    for w in wanted:
        for r in rows:
            if r["metric"].lower().startswith(w):
                return _to_series(sec, r)
    return None


def _to_series(sec: dict, row: dict) -> Series:
    pts = [(c["label"], c["date"], c["type"], v) for c, v in zip(sec["columns"], row["numbers"])]
    return Series(row["metric"], pts)


def summary_value(payload: dict, name: str, second: bool = False) -> Optional[float]:
    for r in payload.get("summary_ratios", []):
        if r["name"].lower() == name.lower():
            return r["value2"] if second else r["value"]
    return None


def growth_range(payload: dict, title_start: str, period: str) -> Optional[float]:
    for g in payload.get("growth", []):
        if g["title"].lower().startswith(title_start.lower()):
            for it in g["rows"]:
                if it["period"].lower().startswith(period.lower()):
                    return it["value"]
    return None


def _series_cagr(vals: list[Optional[float]], years: int) -> Optional[float]:
    clean = [v for v in vals]
    if len(clean) <= years or clean[-1] is None or clean[-1 - years] is None:
        return None
    return cagr(clean[-1 - years], clean[-1], years)


def _avg(vals: list[Optional[float]]) -> Optional[float]:
    v = [x for x in vals if x is not None]
    return mean(v) if v else None


# ------------------------------------------------------------------ price helpers
def _price_on_or_before(prices: list[dict], target: date) -> Optional[float]:
    best = None
    for p in prices:
        d = date.fromisoformat(str(p["date"])[:10])
        if d <= target and p.get("close") is not None:
            best = p["close"]
        elif d > target:
            break
    return best


def price_performance(prices: list[dict]) -> dict:
    prices = [p for p in prices if p.get("close") is not None]
    if not prices:
        return {}
    last = prices[-1]
    last_d = date.fromisoformat(str(last["date"])[:10])
    out: dict[str, Any] = {"last_close": last["close"], "as_of": last_d.isoformat(),
                           "dma50": last.get("dma50"), "dma200": last.get("dma200")}
    for key, days in (("1M", 30), ("3M", 91), ("6M", 182), ("1Y", 365), ("3Y", 365 * 3), ("5Y", 365 * 5 - 5)):
        base = _price_on_or_before(prices, last_d - timedelta(days=days))
        first_d = date.fromisoformat(str(prices[0]["date"])[:10])
        if base and (last_d - timedelta(days=days)) >= first_d:
            out[f"return_{key}"] = pct_change(base, last["close"])
    window = [p["close"] for p in prices if date.fromisoformat(str(p["date"])[:10]) >= last_d - timedelta(days=365)]
    if window:
        out["high_52w"], out["low_52w"] = max(window), min(window)
        out["from_52w_high_pct"] = pct_change(out["high_52w"], last["close"])
        out["from_52w_low_pct"] = pct_change(out["low_52w"], last["close"])
    if last.get("dma200"):
        out["vs_dma200_pct"] = pct_change(last["dma200"], last["close"])
    if last.get("dma50"):
        out["vs_dma50_pct"] = pct_change(last["dma50"], last["close"])
    return out


# ------------------------------------------------------------------ main
def compute_metrics(payload: dict) -> dict:
    m: dict[str, Any] = {}
    meta = payload.get("meta", {})
    is_fin = find_series(payload, "profit-loss", "Financing Profit") is not None
    m["company_type"] = "bank_or_nbfc" if is_fin else "non_financial"

    rev = find_series(payload, "profit-loss", "Sales", "Revenue")
    np_ = find_series(payload, "profit-loss", "Net Profit")
    eps = find_series(payload, "profit-loss", "EPS in Rs", "EPS")
    op = find_series(payload, "profit-loss", "Operating Profit", "Financing Profit")
    opm = find_series(payload, "profit-loss", "OPM %", "Financing Margin %")
    other_inc = find_series(payload, "profit-loss", "Other Income")
    payout = find_series(payload, "profit-loss", "Dividend Payout %")
    pbt = find_series(payload, "profit-loss", "Profit before tax")

    # ---- growth
    g: dict[str, Any] = {}
    if rev:
        vals = rev.values()
        g["revenue_latest_fy"] = rev.last()
        g["revenue_latest_fy_label"] = rev.last_label()
        g["revenue_ttm"] = rev.ttm
        for y in (3, 5, 10):
            g[f"revenue_cagr_{y}y"] = _series_cagr(vals, y)
        g["revenue_yoy_latest_fy"] = pct_change(vals[-2], vals[-1]) if len(vals) >= 2 else None
    if np_:
        vals = np_.values()
        g["profit_latest_fy"] = np_.last()
        g["profit_ttm"] = np_.ttm
        for y in (3, 5, 10):
            g[f"profit_cagr_{y}y"] = _series_cagr(vals, y)
        g["profit_yoy_latest_fy"] = pct_change(vals[-2], vals[-1]) if len(vals) >= 2 else None
    if eps:
        g["eps_latest_fy"] = eps.last()
        g["eps_ttm"] = eps.ttm
        g["eps_cagr_5y"] = _series_cagr(eps.values(), 5)
    for key, title in (("sales", "Compounded Sales Growth"), ("profit", "Compounded Profit Growth"),
                       ("price", "Stock Price CAGR"), ("roe", "Return on Equity")):
        for per in ("10", "5", "3", "TTM", "1 Year", "Last Year"):
            v = growth_range(payload, title, per)
            if v is not None:
                g[f"screener_{key}_{per.lower().replace(' ', '_')}"] = v
    m["growth"] = g

    # ---- quarterly
    q: dict[str, Any] = {}
    qrev = find_series(payload, "quarters", "Sales", "Revenue")
    qnp = find_series(payload, "quarters", "Net Profit")
    qopm = find_series(payload, "quarters", "OPM %", "Financing Margin %")
    if qrev and qrev.quarterly:
        labels = [l for l, _ in qrev.quarterly]
        rv = qrev.values("quarter")
        q["latest_quarter"] = labels[-1]
        q["revenue"] = rv[-1]
        q["revenue_qoq"] = pct_change(rv[-2], rv[-1]) if len(rv) >= 2 else None
        q["revenue_yoy"] = pct_change(rv[-5], rv[-1]) if len(rv) >= 5 else None
        if len(rv) >= 8 and None not in rv[-8:]:
            q["revenue_last4_vs_prev4"] = pct_change(sum(rv[-8:-4]), sum(rv[-4:]))
    if qnp and qnp.quarterly:
        nv = qnp.values("quarter")
        q["net_profit"] = nv[-1]
        q["profit_qoq"] = pct_change(nv[-2], nv[-1]) if len(nv) >= 2 else None
        q["profit_yoy"] = pct_change(nv[-5], nv[-1]) if len(nv) >= 5 else None
        if len(nv) >= 8 and None not in nv[-8:]:
            q["profit_last4_vs_prev4"] = pct_change(sum(nv[-8:-4]), sum(nv[-4:]))
    if qopm:
        ov = qopm.values("quarter")
        q["margin_label"] = qopm.metric
        q["margin_latest"] = ov[-1] if ov else None
        q["margin_year_ago"] = ov[-5] if len(ov) >= 5 else None
    m["quarterly"] = q

    # ---- profitability
    p: dict[str, Any] = {}
    if opm:
        p["margin_label"] = opm.metric
        p["margin_latest_fy"] = opm.last()
        p["margin_avg_5y"] = _avg(opm.values()[-5:])
    if rev and np_:
        nm = [safe_div(n, r) for n, r in zip(np_.values(), rev.values())]
        nm = [x * 100 if x is not None else None for x in nm]
        p["net_margin_latest_fy"] = nm[-1] if nm else None
        p["net_margin_avg_5y"] = _avg(nm[-5:])
    if other_inc and pbt:
        p["other_income_share_of_pbt"] = (safe_div(other_inc.last(), pbt.last()) or 0) * 100 if pbt.last() else None
    roe_s = find_series(payload, "ratios", "ROE %")
    roce_s = find_series(payload, "ratios", "ROCE %")
    p["roe_current"] = summary_value(payload, "ROE")
    p["roce_current"] = summary_value(payload, "ROCE")
    if roe_s:
        p["roe_history"] = roe_s.annual[-6:]
        p["roe_avg_5y"] = _avg(roe_s.values()[-5:])
    if roce_s:
        p["roce_history"] = roce_s.annual[-6:]
        p["roce_avg_5y"] = _avg(roce_s.values()[-5:])
    if payout:
        p["dividend_payout_latest"] = payout.last()
        p["dividend_payout_avg_5y"] = _avg(payout.values()[-5:])
    m["profitability"] = p

    # ---- balance sheet
    b: dict[str, Any] = {}
    eq_cap = find_series(payload, "balance-sheet", "Equity Capital")
    reserves = find_series(payload, "balance-sheet", "Reserves")
    borrow = find_series(payload, "balance-sheet", "Borrowings", "Borrowing")
    deposits = find_series(payload, "balance-sheet", "Deposits")
    tassets = find_series(payload, "balance-sheet", "Total Assets")
    invest = find_series(payload, "balance-sheet", "Investments")
    cwip = find_series(payload, "balance-sheet", "CWIP")
    if eq_cap and reserves:
        equity = [(e or 0) + (r or 0) if (e is not None or r is not None) else None
                  for e, r in zip(eq_cap.values(), reserves.values())]
        b["net_worth"] = equity[-1] if equity else None
        b["net_worth_label"] = eq_cap.last_label()
        b["net_worth_cagr_5y"] = _series_cagr(equity, 5)
        if borrow:
            b["debt"] = borrow.last()
            b["debt_to_equity"] = safe_div(borrow.last(), b["net_worth"])
            de_hist = [safe_div(d, e) for d, e in zip(borrow.values(), equity)]
            b["debt_to_equity_5y_ago"] = de_hist[-6] if len(de_hist) >= 6 else None
        if tassets:
            b["total_assets"] = tassets.last()
            b["leverage_assets_to_equity"] = safe_div(tassets.last(), b["net_worth"])
            b["total_assets_cagr_5y"] = _series_cagr(tassets.values(), 5)
    if deposits:
        dv = deposits.values()
        b["deposits"] = deposits.last()
        b["deposits_yoy"] = pct_change(dv[-2], dv[-1]) if len(dv) >= 2 else None
        b["deposits_cagr_5y"] = _series_cagr(dv, 5)
    if invest and tassets:
        b["investments_share_of_assets"] = (safe_div(invest.last(), tassets.last()) or 0) * 100
    if cwip:
        b["cwip"] = cwip.last()
    m["balance_sheet"] = b

    # ---- cash flow
    c: dict[str, Any] = {}
    cfo = find_series(payload, "cash-flow", "Cash from Operating Activity")
    cfi = find_series(payload, "cash-flow", "Cash from Investing Activity")
    fcf = find_series(payload, "cash-flow", "Free Cash Flow")
    if cfo:
        c["cfo_latest"] = cfo.last()
        c["cfo_label"] = cfo.last_label()
        if np_:
            cf5 = [v for v in cfo.values()[-5:] if v is not None]
            np5 = [v for v in np_.values()[-5:] if v is not None]
            c["cfo_to_pat_5y"] = safe_div(sum(cf5), sum(np5)) if cf5 and np5 else None
    if fcf:
        c["fcf_latest"] = fcf.last()
        c["fcf_sum_5y"] = sum(v for v in fcf.values()[-5:] if v is not None)
    elif cfo and cfi:
        c["cfo_plus_cfi_latest"] = (cfo.last() or 0) + (cfi.last() or 0)
    m["cash_flow"] = c

    # ---- efficiency (non-financials)
    e: dict[str, Any] = {}
    for key, name in (("debtor_days", "Debtor Days"), ("inventory_days", "Inventory Days"),
                      ("payable_days", "Days Payable"), ("cash_conversion_cycle", "Cash Conversion Cycle"),
                      ("working_capital_days", "Working Capital Days")):
        s = find_series(payload, "ratios", name)
        if s:
            e[key] = s.last()
            vals = s.values()
            e[f"{key}_5y_ago"] = vals[-6] if len(vals) >= 6 else None
    m["efficiency"] = e

    # ---- valuation
    v: dict[str, Any] = {}
    price = summary_value(payload, "Current Price")
    v["price"] = price
    v["market_cap_cr"] = summary_value(payload, "Market Cap")
    v["pe"] = summary_value(payload, "Stock P/E")
    v["book_value"] = summary_value(payload, "Book Value")
    v["pb"] = safe_div(price, v["book_value"])
    v["dividend_yield"] = summary_value(payload, "Dividend Yield")
    v["high_52w"] = summary_value(payload, "High / Low")
    v["low_52w"] = summary_value(payload, "High / Low", second=True)
    v["face_value"] = summary_value(payload, "Face Value")
    v["earnings_yield"] = (100 / v["pe"]) if v.get("pe") else None
    pe_hist = payload.get("pe_history") or {}
    med = pe_hist.get("Median PE") or []
    if med:
        v["median_pe_5y"] = med[-1][1]
        v["pe_vs_median"] = safe_div(v["pe"], v["median_pe_5y"])
    pe_series = [x[1] for x in (pe_hist.get("Price to Earning") or []) if x[1] is not None]
    if pe_series:
        v["pe_5y_min"], v["pe_5y_max"] = min(pe_series), max(pe_series)
    peers = payload.get("peers") or {}
    median = (peers.get("median") or {}).get("numbers") or {}
    for k, val in median.items():
        if k.upper().startswith("P/E"):
            v["peer_median_pe"] = val
            v["pe_vs_peer_median"] = safe_div(v["pe"], val)
        if k.upper().startswith("ROCE"):
            v["peer_median_roce"] = val
        if k.upper().startswith("DIV YLD"):
            v["peer_median_div_yield"] = val
    v["peer_count"] = len(peers.get("rows", []))
    m["valuation"] = v

    # ---- shareholding
    s_out: dict[str, Any] = {}
    shq = payload.get("shareholding", {}).get("quarterly")
    if shq:
        cols = [c["label"] for c in shq["columns"]]
        s_out["latest_period"] = cols[-1] if cols else None
        holders = {}
        for r in shq["rows"]:
            nums = r["numbers"]
            if not nums:
                continue
            holders[r["metric"]] = {
                "latest": nums[-1],
                "chg_1q": (nums[-1] - nums[-2]) if len(nums) >= 2 and None not in (nums[-1], nums[-2]) else None,
                "chg_4q": (nums[-1] - nums[-5]) if len(nums) >= 5 and None not in (nums[-1], nums[-5]) else None,
                "history": list(zip(cols, nums)),
            }
        s_out["holders"] = holders
    m["shareholding"] = s_out

    # ---- price
    m["price_performance"] = price_performance(payload.get("price_history") or [])

    m["pros"] = payload.get("pros", [])
    m["cons"] = payload.get("cons", [])
    m["meta"] = {k: meta.get(k) for k in ("name", "nse_symbol", "bse_code", "basis", "sector", "industry",
                                          "broad_sector", "broad_industry", "latest_period", "captured_at",
                                          "upcoming_result_date", "website")}
    return m
