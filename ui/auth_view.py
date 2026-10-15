"""Page 1: sign in / create account (two-column landing layout)."""
from __future__ import annotations

import streamlit as st

from core import repository as repo
from core.auth import AuthError, send_password_reset, sign_in, sign_up
from core.config import APP_NAME

FEATURES = [
    ("1", "Screener data, stored", "Results, P&L, balance sheet, cash flow, ratios, peers and shareholding for any NSE company."),
    ("2", "Missing figures filled", "Ratios Screener does not show, from Yahoo Finance and Value Research, with sources."),
    ("3", "Broker-style reports", "Scorecard, three-year projections, peers and news from NSE, BSE and 11 news websites."),
    ("4", "Your own workspace", "Portfolio, watchlist and a notebook that is saved to your account."),
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
    feats = "".join(f"""<div class="feat"><div class="ic">{n}</div>
        <div><div class="ft">{t}</div><div class="fd">{d}</div></div></div>""" for n, t, d in FEATURES)
    st.html(f"""<div class="vr-auth-brand">
        <div class="logo"><div class="mark">SI</div><div class="n">{APP_NAME}</div></div>
        <div class="tag">Fundamentals, news and AI-assisted analysis for NSE companies, in one place.</div>
        {feats}
    </div>""")


def render() -> None:
    st.html('<div style="height:28px"></div>')
    left, right = st.columns([1.05, 1], gap="large")
    with left:
        _brand_panel()
    with right:
        st.html('<div class="vr-auth-title">Welcome</div>'
                '<div class="vr-auth-sub">Sign in to continue, or create a free account.</div>')
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
