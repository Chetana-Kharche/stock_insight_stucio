"""Stock Insight Studio — Streamlit entry point.

Run:  streamlit run app.py
"""
from __future__ import annotations

import logging

import streamlit as st

from core.config import APP_NAME, get_settings
from core.db import DatabaseNotConfigured, ensure_schema, ping
from ui import (auth_view, chat_widget, company_view, market_news_view, movers_view, notebook_view, portfolio_view,
                profile_view)
from ui import components as C
from ui.html import e
from ui.styles import CSS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title=APP_NAME, page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
st.markdown(CSS, unsafe_allow_html=True)

PAGES = {
    "Portfolio": portfolio_view.render,
    "Stocks": company_view.render,
    "Market Movers": movers_view.render,
    "Market News": market_news_view.render,
    "Notebook": notebook_view.render,
    "Profile": profile_view.render,
}


def _config_problems() -> list[str]:
    s = get_settings()
    problems = []
    if not s.supabase_url or not s.supabase_anon_key or "YOUR-" in s.supabase_url:
        problems.append("SUPABASE_URL / SUPABASE_ANON_KEY missing in .env")
    if not s.database_url or "YOUR-" in s.database_url:
        problems.append("DATABASE_URL missing in .env")
    return problems


TOP_TABS = ["Stocks", "Market Movers", "Market News"]      # horizontal menu
MENU_PAGES = ["Portfolio", "Notebook", "Profile"]          # only in the user drop-down menu


def _route() -> None:
    """Apply a page change requested by a button (drop-down menu or a link inside a page)."""
    target = st.session_state.pop("nav_request", None)
    if target in TOP_TABS:
        st.session_state["menu_page"] = None
        st.session_state["nav"] = target
        st.session_state["_nav_last"] = target
    elif target in MENU_PAGES:
        st.session_state["menu_page"] = target
        st.session_state["nav"] = None           # no tab highlighted while a menu page is open


def top_bar(user: dict) -> str:
    """Brand, main tabs and the user menu. Returns the selected page."""
    _route()
    if "nav" not in st.session_state and not st.session_state.get("menu_page"):
        st.session_state["nav"] = "Stocks"
    with st.container(key="topbar"):
        a, b, c = st.columns([2.1, 5.4, 1.5], vertical_alignment="center", gap="medium")
        with a:
            st.html('<div class="vr-brand"><div class="mark">SI</div><div class="txt">'
                    '<div class="a">Stock Insight</div><div class="b">STUDIO</div></div></div>')
        with b:
            seg = getattr(st, "segmented_control", None)
            if seg is not None:
                val = seg("Navigate", TOP_TABS, key="nav", label_visibility="collapsed")
            else:  # older Streamlit
                val = st.radio("Navigate", TOP_TABS, key="nav", horizontal=True, label_visibility="collapsed")
        with c:
            name = user.get("full_name") or user["email"].split("@")[0]
            with st.popover(f"👤 {name[:14].upper()}", use_container_width=True):
                st.html(f'<div style="font-weight:700;color:#163A5F">{e(name)}</div>'
                        f'<div style="font-size:.8rem;color:#595959;margin-bottom:6px">{e(user["email"])}</div>')
                for target in MENU_PAGES:
                    if st.button(target, key=f"menu_{target}", use_container_width=True):
                        st.session_state["nav_request"] = target
                        st.rerun()
                if st.button("Logout", key="menu_logout", use_container_width=True):
                    profile_view.do_sign_out()
    menu_page = st.session_state.get("menu_page")
    if val is not None:
        if menu_page:                        # a tab was clicked while a menu page was open
            st.session_state["menu_page"] = None
        st.session_state["_nav_last"] = val
        return val
    if menu_page:
        return menu_page
    # the active tab was clicked again (segmented control un-selects it): keep showing it
    last = st.session_state.get("_nav_last", "Stocks")
    st.session_state["nav_request"] = last
    st.rerun()
    return last


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
            from core.db import last_error

            err_text = (last_error() or "").replace(get_settings().database_url or "@@", "<DATABASE_URL>")
            st.error("Cannot connect to the Supabase database. Check DATABASE_URL in .env.")
            st.code(err_text[:800] or "no details", language=None)
            st.caption("ConnectionTimeout = DATABASE_URL uses db.<ref>.supabase.co (needs IPv6): use the Session "
                       "pooler string from Connect → Session pooler instead. 'password authentication failed' = wrong "
                       "password. 'Tenant or user not found' = wrong user/region in the URL. Also check the project "
                       "is not paused.")
            return
    except DatabaseNotConfigured as ex:
        st.error(str(ex))
        return
    err = ensure_schema()  # empty database -> creates all tables from sql/schema.sql
    if err:
        st.error(f"Could not create the tables. Run sql/schema.sql once in the Supabase SQL Editor. ({err})")
        return

    if not st.session_state.get("user"):
        auth_view.render()
        return

    page = top_bar(st.session_state["user"])
    PAGES[page]()
    st.html('<div class="vr-foot">Data: Screener.in (main source), NSE, Yahoo Finance, Value Research, Investing.com, '
            'Macrotrends, NSE & BSE filings and 11 news websites. For personal and educational use; not investment advice.</div>')
    chat_widget.render()


main()
