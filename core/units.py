"""Short unit labels printed above every chart and table (UI and PDFs).

Each entry is (unit, detail): the unit is the 2-3 word answer to "what are these numbers in?",
the detail explains any rows that use a different unit.
"""
from __future__ import annotations

CRORE_HELP = "1 crore = 1,00,00,000 (10 million) · 1 lakh crore = 1,00,000 crore (1 trillion)"

TABLE_UNITS: dict[str, tuple[str, str]] = {
    # Screener sections (keys as stored in payload["sections"])
    "quarters": ("₹ crore", "EPS in ₹ per share · rows ending in % are percentages"),
    "profit-loss": ("₹ crore", "EPS in ₹ per share · rows ending in % are percentages"),
    "balance-sheet": ("₹ crore", ""),
    "cash-flow": ("₹ crore", ""),
    "ratios": ("days and %", "“Days” rows are number of days · rows ending in % are percentages"),
    "shareholding": ("% of shares", "“No. of Shareholders” is a count"),
    "peers": ("mixed units", "CMP in ₹ · Mar Cap, profit and sales in ₹ crore · P/E in times · "
                             "yield, growth and ROCE in %"),
    "growth": ("percent (%)", "compounded per year"),
    # tables inside the analysis report
    "profit_loss": ("₹ crore", "EPS in ₹ per share · rows ending in % are percentages"),
    "quarterly": ("₹ crore", "EPS in ₹ per share · rows ending in % are percentages"),
    "balance_sheet": ("₹ crore", ""),
    "cash_flow": ("₹ crore", ""),
    "key_ratios": ("percent (%)", "Debt / Equity is in times (x)"),
    "scorecard": ("score out of 10", "overall score out of 100"),
    "forecast_annual": ("₹ crore", "EPS in ₹ per share · growth in % per year"),
    "forecast_quarterly": ("₹ crore", ""),
    "supplementary": ("as shown", "each value carries its own unit"),
}


def unit_of(key: str) -> tuple[str, str]:
    return TABLE_UNITS.get(key, ("", ""))


def unit_line(key: str) -> str:
    """'Unit: ₹ crore (EPS in ₹ per share · …)' or '' when unknown."""
    unit, detail = unit_of(key)
    if not unit:
        return ""
    return f"Unit: {unit}" + (f" ({detail})" if detail else "")
