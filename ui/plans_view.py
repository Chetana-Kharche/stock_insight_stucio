"""Plans and payments: pay per report, monthly or yearly, through Razorpay."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import billing
from core.config import get_settings
from ui import components as C
from ui.html import e

CARD = """<div style="border:1px solid {border};border-radius:14px;padding:20px 18px;background:#fff;min-height:210px;
  box-shadow:0 6px 18px rgba(22,58,95,.06)">
  <div style="font-size:.78rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:{accent}">{tag}</div>
  <div style="font-size:1.2rem;font-weight:700;color:#163A5F;margin-top:6px">{name}</div>
  <div style="font-size:2.1rem;font-weight:800;color:#163A5F;margin:6px 0 2px">₹{price}</div>
  <div style="font-size:.85rem;color:#595959">{per}</div>
  <div style="font-size:.92rem;color:#333;margin-top:12px">{blurb}</div>
</div>"""

PER = {"single": "one time", "monthly": "per month", "yearly": "per year"}
TAGS = {"single": ("Pay per report", "#595959", "#d9dee7"), "monthly": ("Unlimited", "#1F6F4A", "#9fd3b8"),
        "yearly": ("Best value", "#0B5CAD", "#8bb7e8")}


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
        st.session_state["show_plans_gate"] = False
        st.session_state["payment_ok"] = billing.plan_by_code(pay["plan_code"]).name
        st.rerun()
    elif pay["status"] in ("expired", "cancelled"):
        st.warning("This payment link has expired. Choose the plan again to get a new link.")
        st.session_state.pop("pay_link", None)
    else:
        st.info("Payment not received yet. Finish paying on the Razorpay page, then check again.")


def render(gate: bool = False) -> None:
    user = st.session_state["user"]
    s = get_settings()
    if gate:
        C.page_header("Welcome back", "Your free report is used. Choose how you want to continue.")
    else:
        C.page_header("Plans", "Pay per report, or get unlimited reports with a monthly or yearly plan.")

    if st.session_state.get("payment_ok"):
        st.success(f"Payment received. {st.session_state.pop('payment_ok')} is now active on your account.")
    access_banner(user["id"])

    cols = st.columns(3, gap="medium")
    for col, plan in zip(cols, billing.plans()):
        tag, accent, border = TAGS[plan.code]
        with col:
            st.html(CARD.format(tag=tag, accent=accent, border=border, name=e(plan.name), price=plan.price,
                                per=PER[plan.code], blurb=e(plan.blurb)))
            if st.button(f"Buy {plan.name.lower()} · ₹{plan.price}", key=f"buy_{plan.code}",
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
            if b.button("I have paid · check payment", key="check_pay", use_container_width=True):
                _check(link["id"])

    pending = [p for p in billing.pending_payments(user["id"]) if not link or p["id"] != link["id"]]
    if pending:
        with st.expander(f"Earlier payment links not yet confirmed ({len(pending)})"):
            for p in pending:
                a, b = st.columns([3, 1], vertical_alignment="center")
                a.caption(f"{billing.plan_by_code(p['plan_code']).name} · ₹{p['amount_paise'] // 100} · "
                          f"created {str(p['created_at'])[:16]}")
                if b.button("Check", key=f"chk_{p['id']}", use_container_width=True):
                    _check(p["id"])

    if gate:
        st.write("")
        if st.button("Not now, go to the app", key="gate_skip"):
            st.session_state["show_plans_gate"] = False
            st.rerun()
    else:
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
        st.success(f"Payment received: {billing.plan_by_code(pay['plan_code']).name} is active on your account.")
        st.caption("You can close this tab and continue in the app, or sign in here.")
    elif params.get("razorpay_payment_link_status") and params.get("razorpay_payment_link_status") != "paid":
        st.warning("The payment was not completed. You can try again from the Plans page.")
    else:
        st.error("We could not confirm this payment. If money was taken, open Plans in the app and press "
                 "“I have paid · check payment”, or contact support with your Razorpay payment id.")
    if st.button("Continue to the app", type="primary"):
        st.query_params.clear()
        st.rerun()
