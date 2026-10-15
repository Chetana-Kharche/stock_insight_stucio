"""Market movers: top gainers, top losers, stocks at 52-week highs, most active.

Primary source: NSE's own live-analysis data (the endpoints behind nseindia.com's "Market movers" page).
NSE only answers browsers that first open its home page, so a requests.Session collects the cookies first.
If NSE refuses (it often blocks automated or cloud traffic), the same lists are calculated from Yahoo Finance
daily prices for the Nifty 100 companies (list downloaded from NSE's archives), and the page says so.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
import requests

log = logging.getLogger(__name__)

NSE_HOME = "https://www.nseindia.com/"
NSE_API = {
    "gainers": "https://www.nseindia.com/api/live-analysis-variations?index=gainers",
    "losers": "https://www.nseindia.com/api/live-analysis-variations?index=loosers",
    "high52": "https://www.nseindia.com/api/live-analysis-data-52weekhighstock",
    "active": "https://www.nseindia.com/api/live-analysis-most-active-securities?index=volume",
}
NIFTY100_CSV = "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36",
           "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
           "Referer": "https://www.nseindia.com/market-data/top-gainers-losers"}
LISTS = {"gainers": "Top gainers", "losers": "Top losers", "high52": "52-week highs", "active": "Most active"}


def _num(v: Any) -> Optional[float]:
    try:
        if v in (None, "", "-"):
            return None
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _pick(d: dict, *keys: str) -> Any:
    low = {k.lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in low and low[k.lower()] not in (None, ""):
            return low[k.lower()]
    return None


def _rows_from_nse(kind: str, js: Any) -> list[dict]:
    """Normalise the different NSE response shapes to one row format."""
    data: list = []
    if isinstance(js, dict):
        if isinstance(js.get("data"), list):
            data = js["data"]
        else:  # variations: {"NIFTY": {"data": [...]}, "allSec": {...}, ...}
            for key in ("allSec", "NIFTY", "FOSec", "BANKNIFTY"):
                block = js.get(key)
                if isinstance(block, dict) and isinstance(block.get("data"), list) and block["data"]:
                    data = block["data"]
                    break
    elif isinstance(js, list):
        data = js
    rows = []
    for d in data:
        if not isinstance(d, dict):
            continue
        sym = _pick(d, "symbol")
        if not sym:
            continue
        rows.append({
            "symbol": str(sym).upper(),
            "name": _pick(d, "companyName", "comapnyName", "meta_companyName"),
            "price": _num(_pick(d, "ltp", "lastPrice", "last_price")),
            "change_pct": _num(_pick(d, "perChange", "pChange", "net_change_percent")),
            "volume": _num(_pick(d, "trade_quantity", "totalTradedVolume", "quantityTraded", "volume")),
            "high_52w": _num(_pick(d, "new52WHL", "yearHigh", "high52")),
        })
    return rows


def _nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(NSE_HOME, timeout=12)
    return s


def from_nse(kind: str, session: Optional[requests.Session] = None) -> list[dict]:
    s = session or _nse_session()
    r = s.get(NSE_API[kind], timeout=12)
    r.raise_for_status()
    rows = _rows_from_nse(kind, r.json())
    if not rows:
        raise ValueError("NSE returned no rows")
    return rows


# ------------------------------------------------------------------ fallback: Yahoo Finance on Nifty 100
def nifty100_list() -> list[dict]:
    r = requests.get(NIFTY100_CSV, headers=HEADERS, timeout=15)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    return [{"symbol": str(row["Symbol"]).strip().upper(), "name": str(row["Company Name"]).strip(),
             "industry": str(row.get("Industry", "")).strip()} for _, row in df.iterrows()]


def from_yahoo(universe: list[dict]) -> dict[str, list[dict]]:
    import yfinance as yf

    tickers = [f"{u['symbol']}.NS" for u in universe]
    names = {u["symbol"]: u["name"] for u in universe}
    data = yf.download(tickers, period="1y", interval="1d", group_by="ticker", auto_adjust=False,
                       progress=False, threads=True)
    rows = []
    for u in universe:
        t = f"{u['symbol']}.NS"
        try:
            df = data[t].dropna(subset=["Close"])
        except (KeyError, AttributeError):
            continue
        if len(df) < 2:
            continue
        last, prev = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
        hi = float(df["High"].max())
        rows.append({"symbol": u["symbol"], "name": names[u["symbol"]], "price": last,
                     "change_pct": (last / prev - 1) * 100 if prev else None,
                     "volume": float(df["Volume"].iloc[-1]) if "Volume" in df else None,
                     "high_52w": hi, "pct_from_high": (last / hi - 1) * 100 if hi else None,
                     "as_of": str(df.index[-1])[:10]})
    ok = [r for r in rows if r["change_pct"] is not None]
    return {
        "gainers": sorted([r for r in ok if r["change_pct"] > 0], key=lambda r: -r["change_pct"])[:20],
        "losers": sorted([r for r in ok if r["change_pct"] < 0], key=lambda r: r["change_pct"])[:20],
        "high52": sorted([r for r in ok if (r["pct_from_high"] or -99) >= -2.0],
                         key=lambda r: -(r["pct_from_high"] or -99))[:20],
        "active": sorted([r for r in ok if r["volume"]], key=lambda r: -r["volume"])[:20],
    }


def market_movers() -> dict:
    """{"source", "as_of", "lists": {kind: [rows]}, "notes": [...]} - never raises."""
    out: dict = {"source": None, "as_of": datetime.now(timezone.utc).isoformat(), "lists": {}, "notes": []}
    try:
        s = _nse_session()
        for kind in LISTS:
            try:
                out["lists"][kind] = from_nse(kind, s)[:20]
            except Exception as e:  # noqa: BLE001
                out["notes"].append(f"NSE {LISTS[kind]}: {type(e).__name__}")
        if any(out["lists"].values()):
            out["source"] = "NSE India (live market data)"
    except Exception as e:  # noqa: BLE001
        out["notes"].append(f"NSE not reachable: {type(e).__name__}")

    missing = [k for k in LISTS if not out["lists"].get(k)]
    if missing:
        try:
            yl = from_yahoo(nifty100_list())
            for k in missing:
                out["lists"][k] = yl.get(k, [])
            label = "Yahoo Finance daily prices for Nifty 100 companies (end of day / delayed)"
            out["source"] = label if not out["source"] else f"{out['source']}; {label} for some lists"
        except Exception as e:  # noqa: BLE001
            out["notes"].append(f"Yahoo Finance fallback failed: {type(e).__name__}: {e}")
    return out
