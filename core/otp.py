"""One-time codes sent by email (account registration and password reset).

Providers (OTP_PROVIDER in .env):
  supabase – Supabase Auth emails the code and checks it. Set the email template and SMTP in the Supabase
             dashboard (see README: "Sign-in with an email code").
  smtp     – the app emails the code itself through any SMTP account (for example Gmail with an app password).
  dev      – nothing is sent; the code is shown on screen. For local testing only.

Codes are valid for 10 minutes, at most 5 tries, and at most one new code every 60 seconds (5 per hour) per
email address. For the smtp and dev providers only a salted hash of each code is stored.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

import requests

from core import db
from core.config import APP_NAME, get_settings

CODE_TTL_MINUTES = 10
MAX_ATTEMPTS = 5
RESEND_SECONDS = 60
MAX_PER_HOUR = 5
EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


class OtpError(RuntimeError):
    pass


@dataclass
class SendResult:
    email: str
    dev_code: Optional[str] = None   # only set when OTP_PROVIDER=dev


def normalize_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if not EMAIL_RE.fullmatch(email):
        raise OtpError("Enter a valid email address.")
    return email


def normalize_phone(raw: str) -> str:
    """Return the number in E.164 form (+919876543210). A 10-digit number gets the default country code."""
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("+"):
        num = "+" + re.sub(r"\D", "", digits)
    else:
        d = re.sub(r"\D", "", digits).lstrip("0")
        cc = get_settings().default_country_code
        if len(d) == 10:
            num = f"+{cc}{d}"
        elif len(d) == 10 + len(cc) and d.startswith(cc):
            num = f"+{d}"
        else:
            num = "+" + d
    if not re.fullmatch(r"\+\d{10,15}", num):
        raise OtpError("Enter a valid mobile number, for example 98765 43210.")
    if num.startswith("+91") and not re.fullmatch(r"\+91[6-9]\d{9}", num):
        raise OtpError("Enter a valid 10-digit Indian mobile number.")
    return num


def _hash(target: str, code: str) -> str:
    secret = (get_settings().otp_secret or "stock-insight-studio").encode()
    return hmac.new(secret, f"{target}:{code}".encode(), hashlib.sha256).hexdigest()


def _check_rate(target: str) -> None:
    row = db.fetch_one(
        """select count(*) filter (where created_at > now() - interval '1 hour') as hour_n,
                  max(created_at) > now() - make_interval(secs => %s) as too_soon
           from otp_codes where target = %s""", (RESEND_SECONDS, target))
    if row and row["too_soon"]:
        raise OtpError(f"Please wait {RESEND_SECONDS} seconds before asking for a new code.")
    if row and row["hour_n"] >= MAX_PER_HOUR:
        raise OtpError("Too many codes requested for this email. Try again in an hour.")


# ---------------------------------------------------------------- providers
def _send_smtp(email: str, code: str, purpose: str) -> None:
    s = get_settings()
    if not (s.smtp_host and s.smtp_user and s.smtp_password):
        raise OtpError("SMTP_HOST, SMTP_USER and SMTP_PASSWORD are not set in .env.")
    msg = EmailMessage()
    msg["Subject"] = f"{code} is your {APP_NAME} code"
    msg["From"] = s.smtp_from or s.smtp_user
    msg["To"] = email
    action = {"register": "create your account", "reset": "reset your password"}.get(purpose, "sign in")
    msg.set_content(f"Your code to {action} on {APP_NAME} is: {code}\n\n"
                    f"It is valid for {CODE_TTL_MINUTES} minutes. If you did not ask for it, ignore this email.")
    msg.add_alternative(
        f"""<div style="font-family:Arial,sans-serif;color:#163A5F">
        <p>Your code to {action} on <b>{APP_NAME}</b> is:</p>
        <p style="font-size:28px;font-weight:700;letter-spacing:6px">{code}</p>
        <p style="color:#595959">It is valid for {CODE_TTL_MINUTES} minutes. If you did not ask for it,
        ignore this email.</p></div>""", subtype="html")
    try:
        if s.smtp_port == 465:
            with smtplib.SMTP_SSL(s.smtp_host, 465, context=ssl.create_default_context(), timeout=20) as srv:
                srv.login(s.smtp_user, s.smtp_password)
                srv.send_message(msg)
        else:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as srv:
                srv.starttls(context=ssl.create_default_context())
                srv.login(s.smtp_user, s.smtp_password)
                srv.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise OtpError("Could not send the email: SMTP login failed (for Gmail use an App Password, "
                       "not your normal password).") from e
    except (smtplib.SMTPException, OSError) as e:
        raise OtpError(f"Could not send the email ({e}).") from e


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_anon_key or "YOUR-" in s.supabase_url:
        raise OtpError("SUPABASE_URL and SUPABASE_ANON_KEY are not set in .env.")
    return s.supabase_url, {"apikey": s.supabase_anon_key, "Authorization": f"Bearer {s.supabase_anon_key}",
                            "Content-Type": "application/json"}


def _sb_error(r) -> str:
    try:
        d = r.json()
    except ValueError:
        return str(r.status_code)
    return d.get("msg") or d.get("error_description") or d.get("message") or d.get("error") or str(r.status_code)


def _send_supabase(email: str) -> None:
    url, headers = _supabase()
    r = requests.post(f"{url}/auth/v1/otp", json={"email": email, "create_user": True}, headers=headers, timeout=20)
    if r.status_code >= 300:
        msg = _sb_error(r)
        if "not authorized" in msg.lower():
            msg += (" (Supabase's built-in email only sends to your team's addresses: add your own SMTP in "
                    "Supabase → Authentication → Emails → SMTP Settings)")
        raise OtpError(f"Could not send the email (Supabase: {msg}).")


def _check_supabase(email: str, code: str) -> Optional[str]:
    """Return the Supabase user id when the code is right, else None."""
    url, headers = _supabase()
    for kind in ("email", "signup"):        # new users may get the "Confirm signup" email
        r = requests.post(f"{url}/auth/v1/verify", json={"type": kind, "email": email, "token": code},
                          headers=headers, timeout=20)
        if r.status_code < 300:
            data = r.json()
            return str((data.get("user") or {}).get("id") or data.get("id") or "") or "ok"
    return None


# ---------------------------------------------------------------- public API
def send_code(email: str, purpose: str) -> SendResult:
    """Send a new code to an already normalised email address."""
    provider = get_settings().otp_provider
    _check_rate(email)
    code = f"{secrets.randbelow(1_000_000):06d}"
    if provider == "supabase":
        _send_supabase(email)
        code_hash = None
    elif provider == "smtp":
        _send_smtp(email, code, purpose)
        code_hash = _hash(email, code)
    elif provider == "dev":
        code_hash = _hash(email, code)
    else:
        raise OtpError(f"Unknown OTP_PROVIDER '{provider}'. Use supabase, smtp or dev.")
    db.execute("update otp_codes set used = true where target = %s and purpose = %s and not used", (email, purpose))
    db.execute("""insert into otp_codes (target, purpose, code_hash, expires_at)
                  values (%s, %s, %s, now() + make_interval(mins => %s))""",
               (email, purpose, code_hash, CODE_TTL_MINUTES))
    return SendResult(email, code if provider == "dev" else None)


def verify_code(email: str, purpose: str, code: str) -> Optional[str]:
    """Raise OtpError unless the code is right. A code can be used only once.
    Returns the Supabase user id when Supabase checked the code, otherwise None."""
    code = re.sub(r"\D", "", code or "")
    if not 6 <= len(code) <= 10:
        raise OtpError("Enter the code from the email.")
    row = db.fetch_one("""select id, code_hash, attempts, expires_at < now() as expired from otp_codes
                          where target = %s and purpose = %s and not used order by created_at desc limit 1""",
                       (email, purpose))
    if not row:
        raise OtpError("No active code for this email. Ask for a new code.")
    if row["expired"]:
        raise OtpError("This code has expired. Ask for a new code.")
    if row["attempts"] >= MAX_ATTEMPTS:
        raise OtpError("Too many wrong tries. Ask for a new code.")
    db.execute("update otp_codes set attempts = attempts + 1 where id = %s", (row["id"],))
    supabase_id = None
    if row["code_hash"] is None:
        supabase_id = _check_supabase(email, code)
        ok = supabase_id is not None
    else:
        ok = hmac.compare_digest(row["code_hash"], _hash(email, code))
    if not ok:
        left = MAX_ATTEMPTS - row["attempts"] - 1
        raise OtpError(f"Wrong code. {left} tr{'y' if left == 1 else 'ies'} left." if left > 0
                       else "Wrong code. Ask for a new code.")
    db.execute("update otp_codes set used = true where id = %s", (row["id"],))
    return supabase_id if supabase_id not in (None, "ok") else None
