"""Tests for analysis/health.py: each value is checked against a hand calculation on tests/sample_payload.py.

Run:  python tests/test_health.py      (or)      python -m pytest tests -q
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis import health as Hm  # noqa: E402
from analysis.metrics import compute_metrics  # noqa: E402
from sample_payload import payload  # noqa: E402


def _h(**over):
    p = payload(**over)
    m = compute_metrics(p)
    return Hm.build_health(p, m, {"items": []}), p, m


def _row(table, start):
    return next(r for r in table["rows"] if r["metric"].startswith(start))


def test_working_capital_table_matches_screener_ratios():
    h, _, _ = _h()
    assert h["working_capital"]["columns"][-1] == "FY26"
    assert _row(h["working_capital"], "Debtor days")["raw"][-1] == 95


def test_earnings_quality_by_hand():
    h, _, _ = _h()
    eq = h["earnings_quality"]
    assert abs(_row(eq, "Other income")["raw"][-1] - 40 / 240 * 100) < 0.01       # 16.67%
    assert abs(_row(eq, "Interest coverage")["raw"][-1] - (240 + 45) / 45) < 0.01  # 6.33x
    assert abs(_row(eq, "Operating cash flow")["raw"][-1] - 80 / 180) < 0.01       # 0.44x


def test_free_cash_flow_from_capex_breakdown():
    h, _, _ = _h()
    cc = h["cash_capex"]
    assert _row(cc, "Capital spending")["raw"][-1] == 180
    assert _row(cc, "Free cash flow (")["raw"][-1] == 80 - 180
    assert cc["fcf_source"].startswith("operating cash flow minus")


def test_dupont_multiplies_back_to_roe():
    h, _, _ = _h()
    d = h["dupont"]
    margin, turn, mult, roe = (_row(d, x)["raw"][-1] for x in ("Net profit", "× Asset", "× Equity", "= Return"))
    assert abs(margin * turn * mult - roe) < 0.01
    assert abs(roe - 180 / 1150 * 100) < 0.05        # net profit / (equity capital + reserves)


def test_piotroski_by_hand():
    h, _, _ = _h()
    p = h["piotroski"]
    res = {t["test"]: t["result"] for t in p["tests"]}
    assert res["Profitable (net profit above zero)"] is True
    assert res["Cash flow higher than profit (good earnings quality)"] is False      # 80 < 180
    assert res["Debt fell as a share of assets"] is False                            # 520/1820 -> 680/2130
    assert res["Short-term liquidity (current ratio) improved"] is None             # never guessed
    assert p["out_of"] == 8 and 0 <= p["score"] <= 8


def test_red_flags_fire_with_evidence():
    h, _, _ = _h()
    names = [f["flag"] for f in h["red_flags"]["flags"]]
    assert "Customers are taking longer to pay" in names          # 60 -> 95 days
    assert "Reported profit is not turning into cash" in names    # 300 cash vs 504 profit over 3 years (0.60x)
    assert "Promoters reduced their holding" in names             # 60 -> 56.5
    assert all(f["evidence"] for f in h["red_flags"]["flags"])


def test_no_false_flags_on_a_healthy_company():
    p = payload()
    p["sections"]["ratios"]["rows"][0]["numbers"] = [55, 56, 57, 57, 58, 58]          # debtor days steady
    p["sections"]["ratios"]["rows"][4]["numbers"] = [60, 61, 61, 62, 62, 63]          # WC days steady
    p["sections"]["cash-flow"]["rows"][0]["numbers"] = [120, 140, 160, 175, 190, 205]  # cash > profit
    p["shareholding"]["quarterly"]["rows"][0]["numbers"] = [60] * 5
    p["sections"]["balance-sheet"]["rows"][2]["numbers"] = [300, 300, 310, 310, 320, 320]  # debt steady
    m = compute_metrics(p)
    h = Hm.build_health(p, m, {"items": []})
    assert h["red_flags"]["flags"] == [], h["red_flags"]["flags"]


def test_price_risk_drawdown_detected():
    h, _, _ = _h()
    r = h["risk"]
    assert r["max_drawdown_3y_pct"] < -30
    assert 0 < r["volatility_1y_pct"] < 200


def test_actions_and_documents():
    h, _, _ = _h()
    dps = _row(h["actions"]["dividends"], "Dividend per share")["raw"][-1]
    assert abs(dps - 18.0 * 25 / 100) < 0.001
    assert any("buyback" in f["title"].lower() for f in h["actions"]["filings"])
    assert not any("trading window" in f["title"].lower() for f in h["actions"]["filings"])
    assert h["documents"]["credit_ratings"][0]["agency"] == "CRISIL"
    assert h["documents"]["annual_reports"][0]["year"] == 2026


def test_banks_skip_non_bank_measures():
    p = payload()
    m = compute_metrics(p)
    m["company_type"] = "bank_or_nbfc"
    h = Hm.build_health(p, m, {"items": []})
    assert h["working_capital"] == {} and h["piotroski"]["available"] is False


def test_bank_detected_from_industry_too():
    p = payload()
    p["meta"]["broad_industry"], p["meta"]["industry"] = "Banks", "Private Sector Bank"
    m = compute_metrics(p)
    h = Hm.build_health(p, m, {"items": []})
    assert h["is_financial"] and h["piotroski"]["available"] is False


def test_bank_other_income_is_not_a_warning():
    p = payload()
    p["meta"]["broad_industry"] = "Banks"
    p["sections"]["profit-loss"]["rows"][4]["numbers"] = [300] * 7          # other income > profit before tax
    m = compute_metrics(p)
    h = Hm.build_health(p, m, {"items": []})
    assert not any("other income" in f["flag"].lower() for f in h["red_flags"]["flags"])


def test_missing_data_never_crashes():
    p = payload(sections={}, price_history=[], documents={}, shareholding={})
    m = compute_metrics(p)
    h = Hm.build_health(p, m, {"items": []})
    assert h["red_flags"]["flags"] == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {fn.__name__}  {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
