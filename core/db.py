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
            "DATABASE_URL is not set. Copy .env.example to .env and fill in your Supabase connection string."
        )
    # prepare_threshold=None keeps it compatible with Supabase's pgbouncer poolers
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


def ping() -> bool:
    try:
        fetch_one("select 1 as ok")
        return True
    except Exception:
        return False
