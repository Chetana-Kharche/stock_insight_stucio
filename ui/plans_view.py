"""Plans and payments: pay per report, monthly or yearly, through Razorpay."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import billing
from core.config import get_settings
from ui import components as C
from ui.html import e

CARD = """<div style="border:1.5px solid {border};border-radius:14px;padding:22px 20px;background:#fff;height:330px;
  box-sizing:border-box;display:flex;flex-direction:column;box-shadow:0 6px 18px rgba(22,58,95,.06);position:relative">
  <div style="font-size:.74rem;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:{accent};
    background:{soft};align-self:flex-start;padding:4px 10px;border-radius:20px">{tag}</div>
  <div style="font-size:1.15rem;font-weight:700;color:#163A5F;margin-top:12px">{name}</div>
  <div style="margin:4px 0 2px"><span style="font-size:2.2rem;font-weight:800;color:#163A5F">₹{price}</span>
    <span style="font-size:.88rem;color:#595959"> {per}</span></div>
  <div style="font-size:.82rem;color:{accent};font-weight:600;min-height:20px">{note}</div>
  <ul style="list-style:none;padding:0;margin:12px 0 0;font-size:.9rem;color:#333;line-height:1.9">{feats}</ul>
</div>"""
FEATURES = {
    "single": ["1 AI analysis report", "Instant PDF download", "Latest news included", "No subscription"],
    "monthly": ["Unlimited reports for 30 days", "Instant PDF download", "Latest news in every report",
                "Screener data export (JSON, Excel, PDF)"],
    "yearly": ["Unlimited reports for 365 days", "Instant PDF download", "Latest news in every report",
               "Lowest price per month"],
}
PER = {"single": "one time", "monthly": "per month", "yearly": "per year"}
TAGS = {"single": ("Pay per report", "#595959", "#d9dee7", "#F1F3F6"),
        "monthly": ("Most popular", "#1F6F4A", "#1F6F4A", "#E7F5EC"),
        "yearly": ("Best value", "#0B5CAD", "#8bb7e8", "#EAF0FA")}


def _note(plan) -> str:
    if plan.code == "yearly" and plan.price and plan.days:
        return f"≈ ₹{plan.price / 12:,.0f} per month"
    if plan.code == "monthly":
        return "Cancel anytime: it simply ends after 30 days"
    return "Pay only when you need a report"


def _fmt(ts) -> str:
    try:
        return pd.to_datetime(ts).strftime("%d %b %Y")
    except (TypeError, ValueError):
        return "–"


def access_banner(uid: str) -> billing.Access:
    acc = billing.access_for(uid)
    if acc.source in ("monthly", "yearly"):
        st.success(f"{acc.plan.title()} plan active until {_fmt(acc.plan_expires_at)} · unlimited reports"
                   + (f" · plus {acc.credits} single-report credit(s)" if acc.credits else ""))
    elif acc.source == "free":
        st.info("Your first analysis report is free. After that, pay per report or choose a plan.")
    elif acc.source == "credit":
        st.info(acc.message)
    else:
        st.warning(acc.message)
    return acc


def _check(pay_id: int) -> None:
    try:
        pay = billing.refresh_payment(pay_id)
    except billing.BillingError as ex:
        st.error(str(ex))
        return
    if pay["applied"]:
        st.session_state.pop("pay_link", None)
        st.session_state["payment_ok"] = billing.plan_by_code(pay["plan_code"]).name
        st.rerun()
    elif pay["status"] in ("expired", "cancelled"):
        st.warning("This payment link has expired. Choose the plan again to get a new link.")
        st.session_state.pop("pay_link", None)
    else:
        st.info("Payment not received yet. Finish paying on the Razorpay page, then check again.")


def _plans_body(user: dict, key: str = "pg") -> None:
    """Plan cards, the Razorpay payment link and unconfirmed links. Used on the Plans page and in the popup."""
    s = get_settings()
    cols = st.columns(3, gap="medium")
    for col, plan in zip(cols, billing.plans()):
        tag, accent, border, soft = TAGS[plan.code]
        feats = "".join(f'<li><span style="color:{accent};font-weight:800">✓</span>&nbsp; {e(f)}</li>'
                        for f in FEATURES[plan.code])
        with col:
            st.html(CARD.format(tag=tag, accent=accent, border=border, soft=soft, name=e(plan.name),
                                price=f"{plan.price:,}", per=PER[plan.code], note=e(_note(plan)), feats=feats))
            if st.button(f"Buy {plan.name.lower()} · ₹{plan.price}", key=f"{key}_buy_{plan.code}",
                         type="primary" if plan.code == "monthly" else "secondary", use_container_width=True,
                         disabled=not s.razorpay_configured):
                try:
                    st.session_state["pay_link"] = billing.create_payment_link(user, plan.code)
                except billing.BillingError as ex:
                    st.error(str(ex))
    if not s.razorpay_configured:
        st.caption("Payments are not switched on yet: add RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET to .env.")

    link = st.session_state.get("pay_link")
    if link:
        with st.container(border=True):
            plan = billing.plan_by_code(link["plan_code"])
            st.markdown(f"**{plan.name} · ₹{plan.price}**: pay securely on Razorpay (UPI, cards, net banking, "
                        "wallets). The payment page opens in a new tab.")
            a, b = st.columns(2)
            a.link_button(f"Pay ₹{plan.price} on Razorpay", link["short_url"], type="primary",
                          use_container_width=True)
            if b.button("I have paid · check payment", key=f"{key}_check_pay", use_container_width=True):
                _check(link["id"])

    pending = [p for p in billing.pending_payments(user["id"]) if not link or p["id"] != link["id"]]
    if pending:
        with st.expander(f"Earlier payment links not yet confirmed ({len(pending)})"):
            for p in pending:
                a, b = st.columns([3, 1], vertical_alignment="center")
                a.caption(f"{billing.plan_by_code(p['plan_code']).name} · ₹{p['amount_paise'] // 100} · "
                          f"created {str(p['created_at'])[:16]}")
                if b.button("Check", key=f"{key}_chk_{p['id']}", use_container_width=True):
                    _check(p["id"])


@st.dialog("Choose a plan to continue", width="large")
def plans_dialog(message: str = "") -> None:
    """Popup shown on Home when a user without a free report or plan asks for a report."""
    st.warning(message or "Your free report is used. Choose a plan to generate your next report.")
    _plans_body(st.session_state["user"], key="dlg")
    st.caption("After paying, press “I have paid · check payment”. Reports are AI-assisted research for "
               "education and are not investment advice.")


def render(gate: bool = False) -> None:
    user = st.session_state["user"]
    C.page_header("Plans", "Pay per report, or get unlimited reports with a monthly or yearly plan.")
    if st.session_state.get("payment_ok"):
        st.success(f"Payment received. {st.session_state.pop('payment_ok')} is now active on your account.")
    access_banner(user["id"])
    msg = st.session_state.pop("plans_msg", None)
    if msg:
        st.warning(msg)
    _plans_body(user, key="pg")
    hist = billing.payment_history(user["id"])
    if hist:
        with st.expander("Payment history"):
            st.dataframe(pd.DataFrame([{
                "Date": str(p["created_at"])[:16], "Plan": billing.plan_by_code(p["plan_code"]).name,
                "Amount (₹)": p["amount_paise"] // 100, "Status": p["status"],
                "Razorpay payment": p.get("razorpay_payment_id") or "–"} for p in hist]),
                hide_index=True, use_container_width=True)
    st.caption("Prices include all charges shown on the Razorpay page. Reports are AI-assisted research for "
               "education and are not investment advice.")


def render_callback(params: dict) -> None:
    """Shown in the tab Razorpay redirects to after payment."""
    C.page_header("Payment", "Stock Insight Studio")
    try:
        pay = billing.apply_from_callback(params)
    except billing.BillingError as ex:
        pay = None
        st.error(str(ex))
    if pay and pay["applied"]:
        plan_name = billing.plan_by_code(pay["plan_code"]).name
        prof = billing.login_from_callback(pay["id"])
        if prof:      # signed in automatically on this tab -> straight to Home
            st.session_state["user"] = {"id": str(prof["id"]), "email": prof["email"],
                                        "full_name": prof.get("username") or prof.get("full_name"),
                                        "phone": prof.get("phone")}
            st.session_state["payment_ok"] = plan_name
            st.session_state["nav_request"] = "Home"
            st.query_params.clear()
            st.rerun()
        st.success(f"Payment received: {plan_name} is active on your account.")
        st.caption("You can close this tab and continue in the app, or sign in here.")
    elif params.get("razorpay_payment_link_status") and params.get("razorpay_payment_link_status") != "paid":
        st.warning("The payment was not completed. You can try again from the Plans page.")
    else:
        st.error("We could not confirm this payment. If money was taken, open Plans in the app and press "
                 "“I have paid · check payment”, or contact support with your Razorpay payment id.")
    if st.button("Continue to the app", type="primary"):
        st.query_params.clear()
        st.rerun()
