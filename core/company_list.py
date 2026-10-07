"""Load the official NSE equity list (real data) into the companies table.

Source: https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
Every NSE symbol maps to a Screener page at https://www.screener.in/company/<SYMBOL>/
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from core import repository as repo
from core.utils import clean_text, parse_number

NSE_EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_SME_URL = "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/128.0 Safari/537.36",
    "Accept": "text/csv,*/*",
    "Referer": "https://www.nseindia.com/",
}


def download_csv(url: str = NSE_EQUITY_URL) -> str:
    s = requests.Session()
    s.headers.update(HEADERS)
    try:  # NSE sets cookies on the home page; some networks need them
        s.get("https://www.nseindia.com/", timeout=15)
    except requests.RequestException:
        pass
    r = s.get(url, timeout=30)
    r.raise_for_status()
    return r.content.decode("utf-8-sig", errors="replace")


def _parse_date(s: str) -> Optional[str]:
    s = clean_text(s)
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_equity_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw in reader:
        r = {clean_text(k).upper(): clean_text(v) for k, v in raw.items() if k}
        sym = r.get("SYMBOL")
        name = r.get("NAME OF COMPANY") or r.get("NAME_OF_COMPANY")
        if not sym or not name:
            continue
        rows.append({
            "nse_symbol": sym.upper(),
            "name": name,
            "series": r.get("SERIES"),
            "isin": r.get("ISIN NUMBER") or r.get("ISIN"),
            "listing_date": _parse_date(r.get("DATE OF LISTING", "")),
            "face_value": parse_number(r.get("FACE VALUE")),
        })
    return rows


def load_companies(csv_path: str | Path | None = None, include_sme: bool = False) -> int:
    """Load from a local CSV (if given) or download from NSE. Returns number of companies upserted."""
    if csv_path:
        text = Path(csv_path).read_text(encoding="utf-8-sig", errors="replace")
        rows = parse_equity_csv(text)
    else:
        rows = parse_equity_csv(download_csv(NSE_EQUITY_URL))
        if include_sme:
            try:
                rows += parse_equity_csv(download_csv(NSE_SME_URL))
            except requests.RequestException:
                pass
    if not rows:
        raise RuntimeError("No companies parsed from the NSE list.")
    # de-duplicate by symbol
    uniq = {r["nse_symbol"]: r for r in rows}
    return repo.upsert_companies_bulk(list(uniq.values()))
