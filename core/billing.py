"""Plans, report access and Razorpay payments.

Access to a new analysis report, checked in this order:
  1. an active Monthly or Yearly plan   -> unlimited reports until the plan ends
  2. a free report not yet used         -> FREE_REPORTS per account (default 1)
  3. single-report credits              -> one credit per report (bought at PRICE_SINGLE_REPORT)

Payments use Razorpay Payment Links: the app creates a link for the chosen plan, the user pays on Razorpay's page
(UPI, cards, net banking, wallets), and the app checks the link with the Razorpay API (or the signed redirect back
to APP_BASE_URL) before giving the plan. A payment is applied only once.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from typing import Optional

import requests

from core import db
from core.config import get_settings

API = "https://api.razorpay.com/v1"


class BillingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price: int          # rupees
    days: int           # 0 = one report credit
    blurb: str


def plans() -> list[Plan]:
    s = get_settings()
    return [
        Plan("single", "Single report", s.price_single, 0, "One analysis report with PDF download"),
        Plan("monthly", "Monthly", s.price_monthly, 30, "Unlimited reports for 30 days"),
        Plan("yearly", "Yearly", s.price_yearly, 365, "Unlimited reports for 365 days"),
    ]


def plan_by_code(code: str) -> Plan:
    for p in plans():
        if p.code == code:
            return p
    raise BillingError(f"Unknown plan '{code}'.")


# ---------------------------------------------------------------- access
@dataclass
class Access:
    can_generate: bool
    source: Optional[str]          # monthly | yearly | free | credit | None
    plan: Optional[str]
    plan_expires_at: Optional[object]
    credits: int
    free_left: int
    message: str


def access_for(user_id: str) -> Access:
    s = get_settings()
    row = db.fetch_one("""select plan, plan_expires_at, plan_expires_at > now() as active, report_credits,
                                 free_reports_used from profiles where id = %s""", (user_id,)) or {}
    credits = int(row.get("report_credits") or 0)
    free_left = max(0, s.free_reports - int(row.get("free_reports_used") or 0))
    plan, expires = row.get("plan"), row.get("plan_expires_at")
    if plan and row.get("active"):
        if s.subscription_daily_limit:
            used = db.fetch_one("""select count(*) as n from report_usage where user_id = %s
                                   and source in ('monthly','yearly') and created_at > date_trunc('day', now())""",
                                (user_id,))["n"]
            if used >= s.subscription_daily_limit:
                return Access(False, None, plan, expires, credits, free_left,
                              f"Daily limit of {s.subscription_daily_limit} reports reached. Try again tomorrow.")
        return Access(True, plan, plan, expires, credits, free_left, f"{plan.title()} plan active")
    if free_left > 0:
        return Access(True, "free", None, None, credits, free_left, "Your first report is free")
    if credits > 0:
        return Access(True, "credit", None, None, credits, free_left,
                      f"{credits} report credit{'s' if credits != 1 else ''} left")
    return Access(False, None, plan, expires, 0, 0, "Choose a plan to generate a report")


def consume(user_id: str, report_id: Optional[int], source: str) -> None:
    """Record that a report was generated and use up the free report or one credit."""
    with db.transaction() as cur:
        if source == "free":
            cur.execute("update profiles set free_reports_used = free_reports_used + 1 where id = %s", (user_id,))
        elif source == "credit":
            cur.execute("update profiles set report_credits = report_credits - 1 "
                        "where id = %s and report_credits > 0 returning id", (user_id,))
            if cur.fetchone() is None:
                raise BillingError("No report credits left.")
        cur.execute("insert into report_usage (user_id, report_id, source) values (%s, %s, %s)",
                    (user_id, report_id, source))


def is_returning_without_access(user_id: str) -> bool:
    """True when the free report is used and there is no plan or credit: show the plans before the home page."""
    return not access_for(user_id).can_generate


# ---------------------------------------------------------------- Razorpay
def _auth():
    s = get_settings()
    if not s.razorpay_configured:
        raise BillingError("Payments are not set up yet: add RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET to .env.")
    return s, (s.razorpay_key_id, s.razorpay_key_secret)


def create_payment_link(user: dict, plan_code: str) -> dict:
    """Create a Razorpay Payment Link for this user and plan. Returns the payments row (with short_url)."""
    s, auth = _auth()
    plan = plan_by_code(plan_code)
    ref = f"sis_{uuid.uuid4().hex[:20]}"
    body = {
        "amount": plan.price * 100,
        "currency": "INR",
        "accept_partial": False,
        "reference_id": ref,
        "description": f"Stock Insight Studio · {plan.name}",
        "customer": {k: v for k, v in {"name": user.get("full_name") or "", "email": user.get("email") or "",
                                       "contact": user.get("phone") or ""}.items() if v},
        "notify": {"sms": False, "email": False},
        "reminder_enable": False,
        "notes": {"user_id": user["id"], "plan": plan.code},
        "callback_url": s.app_base_url + "/",
        "callback_method": "get",
    }
    r = requests.post(f"{API}/payment_links", json=body, auth=auth, timeout=20)
    data = r.json()
    if r.status_code >= 300:
        raise BillingError(f"Razorpay: {(data.get('error') or {}).get('description') or r.status_code}")
    return db.fetch_one("""insert into payments (user_id, plan_code, amount_paise, reference_id, link_id, short_url)
                           values (%s, %s, %s, %s, %s, %s) returning *""",
                        (user["id"], plan.code, plan.price * 100, ref, data["id"], data["short_url"]))


def verify_callback(params: dict) -> bool:
    """Check the signature Razorpay adds to the redirect after payment."""
    s = get_settings()
    need = ("razorpay_payment_id", "razorpay_payment_link_id", "razorpay_payment_link_reference_id",
            "razorpay_payment_link_status", "razorpay_signature")
    if not s.razorpay_key_secret or not all(params.get(k) for k in need):
        return False
    msg = "|".join([params["razorpay_payment_link_id"], params["razorpay_payment_link_reference_id"],
                    params["razorpay_payment_link_status"], params["razorpay_payment_id"]])
    expected = hmac.new(s.razorpay_key_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, params["razorpay_signature"])


def _apply(cur, payment: dict, razorpay_payment_id: Optional[str]) -> bool:
    """Mark the payment paid and give the plan or credit, exactly once. Returns True if applied now."""
    cur.execute("""update payments set status = 'paid', paid_at = coalesce(paid_at, now()),
                       razorpay_payment_id = coalesce(%s, razorpay_payment_id), applied = true
                   where id = %s and not applied returning id""", (razorpay_payment_id, payment["id"]))
    if cur.fetchone() is None:
        return False
    plan = plan_by_code(payment["plan_code"])
    if plan.days == 0:
        cur.execute("update profiles set report_credits = report_credits + 1 where id = %s", (payment["user_id"],))
    else:
        # a new plan starts when the current one ends, so time already paid for is never lost
        cur.execute("""update profiles set plan = %s,
                           plan_expires_at = greatest(coalesce(plan_expires_at, now()), now()) + make_interval(days => %s)
                       where id = %s""", (plan.code, plan.days, payment["user_id"]))
    return True


def refresh_payment(payment_id: int) -> dict:
    """Ask Razorpay for the link's status; apply the plan if it is paid. Returns the updated payments row."""
    _, auth = _auth()
    pay = db.fetch_one("select * from payments where id = %s", (payment_id,))
    if not pay:
        raise BillingError("Payment not found.")
    if pay["applied"]:
        return pay
    r = requests.get(f"{API}/payment_links/{pay['link_id']}", auth=auth, timeout=20)
    data = r.json()
    if r.status_code >= 300:
        raise BillingError(f"Razorpay: {(data.get('error') or {}).get('description') or r.status_code}")
    status = data.get("status")
    with db.transaction() as cur:
        if status == "paid":
            pid = next((p.get("payment_id") for p in data.get("payments") or [] if p.get("status") == "captured"), None)
            _apply(cur, pay, pid)
        elif status in ("expired", "cancelled"):
            cur.execute("update payments set status = %s where id = %s", (status, pay["id"]))
    return db.fetch_one("select * from payments where id = %s", (payment_id,))


def apply_from_callback(params: dict) -> Optional[dict]:
    """Handle the signed redirect from Razorpay. Returns the payments row when the payment is confirmed."""
    if not verify_callback(params) or params.get("razorpay_payment_link_status") != "paid":
        return None
    pay = db.fetch_one("select * from payments where link_id = %s and reference_id = %s",
                       (params["razorpay_payment_link_id"], params["razorpay_payment_link_reference_id"]))
    if not pay:
        return None
    with db.transaction() as cur:
        _apply(cur, pay, params["razorpay_payment_id"])
    return db.fetch_one("select * from payments where id = %s", (pay["id"],))


def login_from_callback(payment_id: int) -> Optional[dict]:
    """After a verified, paid Razorpay redirect, sign the payer in on that tab: once per payment, within 2 hours.
    Returns the profile row, or None."""
    row = db.fetch_one("""update payments set callback_login_used = true
                          where id = %s and status = 'paid' and applied and not callback_login_used
                            and paid_at > now() - interval '2 hours'
                          returning user_id""", (payment_id,))
    if not row:
        return None
    return db.fetch_one("select * from profiles where id = %s", (row["user_id"],))


def pending_payments(user_id: str) -> list[dict]:
    return db.fetch_all("""select * from payments where user_id = %s and status = 'created'
                           and created_at > now() - interval '1 day' order by created_at desc""", (user_id,))


def payment_history(user_id: str, limit: int = 20) -> list[dict]:
    return db.fetch_all("select * from payments where user_id = %s order by created_at desc limit %s",
                        (user_id, limit))
