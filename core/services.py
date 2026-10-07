"""Application services that combine scraper + database (+ RAG sync)."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from core import repository as repo
from scraper.screener_client import ScreenerClient

log = logging.getLogger(__name__)


def resolve_slug(company: dict) -> str:
    return company.get("screener_slug") or company.get("nse_symbol") or ""


def fetch_and_store(company: dict, basis: str, user_id: Optional[str], *, include_schedules: bool = True,
                    progress: Optional[Callable[[str, float], None]] = None) -> tuple[int, dict]:
    """Scrape Screener for one company, persist structured data. Returns (run_id, payload)."""
    client = ScreenerClient()
    slug = resolve_slug(company)
    if not slug:
        raise ValueError("Company has no NSE symbol / Screener slug.")
    run_id = repo.create_run(company["id"], user_id, basis, "https://www.screener.in" +
                             client.company_path(slug, basis))
    try:
        payload = client.fetch_company(slug, basis, include_schedules=include_schedules, progress=progress)
        payload["meta"]["company_db_id"] = company["id"]
        payload["meta"]["nse_symbol"] = payload["meta"].get("nse_symbol") or company.get("nse_symbol")
        n = repo.save_successful_run(run_id, company["id"], payload)
        payload["meta"]["run_id"] = run_id
        payload["meta"]["facts_stored"] = n
    except Exception as e:
        repo.fail_run(run_id, f"{type(e).__name__}: {e}")
        raise
    return run_id, payload


def refresh_news(company: dict) -> list[dict]:
    from analysis.news import fetch_news

    items = fetch_news(company["name"], company.get("nse_symbol"))
    if items:
        repo.upsert_news(company["id"], items)
    return repo.list_news(company["id"])
