"""Tests for analysis/guardrails.py - every case is a mistake an AI or a website could make.

Run:  python -m pytest tests/test_guardrails.py -q      (or)      python tests/test_guardrails.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import guardrails as G  # noqa: E402

DATA = {
    "metrics": {"growth": {"revenue_latest_fy": 92624, "profit_latest_fy": 13266, "revenue_cagr_5y": 8.04,
                           "eps_ttm": 13.36},
                "quarterly": {"revenue": 24479, "revenue_yoy": 10.62, "net_profit": 3356, "profit_yoy": 0.6},
                "valuation": {"price": 171.0, "pe": 12.8, "pb": 2.036, "dividend_yield": 6.44,
                              "median_pe_5y": 19.7},
                "profitability": {"roe_current": 15.5}},
    "model_projections": {"annual": [{"metric": "Sales", "projection": [{"period": "FY29E", "base": 101661,
                                                                          "low": 91982, "high": 112359}]}]},
    "supplementary_data_other_websites": {"items": [{"metric": "Analysts' average target price",
                                                     "value": "₹172.68", "source": "Yahoo Finance"}]},
    "recent_news_headlines": [{"title": "Wipro wins $500 million deal from US retailer", "website": "Mint"}],
    "shareholding": {"DIIs": {"latest": 41.75}},
    "model_projections_q": {"quarterly": [{"metric": "Net Profit", "projection": [{"value": 95580}]}]},
}
STANCE, SCORE = "Neutral", 60
SOURCES = ["Mint", "Economic Times", "Yahoo Finance", "NSE"]
M = {"valuation": {"pe": 12.8, "pb": 2.04, "dividend_yield": 6.44}, "profitability": {"roe_current": 15.5,
                                                                                      "roce_current": 17.8}}


def _allowed():
    return G.allowed_numbers(DATA, {"score": SCORE})


def _ok(text):
    allowed = _allowed()
    return all(G.is_supported(n, allowed) for n in G.numbers_in(text))


# ---------------------------------------------------------------- numbers
def test_exact_and_rounded_numbers_pass():
    assert _ok("FY26 revenue was ₹92,624 Cr and net profit ₹13,266 Cr.")
    assert _ok("Revenue grew 10.6% YoY in Q1FY27 to ₹24,479 Cr.")          # 10.62 rounded
    assert _ok("The 5-year revenue CAGR was 8.0% and the stock trades at 12.8x.")
    assert _ok("P/B is 2.04x and the dividend yield 6.44%.")


def test_unit_conversions_pass():
    assert _ok("FY29E model projection of ₹1.02 lakh crore.")              # 101661 crore
    assert _ok("Sales of about ₹92.6 thousand crore.")


def test_labels_are_not_figures():
    assert _ok("Over 5 years and 4 quarters, the 52-week low and the 200-DMA in FY27 and Q1 2026.")


def test_invented_numbers_fail():
    assert not _ok("Net profit was ₹14,900 Cr in FY26.")
    assert not _ok("Revenue grew 18.3% YoY.")
    assert not _ok("The stock trades at 25.4x earnings.")
    assert not _ok("Operating margin expanded to 21.7%.")


def _ok_ctx(text):
    allowed = _allowed()
    return all(G.is_supported(n, allowed, G.topics_of(s)) for s in G.sentences(text) for n in G.numbers_in(s))


def test_coincidental_numbers_from_other_figures_fail():
    # 41.75 exists only as a DII shareholding %, not as a profit growth rate
    assert not _ok_ctx("Net profit surged 41.7% in the quarter.")
    assert _ok_ctx("DIIs hold 41.75% of the company.")
    # 95,580 exists; 95,310 does not (no loose percentage tolerance)
    assert not _ok_ctx("Net profit reached ₹95,310 Cr.")


def test_numbers_inside_news_headlines_are_allowed():
    assert _ok("Wipro won a $500 million deal (Mint).")


# ---------------------------------------------------------------- content rules
def test_advice_is_caught():
    for s in ["We recommend investors buy the stock at current levels.",
              "Investors should accumulate on dips.",
              "This is a good time to buy Wipro.",
              "The stock is set to double over the next year.",
              "Our target price is ₹220.",
              "We maintain a Buy rating."]:
        assert G.content_issue(s, STANCE, SOURCES), s


def test_third_party_target_is_allowed_unattributed_is_not():
    assert G.content_issue("Analysts' average target price is ₹172.68 (Yahoo Finance).", STANCE, SOURCES) is None
    assert G.content_issue("The target price is ₹172.68.", STANCE, SOURCES)


def test_stance_contradiction_is_caught():
    assert G.content_issue("We hold a Positive stance on the company.", STANCE, SOURCES)
    assert G.content_issue("The scorecard gives a Neutral stance.", STANCE, SOURCES) is None


# ---------------------------------------------------------------- full narrative
def _narr(**over):
    n = {"headline": "Wipro: Q1FY27 revenue ₹24,479 Cr, up 10.6% YoY",
         "executive_summary": "FY26 revenue was ₹92,624 Cr. Net profit was ₹13,266 Cr. ROE is 15.5%.",
         "investment_thesis": ["Valuation: 12.8x P/E vs 5-yr median 19.7x."],
         "sections": [{"heading": "Valuation", "body": "The stock trades at 12.8x. P/B is 2.04x."}],
         "key_strengths": ["Dividend yield of 6.44%."], "key_risks": ["Profit grew only 0.6% YoY."],
         "monitorables": ["Deal wins."], "stance_rationale": "Neutral at 60/100.",
         "news_takeaways": ["Wipro won a $500 million deal (Mint)."]}
    n.update(over)
    return n


def _fallback():
    return _narr(headline="RULE-BASED", executive_summary="Rule-based summary.")


def test_clean_narrative_passes_untouched():
    log = G.CheckLog()
    out, outcome = G.guard_narrative(_narr(), DATA, STANCE, SCORE, SOURCES, _fallback, log)
    assert outcome == "clean" and out["executive_summary"].startswith("FY26 revenue")
    assert not log.removed


def test_one_wrong_sentence_is_removed_rest_kept():
    log = G.CheckLog()
    bad = _narr(sections=[{"heading": "Valuation",
                           "body": "The stock trades at 12.8x. Margins rose to 23.9% last year. P/B is 2.04x."}])
    out, outcome = G.guard_narrative(bad, DATA, STANCE, SCORE, SOURCES, _fallback, log)
    body = out["sections"][0]["body"]
    assert "23.9" not in body and "12.8x" in body and "2.04x" in body
    assert outcome == "trimmed" and len(log.removed) == 1


def test_many_wrong_numbers_replace_whole_text():
    log = G.CheckLog()
    bad = _narr(executive_summary="Revenue was ₹99,999 Cr. Profit was ₹15,555 Cr. ROE was 31.2%. Margin 27.7%.",
                headline="Wipro profit jumps 44.4%")
    out, outcome = G.guard_narrative(bad, DATA, STANCE, SCORE, SOURCES, _fallback, log)
    assert outcome == "replaced" and out["headline"] == "RULE-BASED"


def test_corrector_is_used_first():
    log = G.CheckLog()
    bad = _narr(key_risks=["Profit fell 7.7% YoY."])
    fixed = _narr(key_risks=["Profit grew only 0.6% YoY."])
    out, outcome = G.guard_narrative(bad, DATA, STANCE, SCORE, SOURCES, _fallback, log,
                                     corrector=lambda n, issues: fixed)
    assert outcome == "corrected" and out["key_risks"] == ["Profit grew only 0.6% YoY."]


def test_advice_sentence_removed_and_projection_labelled():
    log = G.CheckLog()
    bad = _narr(executive_summary="FY26 revenue was ₹92,624 Cr. We recommend investors buy the stock.",
                sections=[{"heading": "Outlook", "body": "Sales reach ₹1,01,661 Cr in FY29E."}])
    out, _ = G.guard_narrative(bad, DATA, STANCE, SCORE, SOURCES, _fallback, log)
    assert "recommend" not in out["executive_summary"]
    assert out["sections"][0]["body"].startswith("Model projection:")


def test_news_point_without_website_removed():
    log = G.CheckLog()
    out, _ = G.guard_narrative(_narr(news_takeaways=["Wipro won a big deal.", "Wipro won a $500 million deal (Mint)."]),
                               DATA, STANCE, SCORE, SOURCES, _fallback, log)
    assert out["news_takeaways"] == ["Wipro won a $500 million deal (Mint)."]


def test_stance_rationale_always_states_real_stance():
    log = G.CheckLog()
    out, _ = G.guard_narrative(_narr(stance_rationale="Mixed picture."), DATA, STANCE, SCORE, SOURCES, _fallback, log)
    assert out["stance_rationale"].startswith("Scorecard stance: Neutral (60/100).")


# ---------------------------------------------------------------- other websites
def test_ai_value_outside_range_is_removed():
    log = G.CheckLog()
    sup = {"items": [{"metric": "Gross NPA %", "value": "87.0%", "source": "Investing.com", "url": "https://x",
                      "via": None},
                     {"metric": "Net interest margin (NIM)", "value": "3.4%", "source": "Value Research Online",
                      "url": "https://y", "via": None}]}
    out = G.check_supplementary(sup, M, log)
    assert [i["metric"] for i in out["items"]] == ["Net interest margin (NIM)"]
    assert out["removed_by_checks"][0]["metric"] == "Gross NPA %"


def test_ai_value_contradicting_screener_is_removed():
    log = G.CheckLog()
    sup = {"items": [{"metric": "P/E ratio", "value": "45.2x", "source": "Macrotrends", "url": "https://z", "via": None},
                     {"metric": "Forward P/E", "value": "12.30x", "source": "Yahoo Finance", "via": "yfinance"}]}
    out = G.check_supplementary(sup, M, log)
    assert [i["metric"] for i in out["items"]] == ["Forward P/E"]


def test_direct_values_are_flagged_not_removed():
    log = G.CheckLog()
    sup = {"items": [{"metric": "Beta", "value": "9.5", "source": "Yahoo Finance", "via": "yfinance"}]}
    out = G.check_supplementary(sup, M, log)
    assert out["items"][0]["flag"] and out["items"][0]["verified"].startswith("read directly")


def test_share_counts_are_not_treated_as_percentages():
    log = G.CheckLog()
    sup = {"items": [{"metric": "Free-float shares", "value": "714.59 crore", "source": "Yahoo Finance",
                      "via": "yfinance"}]}
    out = G.check_supplementary(sup, M, log)
    assert "flag" not in out["items"][0]


def test_ai_value_without_link_is_removed():
    log = G.CheckLog()
    sup = {"items": [{"metric": "CASA ratio", "value": "34%", "source": "Investing.com", "url": "", "via": None}]}
    assert G.check_supplementary(sup, M, log)["items"] == []


# ---------------------------------------------------------------- projections
def test_projection_ranges_reordered():
    log = G.CheckLog()
    fc = {"ok": True, "annual": [{"ok": True, "name": "Sales", "unit": "INR_CRORE", "log_space": True,
                                  "low": [110.0], "base": [100.0], "high": [90.0], "cagr_pct": 5.0}],
          "quarterly": []}
    G.check_forecast(fc, log)
    b = fc["annual"][0]
    assert b["low"][0] <= b["base"][0] <= b["high"][0]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}  {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
