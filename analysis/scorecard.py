"""Transparent, rule-based scorecard -> overall score (0-100) and stance.

Stance: Positive (>= 65) | Neutral (45-64.9) | Cautious (< 45)
It is NOT a buy/sell recommendation and has no target price.
"""
from __future__ import annotations

from typing import Optional

from core.utils import fmt_pct

WEIGHTS = {
    "Growth": 20,
    "Profitability": 20,
    "Balance sheet": 15,
    "Cash flow quality": 15,
    "Valuation": 15,
    "Momentum & ownership": 15,
}


def _band(value: Optional[float], bands: list[tuple[float, float]], default: float = 5) -> float:
    """bands: list of (upper_threshold, score) in ascending threshold order; last is catch-all."""
    if value is None:
        return default
    for upper, score in bands:
        if value < upper:
            return score
    return bands[-1][1]


def _first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def build_scorecard(m: dict) -> dict:
    g, p, b, c, v = m["growth"], m["profitability"], m["balance_sheet"], m["cash_flow"], m["valuation"]
    q, sh, pp = m["quarterly"], m["shareholding"], m["price_performance"]
    is_fin = m["company_type"] == "bank_or_nbfc"
    items = []

    # 1. Growth
    growth_bands = [(0, 1), (5, 3), (10, 5), (15, 7), (20, 8), (1e9, 9)]
    rev5 = _first(g.get("screener_sales_5"), g.get("revenue_cagr_5y"))
    pat5 = _first(g.get("screener_profit_5"), g.get("profit_cagr_5y"))
    scores = [_band(x, growth_bands) for x in (rev5, pat5) if x is not None]
    s = sum(scores) / len(scores) if scores else 5
    why = [f"5-yr revenue CAGR {fmt_pct(rev5)}", f"5-yr profit CAGR {fmt_pct(pat5)}"]
    ttm_pg = g.get("screener_profit_ttm")
    if ttm_pg is not None and ttm_pg < 0:
        s -= 1
        why.append(f"TTM profit growth is negative ({fmt_pct(ttm_pg)})")
    if q.get("profit_yoy") is not None:
        why.append(f"latest quarter profit YoY {fmt_pct(q['profit_yoy'])}")
    items.append(("Growth", s, why))

    # 2. Profitability
    roe = _first(p.get("roe_current"), p.get("roe_avg_5y"))
    roe_s = _band(roe, [(8, 2), (12, 4), (15, 6), (20, 8), (1e9, 9)])
    why = [f"ROE {fmt_pct(roe)}"]
    if not is_fin and p.get("roce_current") is not None:
        roce_s = _band(p["roce_current"], [(8, 2), (12, 4), (15, 6), (20, 8), (1e9, 9)])
        s = (roe_s + roce_s) / 2
        why.append(f"ROCE {fmt_pct(p['roce_current'])}")
    else:
        s = roe_s
    if p.get("margin_latest_fy") is not None:
        why.append(f"{p.get('margin_label', 'margin')} latest FY {fmt_pct(p['margin_latest_fy'], 0)}")
    items.append(("Profitability", s, why))

    # 3. Balance sheet
    if is_fin:
        lev = b.get("leverage_assets_to_equity")
        s = _band(lev, [(8, 8), (10, 7), (12, 6), (15, 4), (1e9, 3)])
        why = [f"assets / net worth {lev:.1f}x" if lev else "leverage not available"]
        if b.get("deposits_yoy") is not None:
            why.append(f"deposits growth {fmt_pct(b['deposits_yoy'])} YoY")
    else:
        de = b.get("debt_to_equity")
        s = _band(de, [(0.1, 9), (0.5, 7), (1.0, 5), (2.0, 3), (1e9, 1)])
        why = [f"debt / equity {de:.2f}x" if de is not None else "debt / equity not available"]
        if b.get("debt_to_equity_5y_ago") is not None and de is not None:
            why.append(f"was {b['debt_to_equity_5y_ago']:.2f}x five years ago")
    items.append(("Balance sheet", s, why))

    # 4. Cash flow quality
    if is_fin:
        s, why = 5, ["operating cash flow is not a meaningful quality signal for lenders (deposit/loan flows)"]
    else:
        conv = c.get("cfo_to_pat_5y")
        s = _band(conv, [(0, 1), (0.5, 3), (0.8, 5), (1.0, 7), (1e9, 9)])
        why = [f"5-yr cumulative CFO / net profit {conv:.2f}x" if conv is not None else "cash-flow data not available"]
        if c.get("fcf_sum_5y") is not None:
            why.append(f"5-yr cumulative free cash flow ₹{c['fcf_sum_5y']:,.0f} Cr")
    items.append(("Cash flow quality", s, why))

    # 5. Valuation (relative to own history and peers)
    parts, why = [], []
    if v.get("pe") in (None, 0):
        parts.append(3)
        why.append("P/E not meaningful (losses or not reported)")
    else:
        if v.get("pe_vs_median") is not None:
            parts.append(_band(v["pe_vs_median"], [(0.8, 8), (1.0, 7), (1.2, 5), (1.5, 4), (1e9, 2)]))
            why.append(f"P/E {v['pe']:.1f} vs own 5-yr median {v['median_pe_5y']:.1f}")
        if v.get("pe_vs_peer_median") is not None:
            parts.append(_band(v["pe_vs_peer_median"], [(0.8, 8), (1.0, 7), (1.2, 5), (1.5, 4), (1e9, 2)]))
            why.append(f"peer median P/E {v['peer_median_pe']:.1f}")
    s = sum(parts) / len(parts) if parts else 5
    items.append(("Valuation", s, why or ["insufficient valuation history"]))

    # 6. Momentum & ownership
    s, why = 5.0, []
    if pp.get("vs_dma200_pct") is not None:
        s += 1.5 if pp["vs_dma200_pct"] > 0 else -1.5
        why.append(f"price {fmt_pct(pp['vs_dma200_pct'])} vs 200-DMA")
    if pp.get("return_1Y") is not None:
        s += 1 if pp["return_1Y"] > 10 else (-1 if pp["return_1Y"] < -10 else 0)
        why.append(f"1-yr return {fmt_pct(pp['return_1Y'])}")
    holders = sh.get("holders", {})
    inst = [holders.get(k, {}).get("chg_4q") for k in ("FIIs", "DIIs")]
    inst = [x for x in inst if x is not None]
    if inst:
        chg = sum(inst)
        s += 1 if chg > 1 else (-1 if chg < -1 else 0)
        why.append(f"FII+DII holding change over 4 quarters {chg:+.2f} pts")
    prom = holders.get("Promoters", {}).get("chg_4q")
    if prom is not None:
        s += -1 if prom < -2 else 0
        why.append(f"promoter holding change over 4 quarters {prom:+.2f} pts")
    items.append(("Momentum & ownership", max(0, min(10, s)), why or ["price / ownership data not available"]))

    scorecard = []
    total = 0.0
    for name, score, why in items:
        score = round(max(0.0, min(10.0, score)), 1)
        w = WEIGHTS[name]
        total += score / 10 * w
        scorecard.append({"name": name, "score": score, "weight": w, "rationale": why})
    total = round(total, 1)
    stance = "Positive" if total >= 65 else ("Neutral" if total >= 45 else "Cautious")
    return {"score": total, "stance": stance, "items": scorecard}
