"""Page 1: sign in with email + password, or create an account (email verified with a code). Two-column layout."""
from __future__ import annotations

import streamlit as st

from core.auth import (AuthError, add_mobile, complete_registration, complete_reset, needs_mobile,
                       resend_registration_code, sign_in, start_registration, start_reset)
from core.config import APP_NAME, get_settings

FEATURES = [
    ("1", "Complete company data", "Results, P&L, balance sheet, cash flow, ratios, peers and shareholding for any listed Indian company."),
    ("2", "Nothing missing", "Key ratios and figures gathered and checked for you, in one place."),
    ("3", "Broker-style reports", "Scorecard, three-year projections, peers and the latest news, in a ready PDF."),
    ("4", "Your first report is free", "Then pay per report or choose a monthly or yearly plan."),
]


def _login(user) -> None:
    st.session_state["user"] = {"id": user.id, "email": user.email, "full_name": user.full_name, "phone": user.phone}
    for k in ("otp_reset", "otp_reg", "show_reset"):
        st.session_state.pop(k, None)
    st.session_state["just_signed_in"] = True
    st.rerun()


def _sent_note(state: dict) -> None:
    if state.get("dev_code"):
        st.info(f"Test mode (OTP_PROVIDER=dev): no email was sent to {state['email']}. "
                f"Your code is **{state['dev_code']}**.")
        return
    st.success(f"Code sent to {state['email']}. It is valid for 10 minutes. Check your spam folder too.")


def _brand_panel() -> None:
    feats = "".join(f"""<div class="feat"><div class="ic">{n}</div>
        <div><div class="ft">{t}</div><div class="fd">{d}</div></div></div>""" for n, t, d in FEATURES)
    st.html(f"""<div class="vr-auth-brand">
        <div class="logo"><div class="mark">SI</div><div class="n">{APP_NAME}</div></div>
        <div class="quote">Institutional-style stock research, now at your fingertips.</div>
        <div class="tag"><i>Fundamentals, projections, peers and news, in one broker-style PDF.
        Your first report is free.</i></div>
        {feats}
    </div>""")


def _sign_in_tab() -> None:
    if st.session_state.get("show_reset"):
        _reset_flow()
        return
    with st.form("signin", border=True):
        email = st.text_input("Email address", placeholder="you@example.com")
        password = st.text_input("Password", type="password")
        ok = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if ok:
        try:
            _login(sign_in(email, password))
        except AuthError as e:
            st.error(str(e))
    if st.button("Forgot password?", key="forgot_pw"):
        st.session_state["show_reset"] = True
        st.rerun()


def _reset_flow() -> None:
    state = st.session_state.get("otp_reset")
    st.markdown("**Reset your password**")
    if not state:
        with st.form("reset_start", border=True):
            email = st.text_input("Email address", key="rs_email", placeholder="you@example.com")
            ok = st.form_submit_button("Email me a code", type="primary", use_container_width=True)
        if ok:
            try:
                res = start_reset(email)
                st.session_state["otp_reset"] = {"email": res.email, "dev_code": res.dev_code}
                st.rerun()
            except AuthError as e:
                st.error(str(e))
    else:
        _sent_note(state)
        with st.form("reset_done", border=True):
            code = st.text_input("Code from the email", max_chars=10, key="rs_code", placeholder="••••••")
            p1 = st.text_input("New password", type="password", key="rs_p1",
                               help="At least 8 characters, with a letter and a number.")
            p2 = st.text_input("Repeat new password", type="password", key="rs_p2")
            ok = st.form_submit_button("Set password and sign in", type="primary", use_container_width=True)
        if ok:
            if p1 != p2:
                st.warning("The two passwords do not match.")
            else:
                try:
                    _login(complete_reset(state["email"], code, p1))
                except AuthError as e:
                    st.error(str(e))
    if st.button("Back to sign in", key="rs_back"):
        st.session_state.pop("otp_reset", None)
        st.session_state["show_reset"] = False
        st.rerun()


def _register_tab() -> None:
    state = st.session_state.get("otp_reg")
    if not state:
        with st.form("signup", border=True):
            username = st.text_input("Username", placeholder="e.g. vinod_k", max_chars=30)
            email = st.text_input("Email address", key="su_email", placeholder="you@example.com")
            mobile = st.text_input("Mobile number", key="su_mobile", placeholder="98765 43210", max_chars=16)
            p1 = st.text_input("Password", type="password", key="su_p1",
                               help="At least 8 characters, with a letter and a number.")
            p2 = st.text_input("Repeat password", type="password", key="su_p2")
            st.caption("We will email you a code to verify the address. One account per mobile number.")
            ok = st.form_submit_button("Send code", type="primary", use_container_width=True)
        if ok:
            if not (username and email and mobile and p1):
                st.warning("All fields are required.")
            elif p1 != p2:
                st.warning("The two passwords do not match.")
            else:
                try:
                    res = start_registration(username, email, mobile, p1)
                    st.session_state["otp_reg"] = {"username": username.strip(), "email": res.email,
                                                   "phone": res.phone, "dev_code": res.dev_code,
                                                   "password_hash": res.password_hash}
                    st.rerun()
                except AuthError as e:
                    st.error(str(e))
        return
    _sent_note(state)
    st.caption(f"Creating account **{state['username']}** · mobile {state['phone']}")
    with st.form("signup_otp", border=True):
        code = st.text_input("Code from the email", max_chars=10, key="su_code", placeholder="••••••")
        ok = st.form_submit_button("Verify and create account", type="primary", use_container_width=True)
    if ok:
        try:
            _login(complete_registration(state["username"], state["email"], state["phone"],
                                         state["password_hash"], code))
        except AuthError as e:
            st.error(str(e))
    a, b = st.columns(2)
    if a.button("Edit details", key="su_change", use_container_width=True):
        st.session_state.pop("otp_reg", None)
        st.rerun()
    if b.button("Send a new code", key="su_resend", use_container_width=True):
        try:
            res = resend_registration_code(state["email"])
            st.session_state["otp_reg"] = {**state, "dev_code": res.dev_code}
            st.rerun()
        except AuthError as e:
            st.error(str(e))


def mobile_gate(user: dict) -> bool:
    """Accounts from the old email/password version must add a mobile number once. Returns True when shown."""
    if not needs_mobile(user["id"]):
        return False
    st.html('<div style="height:28px"></div>')
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        st.html('<div class="vr-auth-title">One more step</div>'
                '<div class="vr-auth-sub">Add your mobile number to continue. Each number can be used by only '
                'one account.</div>')
        with st.form("add_mobile", border=True):
            mobile = st.text_input("Mobile number", placeholder="98765 43210", max_chars=16)
            ok = st.form_submit_button("Save and continue", type="primary", use_container_width=True)
        if ok:
            try:
                st.session_state["user"]["phone"] = add_mobile(user["id"], mobile)
                st.rerun()
            except AuthError as e:
                st.error(str(e))
    return True


def render() -> None:
    st.html('<div style="height:28px"></div>')
    left, right = st.columns([1.05, 1], gap="large")
    with left:
        _brand_panel()
    with right:
        st.html('<div class="vr-auth-title">Welcome</div>'
                '<div class="vr-auth-sub">Sign in with your email and password, or create an account. '
                'Your first report is free.</div>')
        if get_settings().otp_provider == "dev":
            st.warning("Test mode: codes are shown on screen instead of being emailed. "
                       "Set OTP_PROVIDER to supabase or smtp in .env before going live.")
        tab_in, tab_up = st.tabs(["Sign in", "Create account"])
        with tab_in:
            _sign_in_tab()
        with tab_up:
            _register_tab()
        st.caption("Reports are AI-assisted research for education and are not investment advice.")
