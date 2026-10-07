"""Small shared helpers: number parsing, period parsing, formatting."""
from __future__ import annotations

import calendar
import math
import re
from datetime import date, datetime
from typing import Any, Optional

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}


def clean_text(s: Any) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).replace("\xa0", " ")).strip()


def parse_number(text: Any) -> Optional[float]:
    """'11,34,052' -> 1134052.0, '-15%' -> -15.0, '₹ 1.00' -> 1.0, '' -> None."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return None if (isinstance(text, float) and math.isnan(text)) else float(text)
    s = clean_text(text).replace(",", "").replace("₹", "").replace("Rs.", "")
    if s in {"", "-", "--", "—", "–", "NA", "N/A"}:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def period_to_date(label: str) -> Optional[date]:
    """'Jun 2023' -> 2023-06-30 ; '2023-06-30' -> date ; 'TTM' -> None."""
    label = clean_text(label)
    if not label:
        return None
    try:
        return datetime.strptime(label[:10], "%Y-%m-%d").date()
    except ValueError:
        pass
    m = re.match(r"([A-Za-z]{3})[a-z]*\s+(\d{4})", label)
    if m and m.group(1).lower() in _MONTHS:
        y, mo = int(m.group(2)), _MONTHS[m.group(1).lower()]
        return date(y, mo, calendar.monthrange(y, mo)[1])
    return None


def fmt_num(v: Any, decimals: int = 0, suffix: str = "") -> str:
    """Indian-style grouping (12,34,567) like Screener."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    neg = v < 0
    v = abs(v)
    s = f"{v:.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    out = whole + (("." + frac) if frac else "")
    return ("-" if neg else "") + out + suffix


def fmt_pct(v: Any, decimals: int = 1) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    return f"{float(v):.{decimals}f}%"


def safe_div(a: Any, b: Any) -> Optional[float]:
    try:
        if a is None or b is None or float(b) == 0:
            return None
        return float(a) / float(b)
    except (TypeError, ValueError):
        return None


def cagr(start: Any, end: Any, years: float) -> Optional[float]:
    """Compound annual growth in % ; None when not meaningful (negative/zero base)."""
    try:
        start, end = float(start), float(end)
    except (TypeError, ValueError):
        return None
    if years <= 0 or start <= 0 or end <= 0:
        return None
    return ((end / start) ** (1 / years) - 1) * 100


def pct_change(old: Any, new: Any) -> Optional[float]:
    try:
        old, new = float(old), float(new)
    except (TypeError, ValueError):
        return None
    if old == 0:
        return None
    return (new - old) / abs(old) * 100


def slugify(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
