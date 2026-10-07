"""Chatbot answer routing: RAGFlow assistant first, Gemini-over-DB fallback."""
from __future__ import annotations

import logging
from typing import Optional

from analysis import llm
from core import repository as repo
from core.config import get_settings
from rag import documents as D
from rag.ragflow_client import RagFlowClient, RagFlowError

log = logging.getLogger(__name__)

FALLBACK_SYSTEM = (
    "You are a financial research assistant inside Stock Insight Studio. Answer ONLY using the CONTEXT, which "
    "contains data scraped from Screener.in, exchange announcements, news headlines and an AI-assisted report. "
    "Quote periods (e.g. 'Jun 2026 quarter', 'FY26') and units (₹ crore, %). If the context does not contain the "
    "answer, say so. Never give buy/sell recommendations or price targets. Keep answers concise and use short "
    "markdown tables when comparing numbers."
)


def answer(question: str, company: Optional[dict], history: list[dict],
           rag_session_id: Optional[str] = None) -> tuple[str, str, Optional[str]]:
    """Returns (answer_text, source_label, rag_session_id)."""
    s = get_settings()
    if company and s.rag_configured:
        state = repo.get_rag_state(company["id"]) or {}
        if state.get("chat_id"):
            try:
                client = RagFlowClient()
                sid = rag_session_id or client.create_session(state["chat_id"], f"streamlit-{company['id']}")
                text, sid, _refs = client.ask(state["chat_id"], question, sid)
                if text:
                    return text, "RAGFlow knowledge base", sid
            except RagFlowError as e:
                log.warning("RAGFlow chat failed, falling back to Gemini: %s", e)

    if not llm.is_available():
        return ("The chatbot needs either RAGFlow (indexed) or a Gemini API key. Configure them in .env.",
                "not configured", rag_session_id)

    payload, report, news = None, None, []
    if company:
        run = repo.latest_run(company["id"])
        if run:
            payload = repo.get_run(run["id"])["payload"]
        rep = repo.latest_report(company["id"])
        report = rep["report"] if rep else None
        news = repo.list_news(company["id"], limit=20)
    context = D.context_for_llm(payload, report, news) if payload else "No company data stored yet."
    convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history[-8:])
    prompt = f"CONTEXT:\n{context}\n\nCONVERSATION SO FAR:\n{convo}\n\nUSER QUESTION: {question}"
    try:
        text = llm.generate_text(prompt, FALLBACK_SYSTEM, temperature=0.2, max_tokens=4096)
    except Exception as e:  # noqa: BLE001
        return f"Sorry, the AI model call failed: {e}", "error", rag_session_id
    return text or "I could not generate an answer.", f"Gemini ({llm.model_name()}) over stored data", rag_session_id
