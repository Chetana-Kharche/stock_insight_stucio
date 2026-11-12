"""Stock Insight Studio — Streamlit entry point.

Run:  streamlit run app.py
"""
from __future__ import annotations

import logging

import streamlit as st

from core.config import APP_NAME, get_settings
from core.db import DatabaseNotConfigured, ensure_schema, ping
from core import billing
from ui import (auth_view, chat_widget, company_view, home_view, market_news_view, notebook_view, plans_view,
                portfolio_view, profile_view)
from ui import components as C
from ui.html import e
from ui.styles import CSS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title=APP_NAME, page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
st.markdown(CSS, unsafe_allow_html=True)

PAGES = {
    "Portfolio": portfolio_view.render,
    "Home": home_view.render,
    "Screener Data": lambda: company_view.render("data"),
    "AI Analysis Report": lambda: company_view.render("report"),
    "Market News": market_news_view.render,
    "Notebook": notebook_view.render,
    "Profile": profile_view.render,
    "Plans": plans_view.render,
}


def _config_problems() -> list[str]:
    s = get_settings()
    problems = []
    if not s.database_url or "YOUR-" in s.database_url:
        problems.append("DATABASE_URL missing in .env")
    return problems


ALIASES = {"Stocks": "Screener Data", "Market Movers": "Home"}       # old page names
MENU_PAGES = ["Home", "Plans", "Portfolio", "Notebook", "Profile"]     # in the user drop-down menu


def _route() -> str:
    """Apply a page change requested by a button anywhere, and return the page to show."""
    target = st.session_state.pop("nav_request", None)
    target = ALIASES.get(target, target)
    if target in PAGES:
        st.session_state["page"] = target
    return st.session_state.setdefault("page", "Home")


def top_bar(user: dict) -> str:
    """Brand on the left, Home + user menu on the right, the scrolling stock ticker below. Returns the page."""
    page = _route()
    with st.container(key="topbar"):
        a, b, c = st.columns([6, 1.1, 1.6], vertical_alignment="center", gap="small")
        with a:
            st.html('<div class="vr-brand"><div class="mark">SI</div><div class="txt">'
                    '<div class="a">Stock Insight</div><div class="b">STUDIO</div></div></div>')
        with b:
            if page != "Home" and st.button("🏠 Home", key="top_home", use_container_width=True):
                st.session_state["nav_request"] = "Home"
                st.rerun()
        with c:
            name = user.get("full_name") or (user.get("email") or "user").split("@")[0]
            with st.popover(f"👤 {name[:14].upper()}", use_container_width=True):
                st.html(f'<div style="font-weight:700;color:#163A5F">{e(name)}</div>'
                        f'<div style="font-size:.8rem;color:#595959;margin-bottom:6px">{e(user.get("phone") or "")}'
                        f' · {e(user.get("email") or "")}</div>')
                for target in MENU_PAGES:
                    if st.button(target, key=f"menu_{target}", use_container_width=True):
                        st.session_state["nav_request"] = target
                        st.rerun()
                if st.button("Logout", key="menu_logout", use_container_width=True):
                    profile_view.do_sign_out()
    home_view.ticker_tape()
    return page


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

    # Razorpay sends the user back here after paying: confirm the payment from the signed redirect
    if "razorpay_payment_link_id" in st.query_params:
        plans_view.render_callback({k: st.query_params.get(k) for k in st.query_params.keys()})
        return

    if not st.session_state.get("user"):
        auth_view.render()
        return

    uid = st.session_state["user"]["id"]
    if auth_view.mobile_gate(st.session_state["user"]):     # old accounts add a mobile number once
        return
    st.session_state.pop("just_signed_in", None)   # signed-in users always start on Home
    page = top_bar(st.session_state["user"])
    PAGES[page]()
    st.html('<div class="vr-foot">Market data may be delayed. AI-assisted research for education; '
            'not investment advice.</div>')
    chat_widget.render()


main()
