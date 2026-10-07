"""HTTP client for Screener.in public company pages and the JSON endpoints the page itself uses.

Screener company pages are server-rendered HTML, so plain `requests` is enough (fast,
no browser).  The "+" breakdown rows, the peers table and the price chart are loaded by
the page through small JSON/HTML endpoints; we call the same endpoints.

Be polite: requests are rate limited (SCRAPER_DELAY_SECONDS) and only made on demand.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Callable, Optional

import requests

from core.config import get_settings
from core.utils import clean_text, parse_number
from scraper.parser import FIN_SECTIONS, parse_company_page, parse_peers_html

log = logging.getLogger(__name__)

BASE = "https://www.screener.in"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


class ScreenerError(RuntimeError):
    pass


class CompanyNotFound(ScreenerError):
    pass


ProgressCb = Optional[Callable[[str, float], None]]


class ScreenerClient:
    def __init__(self, delay: Optional[float] = None):
        s = get_settings()
        self.delay = s.scraper_delay if delay is None else delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept-Language": "en-IN,en;q=0.9",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Referer": BASE + "/",
        })
        if s.screener_sessionid:
            self.session.cookies.set("sessionid", s.screener_sessionid, domain="www.screener.in")
        self._lock = threading.Lock()
        self._last = 0.0

    # ------------------------------------------------------------ http
    def _get(self, path_or_url: str, *, params: dict | None = None, expect_json: bool = False,
             retries: int = 3):
        url = path_or_url if path_or_url.startswith("http") else BASE + path_or_url
        last_err: Exception | None = None
        for attempt in range(retries):
            with self._lock:
                wait = self.delay - (time.monotonic() - self._last)
                if wait > 0:
                    time.sleep(wait)
                self._last = time.monotonic()
            try:
                r = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 404:
                raise CompanyNotFound(f"Not found on Screener: {url}")
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = ScreenerError(f"HTTP {r.status_code} from Screener")
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise ScreenerError(f"HTTP {r.status_code} for {url}")
            if expect_json:
                try:
                    return r.json()
                except ValueError as e:
                    raise ScreenerError(f"Invalid JSON from {url}") from e
            return r
        raise ScreenerError(f"Failed to fetch {url}: {last_err}")

    # ------------------------------------------------------------ search
    def search(self, query: str) -> list[dict]:
        """Screener's own typeahead search -> [{id, name, url, slug}]"""
        if not query.strip():
            return []
        data = self._get("/api/company/search/", params={"q": query.strip(), "v": 3, "fts": 1},
                         expect_json=True)
        out = []
        for item in data or []:
            url = item.get("url") or ""
            m = re.match(r"/company/([^/]+)/", url)
            if not m:
                continue
            out.append({"id": item.get("id"), "name": item.get("name"), "url": url, "slug": m.group(1)})
        return out

    @staticmethod
    def company_path(slug: str, basis: str) -> str:
        slug = slug.strip().upper() if not slug.isdigit() else slug.strip()
        return f"/company/{slug}/consolidated/" if basis == "consolidated" else f"/company/{slug}/"

    # ------------------------------------------------------------ main fetch
    def fetch_company(self, slug: str, basis: str = "consolidated", *, include_schedules: bool = True,
                      include_prices: bool = True, progress: ProgressCb = None) -> dict:
        def tick(msg: str, frac: float):
            if progress:
                progress(msg, frac)

        path = self.company_path(slug, basis)
        tick("Downloading company page", 0.05)
        resp = self._get(path)
        payload = parse_company_page(resp.text, resp.url, basis)
        if basis == "consolidated" and not _has_numbers(payload):
            # company publishes no consolidated statements -> fall back to standalone
            tick("No consolidated figures; switching to standalone", 0.1)
            resp = self._get(self.company_path(slug, "standalone"))
            payload = parse_company_page(resp.text, resp.url, "standalone")
            payload.setdefault("warnings", []).append(
                "Consolidated statements are not available for this company; standalone figures shown.")
        meta = payload["meta"]
        meta["screener_slug"] = slug.upper() if not slug.isdigit() else slug
        cid, wid = meta.get("screener_company_id"), meta.get("screener_warehouse_id")
        is_cons = meta["basis"] == "consolidated"

        if wid:
            tick("Loading peer comparison", 0.2)
            try:
                r = self._get(f"/api/company/{wid}/peers/")
                payload["peers"] = parse_peers_html(r.text)
            except ScreenerError as e:
                log.warning("peers failed: %s", e)
                payload.setdefault("warnings", []).append(f"Peers not loaded: {e}")

        if include_schedules and cid:
            jobs = [(sid, row) for sid, sec in payload["sections"].items() for row in sec["rows"]
                    if row.get("schedule_parent")]
            for i, (sid, row) in enumerate(jobs):
                tick(f"Loading breakdown: {FIN_SECTIONS.get(sid, sid)} → {row['metric']}",
                     0.25 + 0.5 * i / max(len(jobs), 1))
                params = {"parent": row["schedule_parent"], "section": sid}
                if is_cons:
                    params["consolidated"] = ""
                try:
                    data = self._get(f"/api/company/{cid}/schedules/", params=params, expect_json=True)
                except ScreenerError as e:
                    payload.setdefault("warnings", []).append(f"Breakdown {row['metric']} not loaded: {e}")
                    continue
                labels = [c["label"] for c in payload["sections"][sid]["columns"]]
                subs = {}
                for sub_name, per in (data or {}).items():
                    if not isinstance(per, dict) or sub_name == "setAttributes":
                        continue
                    texts = [clean_text(per.get(lbl, "")) for lbl in labels]
                    if not any(texts):
                        continue
                    subs[clean_text(sub_name)] = {"values": texts, "numbers": [parse_number(t) for t in texts]}
                row["schedules"] = subs

        if include_prices and cid:
            tick("Loading price history", 0.8)
            cons = "true" if is_cons else "false"
            try:
                data = self._get(f"/api/company/{cid}/chart/",
                                 params={"q": "Price-DMA50-DMA200-Volume", "days": 1825, "consolidated": cons},
                                 expect_json=True)
                payload["price_history"] = _merge_price_datasets(data)
            except ScreenerError as e:
                payload.setdefault("warnings", []).append(f"Price history not loaded: {e}")
            try:
                data = self._get(f"/api/company/{cid}/chart/",
                                 params={"q": "Price to Earning-Median PE-EPS", "days": 1825, "consolidated": cons},
                                 expect_json=True)
                payload["pe_history"] = {
                    ds.get("metric") or ds.get("label"): [[v[0], parse_number(v[1])] for v in ds.get("values", [])]
                    for ds in (data or {}).get("datasets", [])
                }
            except ScreenerError as e:
                payload.setdefault("warnings", []).append(f"P/E history not loaded: {e}")

        tick("Parsed successfully", 1.0)
        return payload


def _has_numbers(payload: dict) -> bool:
    for sec in payload.get("sections", {}).values():
        for row in sec.get("rows", []):
            if any(n is not None for n in row.get("numbers", [])):
                return True
    return False


def _merge_price_datasets(data: dict) -> list[dict]:
    by_date: dict[str, dict] = {}
    key_map = {"price": "close", "dma50": "dma50", "dma200": "dma200", "volume": "volume"}
    for ds in (data or {}).get("datasets", []):
        metric = (ds.get("metric") or "").lower().replace(" ", "")
        key = key_map.get(metric)
        if not key:
            continue
        for v in ds.get("values", []):
            if not v:
                continue
            d = str(v[0])[:10]
            by_date.setdefault(d, {"date": d})[key] = parse_number(v[1]) if len(v) > 1 else None
    return [by_date[d] for d in sorted(by_date)]
