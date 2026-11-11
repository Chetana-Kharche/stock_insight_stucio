"""Accounts: email + password, with an email code only when registering (and for "forgot password").

Register:  username + email + mobile + password  ->  code sent to the email  ->  verify  ->  account created.
Sign in:   email + password (no code).
Forgot:    email  ->  code sent to the email  ->  code + new password  ->  signed in.

The mobile number is required at registration and can belong to only one account, so one person cannot open
many accounts with different emails to get more free reports. (It is not verified by SMS.)

Passwords are stored only as a salted PBKDF2-SHA256 hash. After 5 wrong passwords the account is locked for
15 minutes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Optional

from core import db
from core.otp import OtpError, normalize_email, normalize_phone, send_code, verify_code

USERNAME_RE = re.compile(r"[A-Za-z0-9_.]{3,30}")
MIN_PASSWORD = 8
PBKDF2_ITERATIONS = 390_000
MAX_FAILED = 5
LOCK_MINUTES = 15


class AuthError(RuntimeError):
    pass


@dataclass
class AuthUser:
    id: str
    email: str
    full_name: Optional[str]
    phone: Optional[str] = None


@dataclass
class Started:
    email: str
    phone: Optional[str] = None
    dev_code: Optional[str] = None
    password_hash: Optional[str] = None


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(PBKDF2_ITERATIONS, base64.b64encode(salt).decode(),
                                           base64.b64encode(dk).decode())


def check_password(password: str, stored: Optional[str]) -> bool:
    try:
        algo, iters, salt, digest = (stored or "").split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def _validate_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"Password: at least {MIN_PASSWORD} characters.")
    if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        raise AuthError("Password: use at least one letter and one number.")


# ---------------------------------------------------------------- helpers
def _to_user(row: dict) -> AuthUser:
    return AuthUser(str(row["id"]), row["email"], row.get("username") or row.get("full_name"), row.get("phone"))


def _validate_new(username: str, email: str, phone: str) -> None:
    if not USERNAME_RE.fullmatch(username or ""):
        raise AuthError("Username: 3 to 30 letters, numbers, dots or underscores, no spaces.")
    if db.fetch_one("select 1 from profiles where lower(email) = %s and phone is not null", (email,)):
        raise AuthError("This email is already registered. Please sign in.")
    if db.fetch_one("select 1 from profiles where phone = %s", (phone,)):
        raise AuthError("This mobile number is already used by another account. Please sign in with that "
                        "account's email.")
    if db.fetch_one("select 1 from profiles where lower(username) = lower(%s)", (username,)):
        raise AuthError("This username is taken. Try another one.")


def _account(email: str) -> Optional[dict]:
    return db.fetch_one("""select *, locked_until > now() as locked from profiles where lower(email) = %s
                           order by (phone is not null) desc, created_at limit 1""", (email,))


# ---------------------------------------------------------------- register
def start_registration(username: str, email: str, mobile: str, password: str) -> Started:
    """Check the details and email a code. The password is kept only as a hash until the code is verified."""
    try:
        email, phone = normalize_email(email), normalize_phone(mobile)
        _validate_new(username.strip(), email, phone)
        _validate_password(password)
        res = send_code(email, "register")
        return Started(email, phone, res.dev_code, hash_password(password))
    except OtpError as e:
        raise AuthError(str(e)) from e


def resend_registration_code(email: str) -> Started:
    try:
        return Started(email, None, send_code(email, "register").dev_code)
    except OtpError as e:
        raise AuthError(str(e)) from e


def complete_registration(username: str, email: str, phone: str, password_hash: str, code: str) -> AuthUser:
    username, email = username.strip(), email.strip().lower()
    try:
        auth_id = verify_code(email, "register", code)
    except OtpError as e:
        raise AuthError(str(e)) from e
    _validate_new(username, email, phone)  # nobody took them while the email was on its way
    old = db.fetch_one("select id from profiles where lower(email) = %s and phone is null "
                       "order by created_at limit 1", (email,))
    if not old and auth_id:
        old = db.fetch_one("select id from profiles where id = %s", (auth_id,))
    if old:
        row = db.fetch_one("""update profiles set username = %s, full_name = coalesce(full_name, %s), phone = %s,
                                  password_hash = %s, failed_logins = 0, locked_until = null, last_login = now()
                              where id = %s returning *""",
                           (username, username, phone, password_hash, old["id"]))
    else:
        row = db.fetch_one("""insert into profiles (id, email, full_name, username, phone, password_hash, last_login)
                              values (%s, %s, %s, %s, %s, %s, now()) returning *""",
                           (auth_id or str(uuid.uuid4()), email, username, username, phone, password_hash))
    return _to_user(row)


# ---------------------------------------------------------------- sign in
def sign_in(email: str, password: str) -> AuthUser:
    try:
        email = normalize_email(email)
    except OtpError as e:
        raise AuthError(str(e)) from e
    row = _account(email)
    if not row:
        raise AuthError("Wrong email or password.")
    if row.get("locked"):
        raise AuthError(f"Too many wrong passwords. Try again in {LOCK_MINUTES} minutes, or use Forgot password.")
    if not row.get("password_hash"):
        raise AuthError("This account has no password yet. Use “Forgot password?” to set one.")
    if not check_password(password or "", row["password_hash"]):
        db.execute("""update profiles set
                          locked_until = case when failed_logins + 1 >= %s
                                              then now() + make_interval(mins => %s) end,
                          failed_logins = case when failed_logins + 1 >= %s then 0 else failed_logins + 1 end
                      where id = %s""", (MAX_FAILED, LOCK_MINUTES, MAX_FAILED, row["id"]))
        raise AuthError("Wrong email or password.")
    row = db.fetch_one("""update profiles set last_login = now(), failed_logins = 0, locked_until = null
                          where id = %s returning *""", (row["id"],))
    return _to_user(row)


# ---------------------------------------------------------------- forgot / change password
def start_reset(email: str) -> Started:
    try:
        email = normalize_email(email)
        if not _account(email):
            raise AuthError("No account uses this email. Create an account first.")
        return Started(email, None, send_code(email, "reset").dev_code)
    except OtpError as e:
        raise AuthError(str(e)) from e


def complete_reset(email: str, code: str, new_password: str) -> AuthUser:
    email = email.strip().lower()
    _validate_password(new_password)
    try:
        verify_code(email, "reset", code)
    except OtpError as e:
        raise AuthError(str(e)) from e
    row = _account(email)
    if not row:
        raise AuthError("Account not found.")
    row = db.fetch_one("""update profiles set password_hash = %s, failed_logins = 0, locked_until = null,
                              last_login = now() where id = %s returning *""",
                       (hash_password(new_password), row["id"]))
    return _to_user(row)


def change_password(user_id: str, current: str, new_password: str) -> None:
    row = db.fetch_one("select password_hash from profiles where id = %s", (user_id,))
    if not row:
        raise AuthError("Account not found.")
    if row.get("password_hash") and not check_password(current or "", row["password_hash"]):
        raise AuthError("The current password is wrong.")
    _validate_password(new_password)
    db.execute("update profiles set password_hash = %s where id = %s", (hash_password(new_password), user_id))


# ---------------------------------------------------------------- mobile number for old accounts
def needs_mobile(user_id: str) -> bool:
    """Accounts from the old version have no mobile number yet."""
    row = db.fetch_one("select phone from profiles where id = %s", (user_id,))
    return bool(row) and not row.get("phone")


def add_mobile(user_id: str, mobile: str) -> str:
    try:
        phone = normalize_phone(mobile)
    except OtpError as e:
        raise AuthError(str(e)) from e
    if db.fetch_one("select 1 from profiles where phone = %s and id <> %s", (phone, user_id)):
        raise AuthError("This mobile number is already used by another account.")
    db.execute("update profiles set phone = %s where id = %s", (phone, user_id))
    return phone


def sign_out() -> None:
    """Nothing to revoke on the server: the session lives in Streamlit's session state."""
