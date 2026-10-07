"""Keep RAGFlow in sync with the database: one dataset + one chat assistant per company.

Called automatically (in a background thread) after every fetch, analysis report and news
refresh, and can be run for all companies with:  python -m scripts.rag_sync_all
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from core import repository as repo
from core.config import get_settings
from rag import documents as D
from rag.ragflow_client import RagFlowClient, RagFlowError

log = logging.getLogger(__name__)
_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(company_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(company_id, threading.Lock())


def dataset_name(company: dict) -> str:
    key = company.get("nse_symbol") or company.get("screener_slug") or str(company["id"])
    return f"sis_{key}"


def chat_name(company: dict) -> str:
    return f"sis_chat_{company.get('nse_symbol') or company.get('screener_slug') or company['id']}"


def build_company_docs(company: dict) -> tuple[dict[str, str], Optional[int], Optional[int]]:
    """Return ({filename: markdown}, run_id, report_id) from the latest stored data."""
    run = repo.latest_run(company["id"])
    if not run:
        return {}, None, None
    full = repo.get_run(run["id"])
    payload = full["payload"]
    sym = company.get("nse_symbol") or company.get("screener_slug") or str(company["id"])
    docs = {
        f"{sym}_profile.md": D.profile_doc(payload),
        f"{sym}_financials.md": D.financials_doc(payload),
        f"{sym}_announcements.md": D.documents_doc(payload),
    }
    news = repo.list_news(company["id"], limit=30)
    if news:
        docs[f"{sym}_news.md"] = D.news_doc(company["name"], news)
    rep = repo.latest_report(company["id"])
    if rep:
        docs[f"{sym}_analysis_report.md"] = D.report_doc(rep["report"])
    return docs, run["id"], (rep["id"] if rep else None)


def sync_company(company_id: int, wait_seconds: int = 240) -> dict:
    """Upload fresh documents for a company, parse them, ensure a chat assistant exists."""
    s = get_settings()
    if not s.rag_configured:
        return {"status": "disabled", "message": "RAGFlow is not configured (see .env)."}
    company = repo.get_company(company_id)
    if not company:
        return {"status": "failed", "message": "company not found"}
    lock = _lock_for(company_id)
    if not lock.acquire(blocking=False):
        return {"status": "syncing", "message": "sync already running"}
    try:
        client = RagFlowClient()
        docs, run_id, report_id = build_company_docs(company)
        if not docs:
            return {"status": "failed", "message": "no stored data to sync"}
        repo.set_rag_state(company_id, status="syncing", message="uploading documents")
        ds = client.get_or_create_dataset(dataset_name(company), f"Stored Screener data, news and reports for {company['name']}")
        state = repo.get_rag_state(company_id) or {}
        old_ids = list((state.get("document_ids") or {}).values())
        # remove any stale files with the same names (also covers a lost state row)
        try:
            existing = client.list_documents(ds["id"])
            old_ids += [d["id"] for d in existing if d.get("name") in docs]
        except RagFlowError:
            pass
        client.delete_documents(ds["id"], list(set(old_ids)))
        new_ids = {}
        for fname, text in docs.items():
            d = client.upload_document(ds["id"], fname, text)
            new_ids[fname] = d["id"]
        client.parse_documents(ds["id"], list(new_ids.values()))
        repo.set_rag_state(company_id, dataset_id=ds["id"], document_ids=new_ids, status="parsing",
                           message="RAGFlow is chunking and embedding documents")
        # wait for parsing (embedding) to finish
        deadline = time.time() + wait_seconds
        done = False
        while time.time() < deadline:
            docs_state = {d["id"]: d for d in client.list_documents(ds["id"])}
            runs = [str(docs_state.get(i, {}).get("run", "")).upper() for i in new_ids.values()]
            if any(r in ("FAIL", "CANCEL") for r in runs):
                raise RagFlowError(f"document parsing failed: {runs}")
            if runs and all(r == "DONE" for r in runs):
                done = True
                break
            time.sleep(4)
        chat = client.find_chat(chat_name(company))
        if chat is None:
            if not done:
                repo.set_rag_state(company_id, status="parsing", message="still parsing; chat will be created on next sync")
                return {"status": "parsing"}
            chat = client.create_chat(chat_name(company), [ds["id"]], company["name"])
        elif ds["id"] not in [d.get("id") for d in chat.get("datasets", [])] and chat.get("dataset_ids") != [ds["id"]]:
            try:
                client.update_chat_datasets(chat["id"], [ds["id"]])
            except RagFlowError:
                pass
        repo.set_rag_state(company_id, dataset_id=ds["id"], chat_id=chat["id"], document_ids=new_ids,
                           last_run_id=run_id, last_report_id=report_id, status="ready" if done else "parsing",
                           message=f"{len(new_ids)} documents indexed", last_synced_at=repo.now_utc())
        return {"status": "ready" if done else "parsing", "chat_id": chat["id"]}
    except Exception as e:  # noqa: BLE001
        log.exception("RAG sync failed")
        try:
            repo.set_rag_state(company_id, status="failed", message=str(e)[:500])
        except Exception:  # noqa: BLE001
            pass
        return {"status": "failed", "message": str(e)}
    finally:
        lock.release()


def sync_company_async(company_id: int) -> None:
    """Fire-and-forget background sync (used after fetch / report / news)."""
    if not get_settings().rag_configured:
        return
    threading.Thread(target=sync_company, args=(company_id,), daemon=True, name=f"rag-sync-{company_id}").start()


def sync_all_pending() -> list[tuple[str, dict]]:
    results = []
    for c in repo.companies_needing_rag_sync():
        results.append((c["name"], sync_company(c["id"])))
    return results
