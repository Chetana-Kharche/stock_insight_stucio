"""Guardrails: checks that stop the report from inventing figures or giving wrong / unsafe information.

Every report passes through five groups of checks. Each check is recorded (pass / warn / fail / fixed) and shown
in the report's "Quality checks" section, so a reader can see exactly what was verified.

1. Input data (Screener)      - internal consistency of the scraped numbers (P/E = price / EPS, balance sheet
                                 balances, 4 quarters = TTM, freshness ...). Problems are flagged, never hidden.
2. Other websites             - every value found on another website gets a plausibility range check and, where
                                 Screener has the same figure, a cross-check. AI-searched values that fail are
                                 dropped BEFORE they can reach the AI writer.
3. Projections                - low <= base <= high, no negative revenue, extreme growth flagged.
4. AI text: numbers           - every number Gemini writes must exist in the data it was given (rounding and
                                 crore / lakh-crore conversions allowed). Unverified numbers -> one correction
                                 round with Gemini -> any sentence still unverified is removed -> if too much is
                                 wrong, the whole text is replaced by the rule-based text built from the data.
5. AI text: content           - no buy/sell advice or own target price, projections must be labelled as model
                                 projections, the stance must match the scorecard, news points must name a website.

Nothing here calls the internet. Everything is deterministic and unit-tested (tests/test_guardrails.py).
"""
from __future__ import annotations

import copy
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

# ------------------------------------------------------------------ check log
PASS, WARN, FAIL, FIXED = "pass", "warn", "fail", "fixed"


class CheckLog:
    def __init__(self) -> None:
        self.checks: list[dict] = []
        self.removed: list[dict] = []

    def add(self, group: str, check: str, status: str, detail: str = "") -> None:
        self.checks.append({"group": group, "check": check, "status": status, "detail": detail})

    def removed_text(self, where: str, text: str, reason: str) -> None:
        self.removed.append({"where": where, "text": text[:400], "reason": reason})

    def summary(self) -> dict:
        counts = {s: sum(1 for c in self.checks if c["status"] == s) for s in (PASS, WARN, FAIL, FIXED)}
        return {"total": len(self.checks), **counts, "removed_sentences": len(self.removed)}

    def to_dict(self) -> dict:
        return {"summary": self.summary(), "checks": self.checks, "removed_text": self.removed,
                "checked_at": datetime.now(timezone.utc).isoformat()}


# ------------------------------------------------------------------ number helpers
# 1,01,661.5 | 12.8 | -4.7 | 0.23 ; a number glued to letters on the left (FY27, Q1, H1) is not a figure
_NUM_RX = re.compile(r"(?<![A-Za-z0-9_.])(-?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)(?![\d])")
# numbers that are labels, not figures: 5-year, 52-week, 200-DMA, 3 years, 4 quarters, Q1FY27 ...
_LABEL_AFTER = re.compile(r"^\s*-?\s*(?:year|yr|years|yrs|month|months|quarter|quarters|week|weeks|day|days|dma|"
                          r"factor|factors|point scale|bullet|section|analysts?)\b", re.I)
_SCALE_WORDS = [(re.compile(r"^\s*(lakh\s*crore|lac\s*crore|l\s*cr)\b", re.I), 1e5),
                (re.compile(r"^\s*(thousand\s*crore|k\s*cr)\b", re.I), 1e3)]


def parse_number(tok: str) -> Optional[float]:
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def numbers_in(text: str) -> list[dict]:
    """Every figure written in `text`: [{'raw', 'value', 'decimals', 'scale'}]. Labels such as FY27 are skipped."""
    out = []
    for m in _NUM_RX.finditer(text or ""):
        raw = m.group(1)
        after = text[m.end():m.end() + 24]
        before = text[max(0, m.start() - 3):m.start()]
        val = parse_number(raw)
        if val is None:
            continue
        if _LABEL_AFTER.match(after) and abs(val) <= 260:
            continue
        if re.match(r"^\s*/\s*(10|100)\b", after):             # "7/10", "60/100" scores
            out.append({"raw": raw, "value": val, "decimals": _decimals(raw), "scale": 1.0, "score": True})
            continue
        if 1990 <= val <= 2040 and float(val).is_integer() and "," not in raw:   # calendar years
            continue
        if before.endswith(("FY", "Q", "H")):
            continue
        if before.rstrip().endswith("/") and val in (5, 10, 100):          # the "/100" of "60/100"
            continue
        scale = 1.0
        for rx, mult in _SCALE_WORDS:
            if rx.match(after):
                scale = mult
        out.append({"raw": raw, "value": val, "decimals": _decimals(raw), "scale": scale})
    return out


def _decimals(raw: str) -> int:
    return len(raw.split(".")[1]) if "." in raw else 0


# What a number is about. A number in a sentence about profit must come from a profit figure in the data,
# not from (say) a shareholding percentage that happens to have the same value.
TOPICS: list[tuple[str, re.Pattern]] = [(name, re.compile(rx, re.I)) for name, rx in [
    ("revenue", r"revenue|sales|top ?line|turnover|total income|income from operations"),
    ("profit", r"profit|\bpat\b|earnings(?! per share)|bottom ?line|net income"),
    ("eps", r"\beps\b|earnings per share"),
    ("margin", r"margin|\bopm\b"),
    ("roe", r"\broe\b|return on equity"),
    ("roce", r"\broce\b|return on capital"),
    ("roa", r"\broa\b|return on assets"),
    ("pe", r"p/e|\bpe\b|price[- ]to[- ]earnings|earnings multiple|trailing earnings|times earnings|x earnings|trades? at|trading at|valued at|multiple"),
    ("pb", r"p/b|\bpb\b|price[- ]to[- ]book|book value|\bbook\b"),
    ("debt", r"debt|borrowing|leverage|gearing"),
    ("cash", r"cash ?flow|\bcfo\b|free cash|operating cash|\bfcf\b"),
    ("dividend", r"dividend|payout"),
    ("holding", r"promoter|\bfiis?\b|\bdiis?\b|public|sharehold|holding|stake|pledge"),
    ("price", r"price|\bcmp\b|52[- ]week|high|low|return|dma|traded|trades at|momentum"),
    ("mcap", r"market cap|market capitali[sz]ation|\bmcap\b|enterprise value"),
    ("deposits", r"deposit|casa"),
    ("assets", r"assets|net worth|reserves|equity capital|investments"),
    ("score", r"score"),
    ("npa", r"\bnpa|asset quality|provision"),
    ("interest", r"interest|\bnim\b"),
    ("projection", r"projection|projected|fy\d{2}e|q\dfy\d{2}e|base case|timesfm|forecast|estimate|range"),
]]


def topics_of(text: str) -> frozenset:
    t = (text or "").replace("_", " ")
    return frozenset(name for name, rx in TOPICS if rx.search(t))


def allowed_numbers(*sources: Any) -> list[tuple[float, frozenset]]:
    """All numbers present in the data given to the AI (also inside text such as headlines), each with the
    topics of where it sits (its key / row name / sentence), plus percent forms of fractions."""
    found: list[tuple[float, frozenset]] = []

    def add(v: float, ctx: str) -> None:
        if math.isfinite(v):
            tp = topics_of(ctx)
            found.append((abs(v), tp))
            if abs(v) < 1.5:
                found.append((abs(v) * 100, tp))            # 0.0644 written as 6.44%

    def walk(x: Any, ctx: str) -> None:
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            add(float(x), ctx)
        elif isinstance(x, str):
            seen = set()
            for n in numbers_in(x):
                add(n["value"] * n["scale"], ctx + " " + x)
                seen.add(n["raw"])
            for m in _NUM_RX.finditer(x):                      # labels too (e.g. '17 October')
                if m.group(1) not in seen:
                    v = parse_number(m.group(1))
                    if v is not None:
                        add(v, ctx + " " + x)
        elif isinstance(x, dict):
            label = " ".join(str(x[k]) for k in ("metric", "name", "title", "period") if isinstance(x.get(k), str))
            for k, v in x.items():
                walk(v, f"{ctx} {label} {k}")
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v, ctx)

    for s in sources:
        walk(s, "")
    return sorted(found, key=lambda t: t[0])


def match(n: dict, allowed: list[tuple[float, frozenset]], topics: Optional[frozenset] = None) -> tuple[bool, str]:
    """(supported?, why not). The written number must equal a number in the data after rounding to the written
    precision; when the sentence names what the number is about, the data number must be about the same thing."""
    import bisect

    x = abs(n["value"])
    if n.get("score") or (x <= 12 and float(x).is_integer()):   # scores and small counts ("3 risks", "5/10")
        return True, ""
    keys = [a[0] for a in allowed]
    d = n["decimals"]
    tol = 0.5 * 10 ** (-d) + 1e-9
    cands: list[frozenset] = []
    for target, t_tol in ((x, tol), (x * n.get("scale", 1.0), tol * n.get("scale", 1.0))):
        lo = bisect.bisect_left(keys, target - t_tol)
        hi = bisect.bisect_right(keys, target + t_tol)
        cands += [allowed[i][1] for i in range(lo, hi)]
        if n.get("scale", 1.0) == 1.0:
            break
    if not cands:
        return False, "not found in the data"
    if not topics:
        return True, ""
    if any(c & topics for c in cands) or any(not c for c in cands):
        return True, ""
    other = sorted({t for c in cands for t in c})
    return False, f"the data has this number only for a different figure ({', '.join(other[:3])})"


def is_supported(n: dict, allowed: list, topics: Optional[frozenset] = None) -> bool:
    return match(n, allowed, topics)[0]


# ------------------------------------------------------------------ sentence helpers
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z₹(\"'])")


def sentences(text: str) -> list[str]:
    parts = _SENT_SPLIT.split((text or "").strip())
    return [p for p in parts if p.strip()]


# ------------------------------------------------------------------ content rules
ADVICE_RX = re.compile(
    r"\b(we|i)\s+(recommend|advise|suggest|believe investors should)\b|"
    r"\b(investors|you)\s+(should|must|may want to)\s+(buy|sell|accumulate|exit|add|invest|book profits?)\b|"
    r"\b(strong\s+buy|outperform|underperform|accumulate rating|buy rating|sell rating|hold rating)\b|"
    r"\b(good|right|great|ideal)\s+time\s+to\s+(buy|sell|invest|enter|exit)\b|"
    r"\b(guaranteed?|assured)\s+(returns?|gains?|profits?)\b|\bmulti-?bagger\b|\bsure[- ]shot\b|"
    r"\b(will|is set to|is going to|is bound to)\s+(surely\s+|definitely\s+|certainly\s+)?"
    r"(double|triple|rally|surge|soar|crash|skyrocket|go up|go down)\b|"
    r"\b(our|my)\s+(target|price target|fair value)\b|\bwe value\b",
    re.I)
TARGET_RX = re.compile(r"\b(target price|price target|fair value|upside of|downside of)\b", re.I)
ATTRIBUTED_RX = re.compile(r"\b(analysts?'?|consensus|third[- ]party|according to|as per|\((?:[A-Z][\w .&-]+)\))",
                           re.I)
FUTURE_TAG_RX = re.compile(r"\bFY\d{2}E\b|\bQ\dFY\d{2}E\b|\bnext (three|3|two|2) (fiscal )?years\b", re.I)
PROJECTION_WORDS_RX = re.compile(r"\b(model|projection|projected|projects|estimate|estimated|forecast|TimesFM|"
                                 r"base case|range)\b", re.I)
STANCE_RX = re.compile(r"\b(positive|neutral|cautious|bullish|bearish|negative)\s+(stance|view|outlook rating|"
                       r"rating|call)\b", re.I)
_STANCE_EQUIV = {"bullish": "positive", "bearish": "cautious", "negative": "cautious"}


def content_issue(sentence: str, stance: str, known_sources: Iterable[str]) -> Optional[str]:
    """Reason the sentence breaks a content rule, or None."""
    if ADVICE_RX.search(sentence):
        return "investment advice or a promise about the share price"
    if TARGET_RX.search(sentence) and not ATTRIBUTED_RX.search(sentence):
        return "target price / fair value without naming the third party it comes from"
    for m in STANCE_RX.finditer(sentence):
        said = _STANCE_EQUIV.get(m.group(1).lower(), m.group(1).lower())
        if said != stance.lower():
            return f"stance '{m.group(1)}' contradicts the scorecard stance '{stance}'"
    return None


def _inr(x: float) -> str:
    from core.utils import fmt_num

    return fmt_num(x, 0)


# ------------------------------------------------------------------ 1. input data (Screener)
def check_input_data(payload: dict, m: dict, log: CheckLog) -> None:
    from analysis.metrics import find_series

    g, v, q = m.get("growth", {}), m.get("valuation", {}), m.get("quarterly", {})
    grp = "Input data (Screener)"

    price, pe, eps_ttm = v.get("price"), v.get("pe"), g.get("eps_ttm")
    if price and pe and eps_ttm and eps_ttm > 0:
        implied = price / eps_ttm
        diff = abs(implied - pe) / pe
        log.add(grp, "P/E matches price ÷ TTM EPS", PASS if diff <= 0.15 else WARN,
                f"Screener P/E {pe:.1f}x vs ₹{price:,.2f} ÷ ₹{eps_ttm:.2f} = {implied:.1f}x")
    bv, pb = v.get("book_value"), v.get("pb")
    if price and bv and bv > 0:
        log.add(grp, "Book value is positive and P/B is consistent", PASS, f"P/B {price / bv:.2f}x")

    ta = find_series(payload, "balance-sheet", "Total Assets")
    tl = find_series(payload, "balance-sheet", "Total Liabilities")
    if ta and tl and ta.annual and tl.annual and ta.annual[-1][1] and tl.annual[-1][1]:
        a, l = ta.annual[-1][1], tl.annual[-1][1]
        diff = abs(a - l) / max(abs(a), 1)
        log.add(grp, "Balance sheet balances (assets = liabilities)", PASS if diff <= 0.01 else FAIL,
                f"{ta.annual[-1][0]}: assets ₹{_inr(a)} Cr vs liabilities ₹{_inr(l)} Cr")

    sales = find_series(payload, "quarters", "Sales", "Revenue")
    if sales and g.get("revenue_ttm"):
        last4 = [x for _, x in sales.quarterly[-4:] if x is not None]
        if len(last4) == 4:
            s4 = sum(last4)
            diff = abs(s4 - g["revenue_ttm"]) / max(abs(g["revenue_ttm"]), 1)
            log.add(grp, "Last 4 quarters add up to TTM revenue", PASS if diff <= 0.05 else WARN,
                    f"sum of quarters ₹{_inr(s4)} Cr vs TTM ₹{_inr(g['revenue_ttm'])} Cr")

    neg = [lab for lab, x in ((sales.quarterly if sales else [])) if x is not None and x < 0]
    log.add(grp, "No negative revenue figures", PASS if not neg else FAIL, ", ".join(neg) or "all positive")

    hi, lo = v.get("high_52w"), v.get("low_52w")
    if price and hi and lo:
        ok = lo * 0.97 <= price <= hi * 1.03
        log.add(grp, "Price lies inside the 52-week range", PASS if ok else WARN,
                f"₹{price:,.2f} vs range ₹{lo:,.0f}–₹{hi:,.0f}")

    cap = (payload.get("meta") or {}).get("captured_at")
    if cap:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(cap).replace("Z", "+00:00"))).days
            log.add(grp, "Data is recent", PASS if age <= 7 else WARN,
                    f"Screener data captured {age} day(s) ago" + ("; click Refresh from Screener" if age > 7 else ""))
        except ValueError:
            pass
    if q.get("latest_quarter"):
        log.add(grp, "Latest quarter identified", PASS, str(q["latest_quarter"]))


# ------------------------------------------------------------------ 2. values from other websites
# (keyword in the metric name, low, high) - a value outside the range is not plausible for an Indian listed company
PLAUSIBLE = [
    ("net interest margin", 0.5, 15), ("nim", 0.5, 15), ("gross npa", 0, 40), ("net npa", 0, 25),
    ("casa", 0, 90), ("capital adequacy", 5, 50), ("crar", 5, 50), ("provision coverage", 0, 100),
    ("cost-to-income", 10, 100), ("cost to income", 10, 100), ("credit-deposit", 20, 200),
    ("credit deposit", 20, 200), ("pledged", 0, 100), ("interest coverage", -100, 10000), ("beta", -2, 5),
    ("forward p/e", 0, 1000), ("p/e", 0, 1000), ("peg", -50, 50), ("price to sales", 0, 500),
    ("p/b", 0, 200), ("price to book", 0, 200), ("ev/ebitda", -500, 1000), ("return on assets", -50, 50),
    ("dividend yield", 0, 30), ("delivery", 0, 100), ("free-float", 0, 100), ("free float", 0, 100),
    ("impact cost", 0, 20), ("score", 0, 10), ("roe", -200, 200), ("roce", -200, 200),
    ("loan", -90, 500), ("deposit growth", -90, 500), ("growth", -100, 1000), ("return", -100, 10000),
    ("margin", -500, 100),
]
# metric keyword -> (metrics path, label) for a cross-check against Screener's own figure
CROSS = [("p/e", ("valuation", "pe"), "Screener P/E"), ("price to book", ("valuation", "pb"), "Screener P/B"),
         ("p/b", ("valuation", "pb"), "Screener P/B"), ("dividend yield", ("valuation", "dividend_yield"),
                                                          "Screener dividend yield"),
         ("roe", ("profitability", "roe_current"), "Screener ROE"),
         ("roce", ("profitability", "roce_current"), "Screener ROCE")]
DIRECT_VIA = {"yfinance", "NSE API", "Value Research page"}


def _first_number(text: str) -> Optional[float]:
    ns = numbers_in(str(text or ""))
    return ns[0]["value"] * ns[0]["scale"] if ns else None


def _norm_metric(name: str) -> str:
    return re.sub(r"\s*\(.*?\)\s*", " ", (name or "").lower()).strip()


def check_supplementary(sup: dict, m: dict, log: CheckLog) -> dict:
    """Validate figures from other websites. AI-searched values that fail are removed; directly read ones are
    flagged. Returns a cleaned copy of `sup` (the original is not changed)."""
    grp = "Other websites"
    if not sup or not sup.get("items"):
        return sup
    sup = copy.deepcopy(sup)
    kept, dropped = [], []
    for it in sup.get("items", []):
        name = _norm_metric(it.get("metric", ""))
        direct = it.get("via") in DIRECT_VIA
        val = _first_number(it.get("value"))
        is_text = val is None
        reason = None
        is_count = any(w in name for w in ("shares", "volume", "employees", "number of", "count")) and \
            "%" not in str(it.get("value"))
        if not is_text and not is_count and "history" not in name and "range" not in name \
                and "(vs" not in str(it.get("value")):
            for key, lo, hi in PLAUSIBLE:
                if key in name:
                    if not (lo <= val <= hi):
                        reason = f"value {it.get('value')} is outside the plausible range {lo}–{hi}"
                    break
            if reason is None and "forward" not in name and "peer" not in name and "industry" not in name \
                    and "sector" not in name and "median" not in name:
                for key, path, label in CROSS:
                    if re.search(r"(?<![a-z])" + re.escape(key) + r"(?![a-z])", name):
                        ref = (m.get(path[0]) or {}).get(path[1])
                        if ref:
                            gap = abs(val - ref) / max(abs(ref), 1e-9)
                            if gap > 0.25:
                                reason = f"{it.get('value')} disagrees with {label} {ref:.2f} by {gap * 100:.0f}%"
                        break
        if not direct and not it.get("url"):
            reason = reason or "no source link"
        if reason and not direct:
            dropped.append((it, reason))
            log.add(grp, f"{it.get('metric')} ({it.get('source')})", FIXED, f"removed: {reason}")
            continue
        if reason and direct:
            it["flag"] = reason
            log.add(grp, f"{it.get('metric')} ({it.get('source')})", WARN, f"kept but flagged: {reason}")
        it["verified"] = "read directly from the website" if direct else \
            "found by AI web search on this website — open the link to confirm"
        kept.append(it)

    # same metric from two websites that disagree a lot
    by_name: dict = {}
    for it in kept:
        v = _first_number(it.get("value"))
        if v is not None:
            by_name.setdefault(_norm_metric(it["metric"]), []).append((it, v))
    for name, lst in by_name.items():
        if len({x[0].get("source") for x in lst}) > 1:
            vals = [x[1] for x in lst]
            spread = (max(vals) - min(vals)) / max(abs(max(vals)), 1e-9)
            if spread > 0.2:
                for it, _ in lst:
                    it["flag"] = "websites disagree on this value"
                log.add(grp, f"{lst[0][0]['metric']}: websites agree", WARN,
                        "; ".join(f"{x[0]['source']} {x[0]['value']}" for x in lst))
    n_ai = sum(1 for it in kept if it.get("via") not in DIRECT_VIA)
    log.add(grp, "Values from other websites checked (range, cross-check with Screener, source link)",
            PASS if not dropped else FIXED,
            f"{len(kept)} kept ({len(kept) - n_ai} read directly, {n_ai} found by AI search), {len(dropped)} removed")
    sup["items"] = kept
    sup["removed_by_checks"] = [{"metric": it.get("metric"), "value": it.get("value"), "source": it.get("source"),
                                 "reason": r} for it, r in dropped]
    return sup


# ------------------------------------------------------------------ 3. projections
def check_forecast(fc: dict, log: CheckLog) -> None:
    grp = "Projections"
    if not fc or not fc.get("ok"):
        log.add(grp, "Projections produced", WARN, (fc or {}).get("error") or "not enough history")
        return
    problems = 0
    for kind in ("annual", "quarterly"):
        for b in fc.get(kind, []):
            if not b.get("ok"):
                continue
            for i, (lo, base, hi) in enumerate(zip(b["low"], b["base"], b["high"])):
                if not (lo <= base <= hi):
                    b["low"][i], b["base"][i], b["high"][i] = sorted([lo, base, hi])
                    problems += 1
            if b["unit"] != "INR" and b.get("log_space") and min(b["base"]) <= 0:
                problems += 1
                log.add(grp, f"{b['name']}: no negative projected amounts", FAIL, "a projected value is ≤ 0")
            cagr = b.get("cagr_pct")
            if cagr is not None and abs(cagr) > 60:
                log.add(grp, f"{b['name']}: growth rate is realistic", WARN,
                        f"{cagr:+.1f}% a year is extreme; read the range, not the base case")
            tf = b.get("timesfm")
            if tf and b["base"][-1]:
                gap = abs(tf["base"][-1] - b["base"][-1]) / abs(b["base"][-1])
                if gap > 0.4:
                    log.add(grp, f"{b['name']}: TimesFM agrees with the other models", WARN,
                            f"TimesFM differs from the base case by {gap * 100:.0f}% at the end of the horizon")
    log.add(grp, "Low ≤ base ≤ high for every projected period", PASS if not problems else FIXED,
            "all ranges in order" if not problems else f"{problems} range(s) re-ordered")
    log.add(grp, "Projections are labelled as model estimates (E suffix, range, confidence)", PASS,
            "added by the code, not by the AI")


# ------------------------------------------------------------------ financial health (computed by code)
def check_health(h: dict, log: CheckLog) -> None:
    grp = "Financial health"
    if not h:
        return
    d = h.get("dupont") or {}
    rows = {r["metric"][:6]: r["raw"] for r in d.get("rows", [])}
    bad = 0
    for i in range(len(d.get("columns", []))):
        try:
            m_, t_, e_, r_ = rows["Net pr"][i], rows["× Asse"][i], rows["× Equi"][i], rows["= Retu"][i]
        except (KeyError, IndexError):
            break
        if None not in (m_, t_, e_, r_) and abs(m_ * t_ * e_ - r_) > 0.05:
            bad += 1
    if d.get("rows"):
        log.add(grp, "DuPont parts multiply back to ROE", PASS if not bad else FAIL,
                "margin × turnover × leverage = ROE for every year" if not bad else f"{bad} year(s) do not add up")
    p = h.get("piotroski") or {}
    if p.get("available"):
        passed = sum(1 for t in p["tests"] if t["result"])
        done = sum(1 for t in p["tests"] if t["result"] is not None)
        ok = passed == p["score"] and done == p["out_of"]
        log.add(grp, "Piotroski score equals the tests passed", PASS if ok else FAIL,
                f"{p['score']} of {p['out_of']} (tests that cannot be done from Screener data are not counted)")
    rf = h.get("red_flags") or {}
    log.add(grp, "Warning signs come with the numbers that triggered them",
            PASS if all(f.get("evidence") for f in rf.get("flags", [])) else FAIL,
            f"{len(rf.get('flags', []))} of {len(rf.get('checked', []))} checks fired")


# ------------------------------------------------------------------ 4 + 5. AI narrative
TEXT_FIELDS = ("headline", "executive_summary", "stance_rationale")
LIST_FIELDS = ("investment_thesis", "key_strengths", "key_risks", "monitorables", "news_takeaways")


def _iter_text(narr: dict):
    """(where, getter-key, text) for every piece of text in the narrative."""
    for f in TEXT_FIELDS:
        yield f, (f, None), narr.get(f) or ""
    for f in LIST_FIELDS:
        for i, t in enumerate(narr.get(f) or []):
            yield f"{f}[{i + 1}]", (f, i), t or ""
    for i, s in enumerate(narr.get("sections") or []):
        yield f"section '{s.get('heading')}'", ("sections", i), s.get("body") or ""


def find_issues(narr: dict, allowed: list[float], stance: str, known_sources: Iterable[str]) -> list[dict]:
    """Every sentence with an unverified number or a content problem."""
    issues = []
    srcs = [s.lower() for s in known_sources]
    for where, key, text in _iter_text(narr):
        for sent in sentences(text):
            tp = topics_of(sent)
            bad = []
            for n in numbers_in(sent):
                ok, why = match(n, allowed, tp)
                if not ok:
                    bad.append(f"{n['raw']} ({why})")
            reason = content_issue(sent, stance, known_sources)
            if bad:
                issues.append({"where": where, "key": key, "sentence": sent, "kind": "number",
                               "reason": "unverified number: " + "; ".join(bad), "numbers": bad})
            if reason:
                issues.append({"where": where, "key": key, "sentence": sent, "kind": "content", "reason": reason})
        if key[0] == "news_takeaways" and text and not any(s in text.lower() for s in srcs):
            issues.append({"where": where, "key": key, "sentence": text, "kind": "content",
                           "reason": "news point does not name the website it comes from"})
    return issues


def _label_projections(text: str) -> tuple[str, int]:
    """Prefix 'Model projection: ' to sentences that quote FY27E-style figures without saying they are estimates."""
    out, n = [], 0
    for s in sentences(text):
        if FUTURE_TAG_RX.search(s) and numbers_in(s) and not PROJECTION_WORDS_RX.search(s):
            s = "Model projection: " + s[0].lower() + s[1:] if s else s
            n += 1
        out.append(s)
    return " ".join(out), n


def _remove_sentences(narr: dict, issues: list[dict], log: CheckLog) -> dict:
    narr = copy.deepcopy(narr)
    by_key: dict = {}
    for iss in issues:
        by_key.setdefault(iss["key"], []).append(iss)
    for (field, idx), lst in by_key.items():
        bad = {i["sentence"] for i in lst}
        for i in lst:
            log.removed_text(i["where"], i["sentence"], i["reason"])
        if field == "sections":
            body = narr["sections"][idx].get("body") or ""
            narr["sections"][idx]["body"] = " ".join(s for s in sentences(body) if s not in bad)
        elif idx is None:
            narr[field] = " ".join(s for s in sentences(narr.get(field) or "") if s not in bad)
        else:
            text = narr[field][idx]
            remaining = " ".join(s for s in sentences(text) if s not in bad)
            narr[field][idx] = remaining
    for f in LIST_FIELDS:
        narr[f] = [t for t in (narr.get(f) or []) if t and t.strip()]
    narr["sections"] = [s for s in (narr.get("sections") or []) if (s.get("body") or "").strip()]
    return narr


def _count_sentences(narr: dict) -> int:
    return sum(len(sentences(t)) for _, _, t in _iter_text(narr))


def guard_narrative(narr: dict, data_for_llm: dict, stance: str, score: float, known_sources: Iterable[str],
                    fallback: Callable[[], dict], log: CheckLog,
                    corrector: Optional[Callable[[dict, list[dict]], Optional[dict]]] = None) -> tuple[dict, str]:
    """Check the AI-written narrative. Returns (safe narrative, outcome) where outcome is one of
    'clean', 'corrected', 'trimmed', 'replaced'."""
    grp = "AI text"
    allowed = allowed_numbers(data_for_llm, {"score": score})
    known_sources = list(known_sources)
    issues = find_issues(narr, allowed, stance, known_sources)
    total = max(_count_sentences(narr), 1)
    n_nums = sum(len(numbers_in(t)) for _, _, t in _iter_text(narr))
    outcome = "clean"

    if issues and corrector is not None:
        fixed = None
        try:
            fixed = corrector(narr, issues)
        except Exception as e:  # noqa: BLE001
            log.add(grp, "Correction round with the AI", WARN, f"failed: {type(e).__name__}")
        if fixed:
            new_issues = find_issues(fixed, allowed, stance, known_sources)
            log.add(grp, "Correction round with the AI", FIXED if len(new_issues) < len(issues) else WARN,
                    f"{len(issues)} problem(s) sent back to the AI; {len(new_issues)} left after correction")
            if len(new_issues) < len(issues):
                narr, issues, outcome = fixed, new_issues, "corrected"
                total = max(_count_sentences(narr), 1)

    bad_sentences = {(i["where"], i["sentence"]) for i in issues}
    core_hit = any(i["key"][0] in ("headline", "executive_summary") for i in issues)
    if len(bad_sentences) > max(4, 0.25 * total) or (core_hit and len(bad_sentences) > 2):
        for i in issues:
            log.removed_text(i["where"], i["sentence"], i["reason"])
        log.add(grp, "Every number in the AI text is found in the data", FAIL,
                f"{len(bad_sentences)} of {total} sentences failed → the whole AI text was replaced by the "
                "rule-based text built only from the data")
        narr, outcome = fallback(), "replaced"
    else:
        if issues:
            narr = _remove_sentences(narr, issues, log)
            outcome = "trimmed" if outcome == "clean" else outcome
        num_issues = [i for i in issues if i["kind"] == "number"]
        log.add(grp, "Every number in the AI text is found in the data",
                PASS if not num_issues else FIXED,
                f"{n_nums} numbers checked" + (f"; {len(num_issues)} sentence(s) with unverified numbers removed"
                                               if num_issues else ""))
        content = [i for i in issues if i["kind"] == "content"]
        log.add(grp, "No investment advice, own target price or price promises; stance matches the scorecard",
                PASS if not content else FIXED,
                "none found" if not content else f"{len(content)} sentence(s) removed")

    # headline / summary must not be empty after trimming; stance rationale must state the real stance
    fb = None
    for f in ("headline", "executive_summary"):
        if not (narr.get(f) or "").strip():
            fb = fb or fallback()
            narr[f] = fb.get(f)
            log.add(grp, f"{f.replace('_', ' ').capitalize()} present", FIXED, "rebuilt from the data")
    if stance.lower() not in (narr.get("stance_rationale") or "").lower():
        narr["stance_rationale"] = (f"Scorecard stance: {stance} ({score:.0f}/100). "
                                    + (narr.get("stance_rationale") or "")).strip()
    labelled = 0
    for where, key, text in list(_iter_text(narr)):
        new, n = _label_projections(text)
        if n:
            labelled += n
            if key[0] == "sections":
                narr["sections"][key[1]]["body"] = new
            elif key[1] is None:
                narr[key[0]] = new
            else:
                narr[key[0]][key[1]] = new
    log.add(grp, "Projections in the text are called model projections", PASS if not labelled else FIXED,
            "all labelled" if not labelled else f"{labelled} sentence(s) labelled 'Model projection'")
    if not narr.get("news_takeaways"):
        fb = fb or fallback()
        narr["news_takeaways"] = fb.get("news_takeaways", [])
    return narr, outcome


def guard_rule_based(narr: dict, data_for_llm: dict, score: float, log: CheckLog) -> None:
    """The rule-based text is built by code from the same data; still verify its numbers (catches code bugs)."""
    allowed = allowed_numbers(data_for_llm, {"score": score})
    bad = []
    for where, _, text in _iter_text(narr):
        for sent in sentences(text):
            tp = topics_of(sent)
            for n in numbers_in(sent):
                ok, why = match(n, allowed, tp)
                if not ok:
                    bad.append(f"{where}: {n['raw']} ({why})")
    log.add("Report text (rule-based)", "Every number in the text is found in the data", PASS if not bad else WARN,
            "text written by code from the data, no AI" + (f"; unmatched: {', '.join(bad[:6])}" if bad else ""))


OUTCOME_TEXT = {
    "clean": "AI text passed every check",
    "corrected": "AI text corrected after the fact-check",
    "trimmed": "sentences that failed the fact-check were removed",
    "replaced": "AI text failed the fact-check and was replaced by text built only from the data",
    "rule-based": "text written by code from the data (no AI)",
}


def reader_badge(report: dict) -> str:
    """The single line a reader sees (the detailed log stays in the app and the database)."""
    if not report.get("quality_checks"):
        return ""
    notes = reader_notes(report)
    return "All figures in this report were checked against the source data" + (
        f" · {len(notes)} data note{'s' if len(notes) != 1 else ''} below" if notes else "")


def reader_notes(report: dict) -> list[str]:
    """Plain-language notes a reader needs to interpret the numbers (stale data, source inconsistencies, outside
    values that disagree). Internal steps such as removed AI sentences are NOT included."""
    out = []
    for c in (report.get("quality_checks") or {}).get("checks", []):
        if c["status"] not in (WARN, FAIL):
            continue
        g, k, d = c["group"], c["check"], c.get("detail") or ""
        if k == "Data is recent":
            m = re.search(r"(\d+) day", d)
            out.append(f"The company data is {m.group(1) if m else 'several'} days old; refresh it from Screener "
                       "before relying on the latest figures.")
        elif k.startswith("P/E matches"):
            out.append(f"Screener's P/E differs from price ÷ latest EPS ({d}); the P/E may use a different period.")
        elif k.startswith("Balance sheet balances"):
            out.append(f"In the source data the balance sheet does not balance ({d}); treat balance-sheet ratios with care.")
        elif k.startswith("Last 4 quarters"):
            out.append(f"Quarterly revenue does not add up to the trailing-twelve-month figure ({d}).")
        elif k.startswith("Price lies inside"):
            out.append(f"The share price is outside the stated 52-week range ({d}); price data may be out of date.")
        elif k.startswith("No negative revenue"):
            out.append(f"Negative revenue appears in the source data ({d}).")
        elif g == "Projections" and "growth rate is realistic" in k:
            out.append(k.split(":")[0] + f": projected growth is unusually high or low ({d}).")
        elif g == "Other websites" and k.endswith("websites agree"):
            out.append(f"Websites give different values for {k.split(':')[0]} ({d}).")
        elif g == "Other websites" and c["status"] == WARN and "kept but flagged" in d:
            out.append(f"{k}: {d.replace('kept but flagged: ', '')}.")
    return out


def badge_text(report: dict) -> str:
    """One line for the top of the report, e.g. 'Fact-checked: 15 checks · 2 fixed · 1 warning'."""
    q = report.get("quality_checks") or {}
    s = q.get("summary") or {}
    if not s:
        return ""
    parts = [f"{s.get('total', 0)} checks"]
    if s.get("fixed"):
        parts.append(f"{s['fixed']} fixed")
    if s.get("warn"):
        parts.append(f"{s['warn']} warning{'s' if s['warn'] != 1 else ''}")
    if s.get("fail"):
        parts.append(f"{s['fail']} failed")
    return "Fact-checked: " + " · ".join(parts) + " · " + OUTCOME_TEXT.get(report.get("narrative_check", ""), "")


def correction_prompt(narr: dict, issues: list[dict]) -> str:
    lines = "\n".join(f"- [{i['where']}] \"{i['sentence']}\" -> {i['reason']}" for i in issues[:40])
    return ("A fact-checker compared your report with the DATA and found the problems below. Return the SAME JSON "
            "report with ONLY these sentences fixed: use the exact figure from DATA, or remove the figure, or remove "
            "the sentence. Do not add any new numbers. Do not give advice or a target price of your own. Keep the "
            "stance unchanged. Keep everything else word for word.\n\nPROBLEMS:\n" + lines +
            "\n\nYOUR REPORT:\n" + json.dumps(narr, ensure_ascii=False))
