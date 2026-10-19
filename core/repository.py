"""All database reads/writes used by the app (companies, runs, facts, reports, news, chat, rag)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from core import db

# =====================================================================
# Profiles
# =====================================================================

def upsert_profile(user_id: str, email: str, full_name: str | None = None) -> None:
    db.execute(
        """insert into profiles (id, email, full_name, last_login) values (%s, %s, %s, now())
           on conflict (id) do update set email = excluded.email,
               full_name = coalesce(excluded.full_name, profiles.full_name), last_login = now()""",
        (user_id, email, full_name),
    )


# =====================================================================
# Companies
# =====================================================================

def count_companies() -> int:
    row = db.fetch_one("select count(*) as n from companies")
    return int(row["n"]) if row else 0


def list_companies() -> list[dict]:
    return db.fetch_all(
        "select id, nse_symbol, screener_slug, name from companies order by name")


def get_company(company_id: int) -> Optional[dict]:
    return db.fetch_one("select * from companies where id = %s", (company_id,))


def find_company(text: str) -> Optional[dict]:
    t = text.strip()
    if not t:
        return None
    row = db.fetch_one(
        "select * from companies where upper(nse_symbol) = upper(%s) or upper(screener_slug) = upper(%s) limit 1",
        (t, t))
    if row:
        return row
    return db.fetch_one(
        "select * from companies where lower(name) = lower(%s) or lower(name) like lower(%s) "
        "order by length(name) limit 1", (t, t + "%"))


def upsert_companies_bulk(rows: list[dict]) -> int:
    """rows: dicts with nse_symbol, name, isin, series, listing_date, face_value."""
    db.executemany(
        """insert into companies (nse_symbol, screener_slug, name, isin, series, listing_date, face_value, source)
           values (%s, %s, %s, %s, %s, %s, %s, 'NSE_EQUITY_L')
           on conflict (nse_symbol) do update set name = excluded.name, isin = excluded.isin,
               series = excluded.series, listing_date = excluded.listing_date,
               face_value = excluded.face_value, updated_at = now()""",
        [(r["nse_symbol"], r["nse_symbol"], r["name"], r.get("isin"), r.get("series"),
          r.get("listing_date"), r.get("face_value")) for r in rows],
    )
    return len(rows)


def add_company_from_search(slug: str, name: str, screener_id: int | None) -> dict:
    """A company found through Screener search that is not in the NSE list (e.g. BSE-only)."""
    row = db.fetch_one("select * from companies where upper(screener_slug) = upper(%s)", (slug,))
    if row:
        return row
    nse = None if slug.isdigit() else slug.upper()
    if nse:
        existing = db.fetch_one("select * from companies where nse_symbol = %s", (nse,))
        if existing:
            return existing
    return db.fetch_one(
        """insert into companies (nse_symbol, screener_slug, name, screener_company_id, source)
           values (%s, %s, %s, %s, 'SCREENER_SEARCH') returning *""",
        (nse, slug.upper() if nse else slug, name, screener_id))


def update_company_meta(company_id: int, meta: dict) -> None:
    db.execute(
        """update companies set
             screener_company_id = coalesce(%s, screener_company_id),
             screener_warehouse_id = coalesce(%s, screener_warehouse_id),
             bse_code = coalesce(%s, bse_code), website = coalesce(%s, website),
             broad_sector = coalesce(%s, broad_sector), sector = coalesce(%s, sector),
             broad_industry = coalesce(%s, broad_industry), industry = coalesce(%s, industry),
             updated_at = now()
           where id = %s""",
        (meta.get("screener_company_id"), meta.get("screener_warehouse_id"), meta.get("bse_code"),
         meta.get("website"), meta.get("broad_sector"), meta.get("sector"), meta.get("broad_industry"),
         meta.get("industry"), company_id))


# =====================================================================
# Scrape runs + structured facts
# =====================================================================

def create_run(company_id: int, user_id: str | None, basis: str, source_url: str) -> int:
    row = db.fetch_one(
        "insert into scrape_runs (company_id, user_id, basis, source_url) values (%s,%s,%s,%s) returning id",
        (company_id, user_id, basis, source_url))
    return int(row["id"])


def fail_run(run_id: int, error: str) -> None:
    db.execute(
        """update scrape_runs set status='failed', error=%s, finished_at=now(),
               duration_ms = (extract(epoch from (now() - started_at)) * 1000)::int where id=%s""",
        (error[:2000], run_id))


def flatten_facts(payload: dict) -> list[dict]:
    """Turn the parsed payload into long-format rows (one row per number)."""
    facts: list[dict] = []

    def add_table(section_key: str, table: dict, parent: str | None = None):
        cols = table.get("columns", [])
        for row in table.get("rows", []):
            for col, vt, num in zip(cols, row["values"], row["numbers"]):
                if vt == "" and num is None:
                    continue
                facts.append({
                    "section": section_key, "metric": row["metric"], "parent_metric": parent,
                    "period_label": col["label"], "period_date": col["date"], "period_type": col["type"],
                    "value": num, "value_text": vt, "unit": row["unit"], "row_order": row["order"],
                })
            for sub_name, sub in (row.get("schedules") or {}).items():
                for col, vt, num in zip(cols, sub["values"], sub["numbers"]):
                    if vt == "" and num is None:
                        continue
                    unit = "PERCENT" if (vt.endswith("%") or "%" in sub_name) else row["unit"]
                    facts.append({
                        "section": section_key, "metric": sub_name, "parent_metric": row["metric"],
                        "period_label": col["label"], "period_date": col["date"], "period_type": col["type"],
                        "value": num, "value_text": vt, "unit": unit, "row_order": row["order"],
                    })

    for sid, table in payload.get("sections", {}).items():
        add_table(sid, table)
    for key in ("quarterly", "yearly"):
        t = payload.get("shareholding", {}).get(key)
        if t:
            add_table(f"shareholding-{key}", t)
    for g in payload.get("growth", []):
        for i, item in enumerate(g["rows"]):
            facts.append({
                "section": "growth", "metric": g["title"], "parent_metric": None,
                "period_label": item["period"], "period_date": None, "period_type": "range",
                "value": item["value"], "value_text": item["value_text"], "unit": "PERCENT", "row_order": i,
            })
    return facts


def save_successful_run(run_id: int, company_id: int, payload: dict) -> int:
    """Store payload + all structured rows in ONE transaction. Returns number of facts."""
    meta = payload["meta"]
    basis = meta["basis"]
    facts = flatten_facts(payload)
    with db.transaction() as cur:
        cur.execute(
            """update scrape_runs set status='success', payload=%s, parser_version=%s, latest_period=%s,
                   basis=%s, source_url=%s, finished_at=now(),
                   duration_ms=(extract(epoch from (now() - started_at)) * 1000)::int
               where id=%s""",
            (db.jsonb(payload), meta.get("parser_version"), meta.get("latest_period"), basis,
             meta.get("source_url"), run_id))
        cur.executemany(
            """insert into financial_facts (run_id, company_id, basis, section, metric, parent_metric,
                   period_label, period_date, period_type, value, value_text, unit, row_order)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [(run_id, company_id, basis, f["section"], f["metric"], f["parent_metric"], f["period_label"],
              f["period_date"], f["period_type"], f["value"], f["value_text"], f["unit"], f["row_order"])
             for f in facts])
        cur.executemany(
            """insert into summary_ratios (run_id, company_id, name, value, value2, value_text, unit)
               values (%s,%s,%s,%s,%s,%s,%s)""",
            [(run_id, company_id, r["name"], r["value"], r["value2"], r["value_text"], r["unit"])
             for r in payload.get("summary_ratios", [])])
        peers = payload.get("peers") or {}
        peer_rows = [(run_id, company_id, int(p["rank"]) if p.get("rank") else None, p["name"], p.get("url"),
                      False, db.jsonb(p["numbers"])) for p in peers.get("rows", [])]
        if peers.get("median"):
            m = peers["median"]
            peer_rows.append((run_id, company_id, None, m["name"], None, True, db.jsonb(m["numbers"])))
        cur.executemany(
            """insert into peers (run_id, company_id, rank, peer_name, peer_url, is_median, metrics)
               values (%s,%s,%s,%s,%s,%s,%s)""", peer_rows)
        docs = payload.get("documents", {})
        doc_rows = []
        for a in docs.get("announcements", []):
            doc_rows.append((run_id, company_id, "announcement", a["title"], a["url"], a.get("date"),
                             a.get("summary"), None))
        for a in docs.get("annual_reports", []):
            doc_rows.append((run_id, company_id, "annual_report", a["title"], a["url"], None, None,
                             db.jsonb({"year": a.get("year"), "source": a.get("source")})))
        for a in docs.get("credit_ratings", []):
            doc_rows.append((run_id, company_id, "credit_rating", a["title"], a["url"], None, a.get("meta"), None))
        for a in docs.get("concalls", []):
            doc_rows.append((run_id, company_id, "concall", a["period"], None, None, None,
                             db.jsonb({"links": a["links"]})))
        cur.executemany(
            """insert into company_documents (run_id, company_id, doc_type, title, url, doc_date, summary, extra)
               values (%s,%s,%s,%s,%s,%s,%s,%s)""", doc_rows)
        prices = payload.get("price_history") or []
        cur.executemany(
            """insert into price_history (company_id, trade_date, close, dma50, dma200, volume)
               values (%s,%s,%s,%s,%s,%s)
               on conflict (company_id, trade_date) do update set close=excluded.close,
                   dma50=excluded.dma50, dma200=excluded.dma200, volume=excluded.volume""",
            [(company_id, p["date"], p.get("close"), p.get("dma50"), p.get("dma200"), p.get("volume"))
             for p in prices])
    update_company_meta(company_id, meta)
    return len(facts)


def get_run(run_id: int) -> Optional[dict]:
    return db.fetch_one(
        """select r.*, c.name as company_name, c.nse_symbol from scrape_runs r
           join companies c on c.id = r.company_id where r.id = %s""", (run_id,))


def latest_run(company_id: int, basis: str | None = None) -> Optional[dict]:
    if basis:
        return db.fetch_one(
            """select * from scrape_runs where company_id=%s and basis=%s and status='success'
               order by started_at desc limit 1""", (company_id, basis))
    return db.fetch_one(
        """select * from scrape_runs where company_id=%s and status='success'
           order by started_at desc limit 1""", (company_id,))


def list_runs(user_id: str | None = None, company_id: int | None = None, limit: int = 100) -> list[dict]:
    where, params = ["1=1"], []
    if user_id:
        where.append("r.user_id = %s")
        params.append(user_id)
    if company_id:
        where.append("r.company_id = %s")
        params.append(company_id)
    params.append(limit)
    return db.fetch_all(
        f"""select r.id, r.company_id, c.name as company_name, c.nse_symbol, r.basis, r.status, r.error,
                   r.latest_period, r.started_at, r.duration_ms,
                   (select count(*) from financial_facts f where f.run_id = r.id) as facts
            from scrape_runs r join companies c on c.id = r.company_id
            where {' and '.join(where)} order by r.started_at desc limit %s""", params)


def query_facts(company_id: int, section: str | None = None, metric: str | None = None,
                basis: str | None = None) -> list[dict]:
    """Facts from the latest successful run of a company (optionally filtered)."""
    run = latest_run(company_id, basis)
    if not run:
        return []
    where, params = ["run_id = %s"], [run["id"]]
    if section:
        where.append("section = %s")
        params.append(section)
    if metric:
        where.append("lower(metric) = lower(%s)")
        params.append(metric)
    return db.fetch_all(
        f"""select section, metric, parent_metric, period_label, period_date, period_type, value, value_text, unit
            from financial_facts where {' and '.join(where)} order by section, row_order, period_date nulls last""",
        params)


# =====================================================================
# Analysis reports
# =====================================================================

def save_report(company_id: int, run_id: int | None, user_id: str | None, report: dict) -> int:
    row = db.fetch_one(
        """insert into analysis_reports (company_id, run_id, user_id, stance, score, model, report)
           values (%s,%s,%s,%s,%s,%s,%s) returning id""",
        (company_id, run_id, user_id, report.get("stance"), report.get("score"), report.get("model"),
         db.jsonb(report)))
    rid = int(row["id"])
    try:
        try:
            save_quality_checks(rid, company_id, user_id, report)
        except Exception as e:  # noqa: BLE001 - table not created yet (older database): create it, retry once
            if "does not exist" not in str(e):
                raise
            db._schema_checked = False
            db.ensure_schema()
            save_quality_checks(rid, company_id, user_id, report)
    except Exception as e:  # noqa: BLE001 - the audit log must never block saving the report
        import logging

        logging.getLogger(__name__).warning("Could not store the report check log: %s", e)
    return rid


def save_quality_checks(report_id: int, company_id: int, user_id: str | None, report: dict) -> None:
    """Audit log of the automatic checks for one report (shown in Profile → System status)."""
    q = report.get("quality_checks") or {}
    if not q:
        return
    s = q.get("summary") or {}
    db.execute(
        """insert into report_quality_checks (report_id, company_id, user_id, narrative_outcome, model, total_checks,
               passed, fixed, warnings, failed, removed_sentences, checks, removed_text, removed_values)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (report_id, company_id, user_id, report.get("narrative_check"), report.get("model"), s.get("total"),
         s.get("pass"), s.get("fixed"), s.get("warn"), s.get("fail"), s.get("removed_sentences"),
         db.jsonb(q.get("checks") or []), db.jsonb(q.get("removed_text") or []),
         db.jsonb((report.get("supplementary") or {}).get("removed_by_checks") or [])))


def list_quality_checks(limit: int = 50, company_id: int | None = None) -> list[dict]:
    where, params = ["1=1"], []
    if company_id:
        where.append("q.company_id = %s")
        params.append(company_id)
    params.append(limit)
    return db.fetch_all(
        f"""select q.id, q.report_id, q.created_at, c.name as company_name, c.nse_symbol, q.narrative_outcome, q.model,
                   q.total_checks, q.passed, q.fixed, q.warnings, q.failed, q.removed_sentences
            from report_quality_checks q join companies c on c.id = q.company_id
            where {' and '.join(where)} order by q.created_at desc limit %s""", params)


def get_quality_checks(check_id: int) -> Optional[dict]:
    return db.fetch_one("select * from report_quality_checks where id = %s", (check_id,))


def list_reports(user_id: str | None = None, company_id: int | None = None, limit: int = 100) -> list[dict]:
    where, params = ["1=1"], []
    if user_id:
        where.append("a.user_id = %s")
        params.append(user_id)
    if company_id:
        where.append("a.company_id = %s")
        params.append(company_id)
    params.append(limit)
    return db.fetch_all(
        f"""select a.id, a.company_id, c.name as company_name, c.nse_symbol, a.run_id, a.stance, a.score,
                   a.model, a.created_at, a.report->>'headline' as headline
            from analysis_reports a join companies c on c.id = a.company_id
            where {' and '.join(where)} order by a.created_at desc limit %s""", params)


def get_report(report_id: int) -> Optional[dict]:
    return db.fetch_one("select * from analysis_reports where id = %s", (report_id,))


def latest_report(company_id: int) -> Optional[dict]:
    return db.fetch_one(
        "select * from analysis_reports where company_id=%s order by created_at desc limit 1", (company_id,))


# =====================================================================
# News
# =====================================================================

def upsert_news(company_id: int, items: list[dict]) -> None:
    db.executemany(
        """insert into news_items (company_id, title, url, source, published_at, summary)
           values (%s,%s,%s,%s,%s,%s)
           on conflict (company_id, url) do update set title=excluded.title, fetched_at=now()""",
        [(company_id, n["title"], n["url"], n.get("source"), n.get("published_at"), n.get("summary"))
         for n in items])


def list_news(company_id: int, limit: int = 400, per_source: int = 15) -> list[dict]:
    """Latest stored headlines, at most `per_source` from each website so no website crowds out the others."""
    return db.fetch_all(
        """select title, url, source, published_at, summary from (
               select n.*, row_number() over (partition by coalesce(source, '') order by published_at desc nulls last) rn
               from news_items n where company_id=%s) x
           where rn <= %s order by published_at desc nulls last limit %s""", (company_id, per_source, limit))


# =====================================================================
# Prices
# =====================================================================

def price_history(company_id: int) -> list[dict]:
    return db.fetch_all(
        "select trade_date, close, dma50, dma200, volume from price_history where company_id=%s order by trade_date",
        (company_id,))


# =====================================================================
# Chat
# =====================================================================

def add_chat_message(user_id: str | None, company_id: int | None, role: str, content: str) -> None:
    db.execute("insert into chat_messages (user_id, company_id, role, content) values (%s,%s,%s,%s)",
               (user_id, company_id, role, content))


def list_chat_messages(user_id: str | None, company_id: int | None, limit: int = 50) -> list[dict]:
    rows = db.fetch_all(
        """select role, content, created_at from chat_messages
           where user_id is not distinct from %s and company_id is not distinct from %s
           order by created_at desc limit %s""", (user_id, company_id, limit))
    return list(reversed(rows))


def clear_chat(user_id: str | None, company_id: int | None) -> None:
    db.execute("delete from chat_messages where user_id is not distinct from %s and company_id is not distinct from %s",
               (user_id, company_id))


# =====================================================================
# RAG sync state
# =====================================================================

def get_rag_state(company_id: int) -> Optional[dict]:
    return db.fetch_one("select * from rag_sync where company_id=%s", (company_id,))


def set_rag_state(company_id: int, **fields: Any) -> None:
    fields = {k: (db.jsonb(v) if k == "document_ids" else v) for k, v in fields.items()}
    cols = list(fields)
    sets = ", ".join(f"{c} = excluded.{c}" for c in cols)
    db.execute(
        f"""insert into rag_sync (company_id, {', '.join(cols)}) values (%s, {', '.join(['%s'] * len(cols))})
            on conflict (company_id) do update set {sets}""",
        [company_id, *fields.values()])


def companies_needing_rag_sync() -> list[dict]:
    """Companies whose latest successful run or report is newer than what was pushed to RAGFlow."""
    return db.fetch_all(
        """select c.id, c.name, c.nse_symbol
           from companies c
           join lateral (select max(id) as run_id from scrape_runs where company_id=c.id and status='success') r on true
           left join lateral (select max(id) as report_id from analysis_reports where company_id=c.id) a on true
           left join rag_sync s on s.company_id = c.id
           where r.run_id is not null
             and (s.company_id is null or s.status = 'failed'
                  or coalesce(s.last_run_id,0) < r.run_id or coalesce(s.last_report_id,0) < coalesce(a.report_id,0))""")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)



# =====================================================================
# v2: profile, notebook, watchlist, portfolio, data from other websites
# =====================================================================

def get_profile(user_id: str) -> Optional[dict]:
    return db.fetch_one("select * from profiles where id = %s", (user_id,))


def update_profile_name(user_id: str, full_name: str) -> None:
    name = full_name.strip() or None
    db.execute("update profiles set full_name = %s where id = %s", (name, user_id))


def user_stats(user_id: str) -> dict:
    row = db.fetch_one(
        """select
             (select count(*) from scrape_runs where user_id = %(u)s and status = 'success') as fetches,
             (select count(distinct company_id) from scrape_runs where user_id = %(u)s and status = 'success') as companies,
             (select count(*) from analysis_reports where user_id = %(u)s) as reports,
             (select count(*) from user_notes where user_id = %(u)s and note_type <> 'activity') as notes,
             (select count(*) from watchlist where user_id = %(u)s) as watchlist,
             (select count(*) from portfolio_holdings where user_id = %(u)s) as holdings""", {"u": user_id})
    return {k: int(v or 0) for k, v in (row or {}).items()}


# ---------- notebook ----------
NOTE_TYPES = ("text", "outlook", "action", "activity")


def add_note(user_id: str, company_id: Optional[int], content: str, note_type: str = "text") -> None:
    if note_type not in NOTE_TYPES:
        note_type = "text"
    db.execute("insert into user_notes (user_id, company_id, note_type, content) values (%s,%s,%s,%s)",
               (user_id, company_id, note_type, content.strip()[:4000]))


def log_activity(user_id: Optional[str], company_id: Optional[int], content: str) -> None:
    """Automatic notebook entry (fetch, report, watchlist ...). Never breaks the caller."""
    if not user_id:
        return
    try:
        add_note(user_id, company_id, content, "activity")
    except Exception:  # noqa: BLE001 - e.g. tables not created yet
        pass


def list_notes(user_id: str, note_type: Optional[str] = None, company_id: Optional[int] = None,
               search: str = "", limit: int = 500) -> list[dict]:
    where, params = ["n.user_id = %s"], [user_id]
    if note_type:
        where.append("n.note_type = %s")
        params.append(note_type)
    if company_id:
        where.append("n.company_id = %s")
        params.append(company_id)
    if search.strip():
        where.append("(n.content ilike %s or c.name ilike %s or c.nse_symbol ilike %s)")
        params += [f"%{search.strip()}%"] * 3
    params.append(limit)
    return db.fetch_all(
        f"""select n.id, n.note_type, n.content, n.created_at, n.company_id, c.name as company_name, c.nse_symbol
            from user_notes n left join companies c on c.id = n.company_id
            where {' and '.join(where)} order by n.created_at desc limit %s""", params)


def delete_note(user_id: str, note_id: int) -> None:
    db.execute("delete from user_notes where id = %s and user_id = %s", (note_id, user_id))


def recent_companies(user_id: str, limit: int = 8) -> list[dict]:
    """Companies this user fetched most recently (for quick re-open)."""
    return db.fetch_all(
        """select c.id, c.name, c.nse_symbol, max(r.started_at) as last_seen
           from scrape_runs r join companies c on c.id = r.company_id
           where r.user_id = %s and r.status = 'success'
           group by c.id, c.name, c.nse_symbol order by last_seen desc limit %s""", (user_id, limit))


# ---------- watchlist ----------
def is_in_watchlist(user_id: str, company_id: int) -> bool:
    return db.fetch_one("select 1 from watchlist where user_id=%s and company_id=%s", (user_id, company_id)) is not None


def add_to_watchlist(user_id: str, company_id: int) -> None:
    db.execute("insert into watchlist (user_id, company_id) values (%s,%s) on conflict do nothing",
               (user_id, company_id))


def remove_from_watchlist(user_id: str, company_id: int) -> None:
    db.execute("delete from watchlist where user_id=%s and company_id=%s", (user_id, company_id))


def list_watchlist(user_id: str) -> list[dict]:
    return db.fetch_all(
        """select w.company_id, w.added_at, c.name, c.nse_symbol, c.bse_code, c.industry
           from watchlist w join companies c on c.id = w.company_id
           where w.user_id = %s order by w.added_at desc""", (user_id,))


# ---------- portfolio ----------
def add_holding(user_id: str, company_id: int, quantity: float, avg_price: float, buy_date=None) -> None:
    db.execute("""insert into portfolio_holdings (user_id, company_id, quantity, avg_price, buy_date)
                  values (%s,%s,%s,%s,%s)""", (user_id, company_id, quantity, avg_price, buy_date))


def delete_holding(user_id: str, holding_id: int) -> None:
    db.execute("delete from portfolio_holdings where id=%s and user_id=%s", (holding_id, user_id))


def list_holdings(user_id: str) -> list[dict]:
    return db.fetch_all(
        """select h.id, h.company_id, h.quantity, h.avg_price, h.buy_date, h.created_at,
                  c.name, c.nse_symbol, c.bse_code, c.industry
           from portfolio_holdings h join companies c on c.id = h.company_id
           where h.user_id = %s order by c.name, h.buy_date""", (user_id,))


def last_closes(company_ids: list[int]) -> dict[int, dict]:
    """Latest two Screener closing prices per company: {id: {close, prev_close, trade_date}}."""
    if not company_ids:
        return {}
    rows = db.fetch_all(
        """select company_id, trade_date, close from (
             select company_id, trade_date, close,
                    row_number() over (partition by company_id order by trade_date desc) as rn
             from price_history where company_id = any(%s) and close is not null) t
           where rn <= 2 order by company_id, trade_date desc""", (list(company_ids),))
    out: dict[int, dict] = {}
    for r in rows:
        d = out.setdefault(r["company_id"], {})
        if "close" not in d:
            d.update(close=float(r["close"]), trade_date=r["trade_date"])
        else:
            d["prev_close"] = float(r["close"])
    return out


def companies_by_symbols(symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}
    rows = db.fetch_all("select id, name, nse_symbol from companies where nse_symbol = any(%s)",
                        ([s.upper() for s in symbols],))
    return {r["nse_symbol"]: r for r in rows}


# ---------- data from other websites (cache) ----------
def save_external(company_id: int, data: dict) -> None:
    db.execute("insert into external_data (company_id, data) values (%s,%s)", (company_id, db.jsonb(data)))


def latest_external(company_id: int, max_age_hours: Optional[float] = None) -> Optional[dict]:
    if max_age_hours is None:
        row = db.fetch_one("select data, fetched_at from external_data where company_id=%s "
                           "order by fetched_at desc limit 1", (company_id,))
    else:
        row = db.fetch_one("select data, fetched_at from external_data where company_id=%s "
                           "and fetched_at > now() - make_interval(secs => %s) order by fetched_at desc limit 1",
                           (company_id, float(max_age_hours) * 3600))
    if not row:
        return None
    data = row["data"] or {}
    data["cached_at"] = str(row["fetched_at"])
    return data


# =====================================================================
# Pages of a company on other websites
# =====================================================================

def get_link(company_id: int, site: str) -> Optional[str]:
    row = db.fetch_one("select url from company_links where company_id = %s and site = %s", (company_id, site))
    return row["url"] if row else None


def save_link(company_id: int, site: str, url: str, found_by: str = "search") -> None:
    db.execute("""insert into company_links (company_id, site, url, found_by) values (%s, %s, %s, %s)
                  on conflict (company_id, site) do update set url = excluded.url, found_by = excluded.found_by,
                  found_at = now()""", (company_id, site, url, found_by))


def delete_link(company_id: int, site: str) -> None:
    db.execute("delete from company_links where company_id = %s and site = %s", (company_id, site))
