"""Reset a user's password when using your own PostgreSQL (AUTH_MODE local).

    python scripts/reset_password.py you@example.com
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db  # noqa: E402
from core.auth import hash_password  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        return
    email = sys.argv[1].strip().lower()
    if not db.fetch_one("select 1 as x from app_users where email = %s", (email,)):
        print(f"No user with email {email}")
        return
    pw = getpass.getpass("New password: ")
    if len(pw) < 6 or pw != getpass.getpass("Repeat: "):
        print("Passwords do not match or are shorter than 6 characters.")
        return
    db.execute("update app_users set password_hash = %s where email = %s", (hash_password(pw), email))
    print("Password changed.")


if __name__ == "__main__":
    main()
