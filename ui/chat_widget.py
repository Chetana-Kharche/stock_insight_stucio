"""Floating chatbot (bottom-right) — answers questions about the selected company."""
from __future__ import annotations

import streamlit as st

from core import repository as repo
from rag.chat import answer
from ui.html import e


def render() -> None:
    user = st.session_state.get("user") or {}
    company = st.session_state.get("company")
    with st.container(key="chat_fab"):
        label = f"💬  Ask about {company.get('nse_symbol') or 'company'}" if company else "💬  Ask AI"
        with st.popover(label):
            if not company:
                st.html('<div class="sis-chat-head"><div class="a">AI assistant</div>'
                        '<div class="b">Select and fetch a company first, then ask anything about it.</div></div>')
                return
            state = repo.get_rag_state(company["id"]) or {}
            src = "RAGFlow knowledge base" if state.get("status") == "ready" else "Gemini over stored data"
            st.html(f'<div class="sis-chat-head"><div class="a">{e(company["name"])}</div>'
                    f'<div class="b">Source: {e(src)} · answers use only stored data</div></div>')
            history = repo.list_chat_messages(user.get("id"), company["id"], limit=40)
            box = st.container(height=360, border=False)
            with box:
                if not history:
                    st.caption("Try asking:")
                    st.markdown("- *What was the net profit trend over the last 4 quarters?*\n"
                                "- *How has FII holding changed?*\n"
                                "- *Summarise the latest announcements.*")
                for m in history:
                    with st.chat_message(m["role"]):
                        st.markdown(m["content"])
            with st.form("chat_form", clear_on_submit=True, border=False):
                q = st.text_input("Your question", label_visibility="collapsed",
                                  placeholder=f"Ask about {company['name']}…")
                c1, c2 = st.columns([1.3, 1])
                send = c1.form_submit_button("Send", type="primary", use_container_width=True)
                clear = c2.form_submit_button("Clear chat", use_container_width=True)
            if clear:
                repo.clear_chat(user.get("id"), company["id"])
                st.session_state.pop("rag_session_id", None)
                st.rerun()
            if send and q.strip():
                repo.add_chat_message(user.get("id"), company["id"], "user", q.strip())
                with box:
                    with st.chat_message("user"):
                        st.markdown(q.strip())
                    with st.chat_message("assistant"):
                        with st.spinner("Thinking…"):
                            text, source, sid = answer(q.strip(), company, history,
                                                       st.session_state.get("rag_session_id"))
                        st.markdown(text)
                        st.caption(source)
                st.session_state["rag_session_id"] = sid
                repo.add_chat_message(user.get("id"), company["id"], "assistant", text)
