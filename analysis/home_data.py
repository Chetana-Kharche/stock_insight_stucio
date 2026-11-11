"""Live market data for the Home page: indices, sectors, top companies, movers, volume shockers.

Sources (all public, no login):
  * NSE India  - index values (allIndices) and the NIFTY 100 constituents with price, change, volume,
                 traded value and free-float market cap (equity-stockIndices). Live during market hours.
  * Yahoo Finance (yfinance) - index charts (1D to 5Y), BSE SENSEX, volume history for "volume shockers",
                 and a full fallback when NSE refuses the request (NSE often blocks cloud/automated traffic).
Company fundamentals stay with Screener.in (Screener Data page) and the report adds Value Research and others.
Every function here returns plain dicts/lists and never raises, so the Home page always renders.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from analysis.market import HEADERS, NSE_HOME, nifty100_list

log = logging.getLogger(__name__)

# name shown, Yahoo ticker, NSE index name (None = not an NSE index)
INDICES = [
    ("NIFTY 50", "^NSEI", "NIFTY 50"),
    ("SENSEX", "^BSESN", None),
    ("BANK NIFTY", "^NSEBANK", "NIFTY BANK"),
    ("NIFTY NEXT 50", "^NSMIDCP", "NIFTY NEXT 50"),
    ("NIFTY MIDCAP 100", "NIFTY_MIDCAP_100.NS", "NIFTY MIDCAP 100"),
    ("NIFTY IT", "^CNXIT", "NIFTY IT"),
    ("INDIA VIX", "^INDIAVIX", "INDIA VIX"),
]
SECTORS = [
    ("Banks", "^NSEBANK", "NIFTY BANK"),
    ("Financial Services", "NIFTY_FIN_SERVICE.NS", "NIFTY FINANCIAL SERVICES"),
    ("IT", "^CNXIT", "NIFTY IT"),
    ("Auto", "^CNXAUTO", "NIFTY AUTO"),
    ("Pharma", "^CNXPHARMA", "NIFTY PHARMA"),
    ("FMCG", "^CNXFMCG", "NIFTY FMCG"),
    ("Metal", "^CNXMETAL", "NIFTY METAL"),
    ("Energy", "^CNXENERGY", "NIFTY ENERGY"),
    ("Realty", "^CNXREALTY", "NIFTY REALTY"),
    ("PSU Banks", "^CNXPSUBANK", "NIFTY PSU BANK"),
    ("Infrastructure", "^CNXINFRA", "NIFTY INFRASTRUCTURE"),
    ("Media", "^CNXMEDIA", "NIFTY MEDIA"),
]
RANGES = {  # label -> (yfinance period, interval)
    "1D": ("1d", "5m"), "1W": ("5d", "15m"), "1M": ("1mo", "1d"), "6M": ("6mo", "1d"),
    "1Y": ("1y", "1d"), "3Y": ("3y", "1wk"), "5Y": ("5y", "1wk"),
}
NSE_ALL_INDICES = "https://www.nseindia.com/api/allIndices"
NSE_CONSTITUENTS = "https://www.nseindia.com/api/equity-stockIndices"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(v: Any) -> Optional[float]:
    try:
        if v in (None, "", "-"):
            return None
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({**HEADERS, "Referer": "https://www.nseindia.com/market-data/live-equity-market"})
    s.get(NSE_HOME, timeout=10)
    return s


# ------------------------------------------------------------------ yfinance helpers
def _frame(data, ticker: str):
    """One ticker's OHLCV frame from yf.download output (works for 1 or many tickers, old and new yfinance)."""
    import pandas as pd

    if data is None or getattr(data, "empty", True):
        return None
    cols = data.columns
    if isinstance(cols, pd.MultiIndex):
        if ticker in cols.get_level_values(0):
            df = data[ticker]
        elif ticker in cols.get_level_values(-1):
            df = data.xs(ticker, axis=1, level=-1)
        else:
            return None
    else:
        df = data
    if "Close" not in df:
        return None
    df = df.dropna(subset=["Close"])
    return df if len(df) else None


def _download(tickers: list[str], period: str, interval: str):
    import yfinance as yf

    return yf.download(tickers, period=period, interval=interval, group_by="ticker", auto_adjust=False,
                       progress=False, threads=True)


def _last_session(df):
    """Rows of the most recent trading day (for intraday sparklines)."""
    if df is None or not len(df):
        return df
    day = df.index[-1].date()
    return df[[ix.date() == day for ix in df.index]]


# ------------------------------------------------------------------ indices + sectors
def _nse_index_quotes(session: Optional[requests.Session] = None) -> dict[str, dict]:
    s = session or _nse_session()
    r = s.get(NSE_ALL_INDICES, timeout=12)
    r.raise_for_status()
    out = {}
    for d in (r.json() or {}).get("data", []):
        name = str(d.get("index") or d.get("indexSymbol") or "").upper()
        if not name:
            continue
        out[name] = {"last": _num(d.get("last")), "change": _num(d.get("variation")),
                     "change_pct": _num(d.get("percentChange")), "prev_close": _num(d.get("previousClose")),
                     "open": _num(d.get("open")), "high": _num(d.get("high")), "low": _num(d.get("low")),
                     "year_high": _num(d.get("yearHigh")), "year_low": _num(d.get("yearLow")),
                     "advances": _num(d.get("advances")), "declines": _num(d.get("declines")),
                     "unchanged": _num(d.get("unchanged"))}
    if not out:
        raise ValueError("NSE returned no index data")
    return out


def market_overview() -> dict:
    """Index cards + sector performance + intraday sparklines. Never raises."""
    out: dict = {"as_of": _now(), "indices": [], "sectors": [], "breadth": None, "sources": [], "notes": []}
    nse: dict[str, dict] = {}
    try:
        nse = _nse_index_quotes()
        out["sources"].append("NSE India")
    except Exception as e:  # noqa: BLE001
        out["notes"].append(f"NSE index data not available ({type(e).__name__}); using Yahoo Finance.")

    tickers = sorted({t for _, t, _ in INDICES + SECTORS})
    intraday = daily = None
    try:
        intraday = _download(tickers, "5d", "5m")
        daily = _download(tickers, "1mo", "1d")
        out["sources"].append("Yahoo Finance")
    except Exception as e:  # noqa: BLE001
        out["notes"].append(f"Yahoo Finance not available ({type(e).__name__}).")

    def build(name: str, ticker: str, nse_name: Optional[str]) -> Optional[dict]:
        q = dict(nse.get((nse_name or "").upper()) or {})
        dfi = _last_session(_frame(intraday, ticker))
        dfd = _frame(daily, ticker)
        spark = [float(x) for x in dfi["Close"].tolist()] if dfi is not None and len(dfi) else []
        if q.get("last") is None:
            if dfd is not None and len(dfd) >= 2:
                if spark:   # latest intraday price vs the last daily close before that trading day
                    day = dfi.index[-1].date()
                    before = [c for ix, c in zip(dfd.index, dfd["Close"]) if ix.date() < day]
                    last = float(dfi["Close"].iloc[-1])
                    prev = float(before[-1]) if before else float(dfd["Close"].iloc[-2])
                else:
                    last, prev = float(dfd["Close"].iloc[-1]), float(dfd["Close"].iloc[-2])
                q = {"last": last, "prev_close": prev, "change": last - prev,
                     "change_pct": (last / prev - 1) * 100 if prev else None,
                     "high": float(dfi["High"].max()) if spark else None,
                     "low": float(dfi["Low"].min()) if spark else None}
            else:
                return None
        q.update({"name": name, "ticker": ticker, "spark": spark})
        return q

    for name, t, n in INDICES:
        row = build(name, t, n)
        if row:
            out["indices"].append(row)
    for name, t, n in SECTORS:
        row = build(name, t, n)
        if row:
            out["sectors"].append(row)
    out["sectors"].sort(key=lambda r: -(r.get("change_pct") or -999))
    n50 = nse.get("NIFTY 50") or {}
    if n50.get("advances") is not None:
        out["breadth"] = {"advances": n50["advances"], "declines": n50.get("declines") or 0,
                          "unchanged": n50.get("unchanged") or 0, "index": "NIFTY 50"}
    return out


def index_history(ticker: str, rng: str = "1D") -> list[dict]:
    """[{t, close}] for the big chart. Never raises."""
    period, interval = RANGES.get(rng, RANGES["1D"])
    try:
        df = _frame(_download([ticker], "5d" if rng == "1D" else period, interval), ticker)
        if rng == "1D":
            df = _last_session(df)
        if df is None:
            return []
        return [{"t": ix.to_pydatetime() if hasattr(ix, "to_pydatetime") else ix, "close": float(c)}
                for ix, c in zip(df.index, df["Close"])]
    except Exception as e:  # noqa: BLE001
        log.warning("index history %s %s: %s", ticker, rng, e)
        return []


# ------------------------------------------------------------------ stocks (NIFTY 100 universe)
def _nse_constituents(index: str = "NIFTY 100", session: Optional[requests.Session] = None) -> list[dict]:
    s = session or _nse_session()
    r = s.get(NSE_CONSTITUENTS, params={"index": index}, timeout=15)
    r.raise_for_status()
    rows = []
    for d in (r.json() or {}).get("data", []):
        sym = str(d.get("symbol") or "").upper()
        if not sym or sym == index.upper() or d.get("priority") == 1:
            continue
        meta = d.get("meta") or {}
        ffmc = _num(d.get("ffmc"))
        rows.append({
            "symbol": sym, "name": meta.get("companyName") or sym, "industry": meta.get("industry") or "",
            "price": _num(d.get("lastPrice")), "change": _num(d.get("change")), "change_pct": _num(d.get("pChange")),
            "volume": _num(d.get("totalTradedVolume")), "value": _num(d.get("totalTradedValue")),
            "year_high": _num(d.get("yearHigh")), "year_low": _num(d.get("yearLow")),
            # NSE gives free-float market cap in rupees; shown in ₹ crore
            "mcap_cr": (ffmc / 1e7 if ffmc and ffmc > 1e9 else ffmc), "mcap_kind": "free-float",
        })
    if not rows:
        raise ValueError("NSE returned no stocks")
    return rows


def _yahoo_mcaps(symbols: list[str]) -> dict[str, float]:
    import yfinance as yf

    def one(sym: str):
        try:
            v = yf.Ticker(f"{sym}.NS").fast_info.get("marketCap")
            return sym, (float(v) / 1e7 if v else None)
        except Exception:  # noqa: BLE001
            return sym, None

    with ThreadPoolExecutor(max_workers=12) as ex:
        return {s: v for s, v in ex.map(one, symbols) if v}


def stocks_overview(extra_symbols: tuple[str, ...] = ()) -> dict:
    """NIFTY 100 stocks with price/change/volume/market cap, 1-month sparkline and volume-shock ratio.
    extra_symbols: more NSE symbols to price (popular / watchlist companies). Never raises."""
    out: dict = {"as_of": _now(), "stocks": [], "extra": {}, "sources": [], "notes": []}
    rows: list[dict] = []
    try:
        rows = _nse_constituents("NIFTY 100")
        out["sources"].append("NSE India (NIFTY 100, live)")
    except Exception as e:  # noqa: BLE001
        out["notes"].append(f"NSE stock data not available ({type(e).__name__}); using Yahoo Finance (delayed).")
        try:
            rows = [{"symbol": u["symbol"], "name": u["name"], "industry": u.get("industry", "")}
                    for u in nifty100_list()]
        except Exception as e2:  # noqa: BLE001
            out["notes"].append(f"NIFTY 100 list not available ({type(e2).__name__}).")

    syms = [r["symbol"] for r in rows]
    extra = [s for s in dict.fromkeys(x.upper() for x in extra_symbols if x) if s not in syms]
    hist = None
    if syms or extra:
        try:
            hist = _download([f"{s}.NS" for s in syms + extra], "3mo", "1d")
            out["sources"].append("Yahoo Finance (price history)")
        except Exception as e:  # noqa: BLE001
            out["notes"].append(f"Yahoo Finance price history not available ({type(e).__name__}).")

    def enrich(r: dict) -> dict:
        df = _frame(hist, f"{r['symbol']}.NS")
        if df is not None and len(df) >= 2:
            closes = df["Close"].tolist()
            r["spark"] = [float(x) for x in closes[-22:]]
            if r.get("price") is None:
                last, prev = float(closes[-1]), float(closes[-2])
                r.update({"price": last, "change": last - prev,
                          "change_pct": (last / prev - 1) * 100 if prev else None,
                          "volume": float(df["Volume"].iloc[-1]) if "Volume" in df else None})
                r["value"] = (r["volume"] or 0) * last
            if "Volume" in df and len(df) > 5:
                vols = df["Volume"].tolist()
                avg = sum(vols[-21:-1]) / max(1, len(vols[-21:-1]))
                today = r.get("volume") or float(vols[-1])
                r["vol_avg20"] = avg
                r["vol_ratio"] = (today / avg) if avg else None
            if r.get("year_high") is None:
                r["year_high"] = float(df["High"].max())
                r["year_low"] = float(df["Low"].min())
        return r

    rows = [enrich(r) for r in rows]
    out["extra"] = {s: enrich({"symbol": s, "name": s}) for s in extra}
    if rows and not any(r.get("mcap_cr") for r in rows):
        try:
            caps = _yahoo_mcaps([r["symbol"] for r in rows])
            for r in rows:
                if caps.get(r["symbol"]):
                    r["mcap_cr"], r["mcap_kind"] = caps[r["symbol"]], "full"
        except Exception as e:  # noqa: BLE001
            out["notes"].append(f"Market caps not available ({type(e).__name__}).")
    out["stocks"] = [r for r in rows if r.get("price") is not None]
    return out


def lists_from(stocks: list[dict], n: int = 10) -> dict[str, list[dict]]:
    """Ready-made lists for the Home page tabs."""
    ok = [r for r in stocks if r.get("change_pct") is not None]
    near_high = [r for r in ok if r.get("year_high") and r["price"] >= 0.98 * r["year_high"]]
    near_low = [r for r in ok if r.get("year_low") and r["price"] <= 1.02 * r["year_low"]]
    return {
        "gainers": sorted([r for r in ok if r["change_pct"] > 0], key=lambda r: -r["change_pct"])[:n],
        "losers": sorted([r for r in ok if r["change_pct"] < 0], key=lambda r: r["change_pct"])[:n],
        "volume": sorted([r for r in ok if r.get("vol_ratio")], key=lambda r: -r["vol_ratio"])[:n],
        "traded": sorted([r for r in ok if r.get("value")], key=lambda r: -r["value"])[:n],
        "high52": sorted(near_high, key=lambda r: -(r["price"] / r["year_high"]))[:n],
        "low52": sorted(near_low, key=lambda r: r["price"] / r["year_low"])[:n],
        "mcap": sorted([r for r in stocks if r.get("mcap_cr")], key=lambda r: -r["mcap_cr"])[:n],
    }


def sector_breakdown(stocks: list[dict]) -> list[dict]:
    """Average change of NIFTY 100 companies per industry (NSE industry names)."""
    groups: dict[str, list[float]] = {}
    for r in stocks:
        if r.get("industry") and r.get("change_pct") is not None:
            groups.setdefault(r["industry"], []).append(r["change_pct"])
    rows = [{"industry": k, "change_pct": sum(v) / len(v), "count": len(v)} for k, v in groups.items()]
    return sorted(rows, key=lambda r: -r["change_pct"])
