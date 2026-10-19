"""A made-up company in exactly the shape the Screener scraper stores (for tests only - never shown to users).

Numbers are chosen so each check can be verified by hand, e.g. FY26 debtor days 95 vs 60 in FY24 -> red flag.
"""
from __future__ import annotations

import copy
from datetime import date, timedelta

LABELS = ["Mar 2021", "Mar 2022", "Mar 2023", "Mar 2024", "Mar 2025", "Mar 2026"]


def _cols(extra_ttm: bool = False):
    cols = [{"label": l, "date": None, "type": "annual"} for l in LABELS]
    if extra_ttm:
        cols.append({"label": "TTM", "date": None, "type": "ttm"})
    return cols


def _row(metric, nums, schedules=None):
    return {"metric": metric, "order": 0, "values": [str(n) for n in nums], "numbers": list(nums), "unit": "",
            "is_bold": False, "schedule_parent": None, "shareholder_class": None, "schedules": schedules or {}}


def payload(**over) -> dict:
    pl = [("Sales", [1000, 1150, 1300, 1450, 1600, 1760, 1800]),
          ("Expenses", [820, 940, 1060, 1180, 1310, 1450, 1480]),
          ("Operating Profit", [180, 210, 240, 270, 290, 310, 320]),
          ("OPM %", [18, 18, 18, 19, 18, 18, 18]),
          ("Other Income", [20, 22, 25, 30, 35, 40, 41]),
          ("Interest", [30, 32, 35, 38, 40, 45, 46]),
          ("Depreciation", [40, 45, 50, 55, 60, 65, 66]),
          ("Profit before tax", [130, 155, 180, 207, 225, 240, 249]),
          ("Tax %", [25, 25, 25, 25, 25, 25, 25]),
          ("Net Profit", [97.5, 116.25, 135, 155.25, 168.75, 180, 186.75]),
          ("EPS in Rs", [9.75, 11.63, 13.5, 15.53, 16.88, 18.0, 18.68]),
          ("Dividend Payout %", [20, 20, 22, 22, 25, 25, None])]
    bs = [("Equity Capital", [100] * 6), ("Reserves", [500, 590, 690, 800, 920, 1050]),
          ("Borrowings", [300, 310, 330, 400, 520, 680]), ("Other Liabilities", [200, 220, 240, 260, 280, 300]),
          ("Total Liabilities", [1100, 1220, 1360, 1560, 1820, 2130]),
          ("Fixed Assets", [500, 540, 600, 680, 780, 900]), ("CWIP", [20, 30, 40, 50, 60, 70]),
          ("Investments", [80, 90, 100, 110, 120, 130]), ("Other Assets", [500, 560, 620, 720, 860, 1030]),
          ("Total Assets", [1100, 1220, 1360, 1560, 1820, 2130])]
    cf_inv_sched = {"Fixed assets purchased": {"values": [], "numbers": [-60, -80, -100, -120, -150, -180]},
                    "Fixed assets sold": {"values": [], "numbers": [2, 3, 2, 4, 3, 5]}}
    cf = [("Cash from Operating Activity", [120, 140, 150, 120, 100, 80]),
          ("Cash from Investing Activity", [-70, -90, -110, -130, -160, -190], cf_inv_sched),
          ("Cash from Financing Activity", [-40, -40, -30, 20, 70, 110]),
          ("Net Cash Flow", [10, 10, 10, 10, 10, 10])]
    ratios = [("Debtor Days", [55, 58, 60, 60, 75, 95]), ("Inventory Days", [70, 70, 72, 74, 76, 80]),
              ("Days Payable", [50, 50, 52, 52, 50, 48]), ("Cash Conversion Cycle", [75, 78, 80, 82, 101, 127]),
              ("Working Capital Days", [60, 62, 65, 70, 90, 115]), ("ROCE %", [20, 21, 21, 20, 19, 17])]
    start = date(2021, 10, 1)
    prices, p = [], 100.0
    for i in range(1300):
        d = start + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        p *= 1.0006 if i % 7 else 0.985
        if 900 < i < 960:
            p *= 0.99            # a 40%-ish fall, for the drawdown test
        prices.append({"date": d.isoformat(), "close": round(p, 2), "dma50": None, "dma200": None})
    pay = {
        "meta": {"name": "Test Industries Ltd", "nse_symbol": None, "bse_code": None, "basis": "consolidated",
                 "captured_at": "2026-10-17T00:00:00+00:00", "broad_industry": "Industrials", "industry": "Machinery",
                 "run_id": 1},
        "about": "Test Industries makes machines.", "pros": [], "cons": [],
        "summary_ratios": [{"name": "Current Price", "value": 180.0, "value2": None, "value_text": "180", "unit": "INR"},
                           {"name": "Stock P/E", "value": 9.6, "value2": None, "value_text": "9.6", "unit": "x"},
                           {"name": "Market Cap", "value": 1800.0, "value2": None, "value_text": "1,800", "unit": "INR_CRORE"},
                           {"name": "Book Value", "value": 115.0, "value2": None, "value_text": "115", "unit": "INR"}],
        "sections": {
            "profit-loss": {"columns": _cols(True), "rows": [_row(n, v) for n, v in pl]},
            "balance-sheet": {"columns": _cols(), "rows": [_row(n, v) for n, v in bs]},
            "cash-flow": {"columns": _cols(), "rows": [_row(*r) for r in cf]},
            "ratios": {"columns": _cols(), "rows": [_row(n, v) for n, v in ratios]},
        },
        "shareholding": {"quarterly": {"columns": [{"label": q, "date": None, "type": "quarter"} for q in
                                                   ("Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026")],
                                       "rows": [_row("Promoters", [60, 59, 58, 57, 56.5]),
                                                _row("FIIs", [10, 10.5, 11, 11.5, 12])]}},
        "documents": {"announcements": [{"title": "Board approves buyback of shares", "url": "https://x/1",
                                         "date": "2026-09-01", "summary": ""},
                                        {"title": "Trading window closure", "url": "https://x/2", "date": "2026-09-20",
                                         "summary": ""}],
                      "annual_reports": [{"title": "Financial Year 2025", "url": "https://x/ar25", "year": 2025},
                                         {"title": "Financial Year 2026", "url": "https://x/ar26", "year": 2026}],
                      "credit_ratings": [{"title": "Rating update", "url": "https://www.crisil.com/r1",
                                          "meta": "12 Aug 2026 from crisil"}],
                      "concalls": [{"period": "Aug 2026", "links": {"Transcript": "https://x/t", "PPT": "https://x/p"}}]},
        "price_history": prices, "peers": {}, "growth": [], "pe_history": {},
    }
    for k, v in over.items():
        pay[k] = v
    return copy.deepcopy(pay)
