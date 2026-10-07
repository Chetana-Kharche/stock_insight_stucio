"""Stock Insight Studio — Streamlit entry point.

Run:  streamlit run app.py
"""
from __future__ import annotations

import logging

import streamlit as st

from core.config import APP_NAME, get_settings
from core.db import DatabaseNotConfigured, ping
from ui import auth_view, chat_widget, dashboard_view, history_view, status_view
from ui.styles import CSS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title=APP_NAME, page_icon="📈", layout="wide", initial_sidebar_state="expanded")
st.markdown(CSS, unsafe_allow_html=True)


def _config_problems() -> list[str]:
    s = get_settings()
    problems = []
    if not s.supabase_url or "YOUR-" in s.supabase_url:
        problems.append("SUPABASE_URL / SUPABASE_ANON_KEY missing in .env")
    if not s.database_url or "YOUR-" in s.database_url:
        problems.append("DATABASE_URL missing in .env")
    return problems


def main() -> None:
    problems = _config_problems()
    if problems:
        st.title(APP_NAME)
        st.error("Setup incomplete:\n\n" + "\n".join(f"- {p}" for p in problems))
        st.info("Copy `.env.example` to `.env`, fill in your Supabase details (see docs/SETUP_SUPABASE.md) "
                "and restart the app.")
        return
    try:
        if not ping():
            st.error("Cannot connect to the Supabase database. Check DATABASE_URL (use the Session pooler string).")
            return
    except DatabaseNotConfigured as e:
        st.error(str(e))
        return

    if not st.session_state.get("user"):
        auth_view.render()
        return

    user = st.session_state["user"]
    with st.sidebar:
        st.markdown(f"### {APP_NAME}")
        st.caption(f"Signed in as **{user.get('full_name') or user['email']}**")
        pages = ["Dashboard", "History", "System status"]
        if "nav_request" in st.session_state:
            st.session_state["nav"] = st.session_state.pop("nav_request")
        st.radio("Navigate", pages, key="nav", label_visibility="collapsed")
        company = st.session_state.get("company")
        if company:
            st.divider()
            st.caption("Current company")
            st.markdown(f"**{company['name']}**  \n`{company.get('nse_symbol') or company.get('screener_slug')}`")
        st.divider()
        if st.button("Sign out", use_container_width=True):
            from core.auth import sign_out

            sign_out()
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()
        st.caption("Data: Screener.in public pages, NSE, Google News. For personal/educational use; "
                   "not investment advice.")

    page = st.session_state.get("nav", "Dashboard")
    if page == "Dashboard":
        dashboard_view.render()
    elif page == "History":
        st.title("History")
        history_view.render()
    else:
        status_view.render()

    chat_widget.render()


main()
