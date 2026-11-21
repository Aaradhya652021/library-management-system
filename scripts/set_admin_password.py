"""Change an administrator password.

Usage:
    python scripts/set_admin_password.py
    python scripts/set_admin_password.py --username admin --password "new secret"
    python scripts/set_admin_password.py --list

Prompts without echoing when --password is omitted.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from werkzeug.security import generate_password_hash  # noqa: E402

from db import get_connection  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="admin", help="admin username")
    parser.add_argument("--password", help="new password (omit to be prompted)")
    parser.add_argument("--list", action="store_true", help="list admin usernames")
    args = parser.parse_args()

    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        if args.list:
            cur.execute("SELECT admin_id, username, full_name FROM admin ORDER BY admin_id")
            for row in cur.fetchall():
                print(f"{row['admin_id']}: {row['username']} ({row['full_name']})")
            return 0

        cur.execute(
            "SELECT admin_id FROM admin WHERE username = %s", (args.username,)
        )
        admin = cur.fetchone()
        if not admin:
            print(f"No admin named {args.username!r}.")
            return 1

        password = args.password
        if password is None:
            password = getpass.getpass("New password: ")
            confirm = getpass.getpass("Confirm new password: ")
            if password != confirm:
                print("Passwords do not match.")
                return 1

        if len(password) < 8:
            print("Password must be at least 8 characters.")
            return 1

        cur.execute(
            "UPDATE admin SET password_hash = %s WHERE admin_id = %s",
            (generate_password_hash(password), admin["admin_id"]),
        )
        conn.commit()
        print(f"Password updated for admin {args.username!r}.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
