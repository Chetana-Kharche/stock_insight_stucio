"""Thin PostgreSQL (Supabase) access layer built on psycopg 3."""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Optional, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from core.config import get_settings

_local = threading.local()


class DatabaseNotConfigured(RuntimeError):
    pass


def _connect() -> psycopg.Connection:
    url = get_settings().database_url
    if not url or "YOUR-" in url:
        raise DatabaseNotConfigured(
            "DATABASE_URL is not set. Copy .env.example to .env and fill in your Supabase Session pooler connection string."
        )
    # prepare_threshold=None keeps it compatible with Supabase's poolers
    return psycopg.connect(url, row_factory=dict_row, prepare_threshold=None, connect_timeout=15)


def _get_conn() -> psycopg.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None or conn.closed or conn.broken:
        conn = _connect()
        _local.conn = conn
    return conn


@contextmanager
def transaction() -> Iterator[psycopg.Cursor]:
    """Yield a cursor inside a transaction; commit on success, rollback on error.

    Retries the connection once if the pooled connection was dropped by the server.
    """
    try:
        conn = _get_conn()
        conn.execute("select 1")
    except psycopg.OperationalError:
        _local.conn = None
        conn = _get_conn()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            _local.conn = None
        raise


def fetch_all(sql: str, params: Sequence[Any] | dict | None = None) -> list[dict]:
    with transaction() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall()) if cur.description else []


def fetch_one(sql: str, params: Sequence[Any] | dict | None = None) -> Optional[dict]:
    with transaction() as cur:
        cur.execute(sql, params)
        return cur.fetchone() if cur.description else None


def execute(sql: str, params: Sequence[Any] | dict | None = None) -> None:
    with transaction() as cur:
        cur.execute(sql, params)


def executemany(sql: str, rows: Iterable[Sequence[Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    with transaction() as cur:
        cur.executemany(sql, rows)


def jsonb(value: Any) -> Jsonb:
    """Wrap a python object for a jsonb column (handles dates/decimals)."""
    return Jsonb(value, dumps=lambda o: json.dumps(o, default=str))


_last_error: Optional[str] = None


def ping() -> bool:
    global _last_error
    try:
        fetch_one("select 1 as ok")
        _last_error = None
        return True
    except Exception as e:  # noqa: BLE001
        _last_error = f"{type(e).__name__}: {e}"
        return False


def last_error() -> Optional[str]:
    """The real reason the last ping() failed (shown on screen to help fix .env)."""
    return _last_error


_schema_checked = False

REQUIRED_TABLES = ("profiles", "companies", "scrape_runs", "financial_facts", "summary_ratios", "peers",
                   "company_documents", "price_history", "news_items", "analysis_reports", "chat_messages", "rag_sync",
                   "user_notes", "watchlist", "portfolio_holdings", "external_data", "company_links", "report_quality_checks")


def missing_tables() -> list[str]:
    rows = fetch_all("select tbl from unnest(%s::text[]) as tbl where to_regclass('public.' || tbl) is null",
                     (list(REQUIRED_TABLES),))
    return [r["tbl"] for r in rows]


def ensure_schema() -> Optional[str]:
    """Create any missing tables from sql/schema.sql (once per app process).

    The script only uses CREATE ... IF NOT EXISTS / CREATE OR REPLACE VIEW, so existing data is never touched.
    Returns an error text, or None when everything is in place.
    """
    global _schema_checked
    if _schema_checked:
        return None
    try:
        if missing_tables():
            from pathlib import Path

            execute((Path(__file__).resolve().parent.parent / "sql" / "schema.sql").read_text(encoding="utf-8"))
            still = missing_tables()
            if still:
                return "tables still missing: " + ", ".join(still)
        _schema_checked = True
        return None
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"
