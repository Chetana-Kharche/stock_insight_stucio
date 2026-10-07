"""Page 1: sign in / create account (two-column landing layout)."""
from __future__ import annotations

import streamlit as st

from core import repository as repo
from core.auth import AuthError, send_password_reset, sign_in, sign_up
from core.config import APP_NAME

FEATURES = [
    ("1", "Live Screener capture", "Quarterly results, P&L, balance sheet, cash flow, ratios, peers and shareholding."),
    ("2", "Structured storage", "Every number saved in Supabase PostgreSQL — query it any time."),
    ("3", "Broker-style analysis", "Scorecard, stance and an AI-written company update with exhibits."),
    ("4", "Ask the AI", "A chatbot grounded in your stored data, news and reports."),
]


def _login(user) -> None:
    try:
        repo.upsert_profile(user.id, user.email, user.full_name)
    except Exception as e:  # noqa: BLE001
        st.error(f"Signed in, but the database is not reachable: {e}")
        return
    st.session_state["user"] = {"id": user.id, "email": user.email, "full_name": user.full_name}
    st.rerun()


def _brand_panel() -> None:
    words = APP_NAME.split(" ", 1)
    logo = f"{words[0]} <span>{words[1]}</span>" if len(words) == 2 else APP_NAME
    feats = "".join(f"""<div class="feat"><div class="ic">{n}</div>
        <div><div class="ft">{t}</div><div class="fd">{d}</div></div></div>""" for n, t, d in FEATURES)
    st.html(f"""<div class="sis-auth-brand">
        <div class="logo">{logo}</div>
        <div class="tag">Fundamentals capture, structured storage and AI-assisted equity analysis for NSE companies.</div>
        {feats}
    </div>""")


def render() -> None:
    st.write("")
    left, right = st.columns([1.05, 1], gap="large")
    with left:
        _brand_panel()
    with right:
        st.html('<div class="sis-auth-title">Welcome</div>'
                '<div class="sis-auth-sub">Sign in to continue, or create a free account.</div>')
        tab_in, tab_up, tab_reset = st.tabs(["Sign in", "Create account", "Forgot password"])

        with tab_in:
            with st.form("signin", border=True):
                email = st.text_input("Email address", placeholder="you@example.com")
                pw = st.text_input("Password", type="password", placeholder="Your password")
                st.write("")
                ok = st.form_submit_button("Sign in", type="primary", use_container_width=True)
            if ok:
                if not email or not pw:
                    st.warning("Enter email and password.")
                else:
                    try:
                        _login(sign_in(email.strip(), pw))
                    except AuthError as e:
                        st.error(str(e))

        with tab_up:
            with st.form("signup", border=True):
                name = st.text_input("Full name", placeholder="Your name")
                email2 = st.text_input("Email address", key="su_email", placeholder="you@example.com")
                c1, c2 = st.columns(2)
                with c1:
                    pw1 = st.text_input("Password", type="password", key="su_pw1", placeholder="Min. 8 characters")
                with c2:
                    pw2 = st.text_input("Confirm password", type="password", key="su_pw2", placeholder="Repeat password")
                st.write("")
                ok2 = st.form_submit_button("Create account", type="primary", use_container_width=True)
            if ok2:
                if not (name and email2 and pw1):
                    st.warning("All fields are required.")
                elif pw1 != pw2:
                    st.warning("Passwords do not match.")
                elif len(pw1) < 8:
                    st.warning("Use at least 8 characters.")
                else:
                    try:
                        user, msg = sign_up(email2.strip(), pw1, name.strip())
                        if user:
                            _login(user)
                        else:
                            st.success(msg)
                    except AuthError as e:
                        st.error(str(e))

        with tab_reset:
            with st.form("reset", border=True):
                st.caption("We'll email you a link to set a new password.")
                email3 = st.text_input("Email address", key="rs_email", placeholder="you@example.com")
                ok3 = st.form_submit_button("Send reset link", type="primary", use_container_width=True)
            if ok3 and email3:
                try:
                    send_password_reset(email3.strip())
                    st.success("If the email exists, a reset link has been sent.")
                except AuthError as e:
                    st.error(str(e))

        st.caption("For personal and educational use. Reports are AI-assisted and not investment advice.")
