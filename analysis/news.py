"""Latest company news from Google News RSS (real, public headlines)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from time import mktime
from urllib.parse import quote_plus

import feedparser
import requests

from core.utils import clean_text

_SUFFIX = re.compile(r"\b(ltd|limited|pvt|private|inc|corp(oration)?|co)\.?$", re.I)


def short_name(name: str) -> str:
    n = clean_text(name)
    for _ in range(2):
        n = _SUFFIX.sub("", n).strip(" .,&")
    return n


def _feed(query: str) -> list:
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return feedparser.parse(r.content).entries


def fetch_news(company_name: str, nse_symbol: str | None = None, days: int = 45, limit: int = 20) -> list[dict]:
    base = short_name(company_name)
    queries = [f'"{base}" share OR stock OR results when:{days}d']
    if nse_symbol:
        queries.append(f'"{nse_symbol}" NSE when:{days}d')
    seen, items = set(), []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for q in queries:
        try:
            entries = _feed(q)
        except Exception:  # noqa: BLE001 - news is best-effort
            continue
        for e in entries:
            link = e.get("link")
            title = clean_text(e.get("title", ""))
            if not link or not title:
                continue
            src = clean_text((e.get("source") or {}).get("title", "")) if isinstance(e.get("source"), dict) else ""
            if src and title.endswith(f" - {src}"):
                title = title[: -len(src) - 3]
            key = title.lower()[:90]
            if key in seen:
                continue
            published = None
            if e.get("published_parsed"):
                published = datetime.fromtimestamp(mktime(e.published_parsed), tz=timezone.utc)
                if published < cutoff:
                    continue
            seen.add(key)
            items.append({"title": title, "url": link, "source": src, "published_at": published,
                          "summary": ""})
    items.sort(key=lambda x: x["published_at"] or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return items[:limit]
