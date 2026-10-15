"""Sign up / sign in with Supabase Auth."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.config import get_settings


class AuthError(RuntimeError):
    pass


@dataclass
class AuthUser:
    id: str
    email: str
    full_name: Optional[str]
    access_token: Optional[str] = None


def _supabase():
    """A fresh client per call so auth sessions never leak between Streamlit users."""
    s = get_settings()
    if not s.supabase_url or not s.supabase_anon_key or "YOUR-" in s.supabase_url:
        raise AuthError("SUPABASE_URL / SUPABASE_ANON_KEY are not configured in .env")
    if "supabase.com/dashboard" in s.supabase_url or not s.supabase_url.startswith("https://"):
        raise AuthError("SUPABASE_URL looks wrong. It must be the Project URL like https://abcdxyz.supabase.co "
                        "(Project Settings -> API), not the dashboard link.")
    from supabase import create_client

    return create_client(s.supabase_url, s.supabase_anon_key)


def _friendly(e: Exception) -> str:
    msg = getattr(e, "message", None) or str(e)
    low = msg.lower()
    if "invalid path" in low:
        return ("Supabase rejected the URL. Set SUPABASE_URL in .env to exactly https://<project-ref>.supabase.co "
                "(no /rest/v1 or other path at the end) and restart the app.")
    if "invalid login" in low:
        return "Incorrect email or password."
    if "email not confirmed" in low:
        return "Please confirm your email first (check your inbox), or disable email confirmation in Supabase."
    if "already registered" in low or "already been registered" in low:
        return "This email is already registered. Please sign in."
    if "password" in low and ("6" in low or "short" in low or "weak" in low):
        return "Password is too weak — use at least 6 characters (8+ recommended)."
    return msg


def sign_up(email: str, password: str, full_name: str) -> tuple[Optional[AuthUser], str]:
    """Returns (user or None, message). user is None when email confirmation is required."""
    try:
        res = _supabase().auth.sign_up({"email": email, "password": password,
                                        "options": {"data": {"full_name": full_name}}})
    except Exception as e:  # noqa: BLE001
        raise AuthError(_friendly(e)) from e
    if res.user is None:
        raise AuthError("Sign-up failed.")
    if res.session is None:
        return None, "Account created. Check your email to confirm it, then sign in."
    return AuthUser(res.user.id, res.user.email, full_name, res.session.access_token), "Account created."


def sign_in(email: str, password: str) -> AuthUser:
    try:
        res = _supabase().auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:  # noqa: BLE001
        raise AuthError(_friendly(e)) from e
    if not res.user:
        raise AuthError("Sign-in failed.")
    meta = res.user.user_metadata or {}
    return AuthUser(res.user.id, res.user.email, meta.get("full_name"),
                    res.session.access_token if res.session else None)


def send_password_reset(email: str) -> None:
    try:
        _supabase().auth.reset_password_for_email(email)
    except Exception as e:  # noqa: BLE001
        raise AuthError(_friendly(e)) from e


def change_password(email: str, current_password: str, new_password: str) -> None:
    """Re-check the current password, then set the new one (Supabase Auth)."""
    client = _supabase()
    try:
        client.auth.sign_in_with_password({"email": email, "password": current_password})
    except Exception as e:  # noqa: BLE001
        raise AuthError("Current password is incorrect.") from e
    try:
        client.auth.update_user({"password": new_password})
    except Exception as e:  # noqa: BLE001
        raise AuthError(_friendly(e)) from e
    finally:
        try:
            client.auth.sign_out()
        except Exception:  # noqa: BLE001
            pass


def sign_out() -> None:
    try:
        _supabase().auth.sign_out()
    except Exception:  # noqa: BLE001
        pass
