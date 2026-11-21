"""Run an idempotent SQL migration file against the configured database.

Usage:
    python scripts/migrate.py [path/to/migration.sql]

The default file is migrations/001_ml_feedback.sql.  Statements are split on
semicolons (respecting quoted strings and comments) and executed in order on a
single connection, which matters for the SET @ddl / PREPARE guard blocks.
"""
from __future__ import annotations

import os
import sys

# Make the project root importable when this file is run as a script.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db import get_connection  # noqa: E402


def split_sql(text: str) -> list[str]:
    """Split a SQL script into statements without breaking quoted strings."""
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(text)
    quote: str | None = None
    line_comment = False
    block_comment = False

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if line_comment:
            if ch == "\n":
                line_comment = False
                buf.append(ch)
            i += 1
            continue

        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
                continue
            i += 1
            continue

        if quote:
            buf.append(ch)
            if ch == quote:
                # Handle doubled quote escapes ('' or "") and backslash escapes.
                if nxt == quote:
                    buf.append(nxt)
                    i += 2
                    continue
                if i > 0 and text[i - 1] == "\\":
                    i += 1
                    continue
                quote = None
            i += 1
            continue

        if ch == "-" and nxt == "-":
            line_comment = True
            i += 2
            continue
        if ch == "#":
            line_comment = True
            i += 1
            continue
        if ch == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def run_migration(path: str) -> int:
    with open(path, "r", encoding="utf-8") as fh:
        sql = fh.read()

    statements = split_sql(sql)
    print(f"Running {len(statements)} statement(s) from {path} ...")

    conn = get_connection()
    try:
        cur = conn.cursor()
        for number, statement in enumerate(statements, start=1):
            first_line = statement.strip().splitlines()[0][:90]
            try:
                cur.execute(statement)
                # Drain result sets from SELECT / DO style guards.
                try:
                    while cur.nextset():
                        pass
                except Exception:
                    pass
                print(f"  [{number:02d}] ok  {first_line}")
            except Exception as exc:
                print(f"  [{number:02d}] FAILED: {first_line}")
                raise exc
        conn.commit()
        cur.close()
    finally:
        conn.close()

    print("Migration complete.")
    return 0


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "migrations", "001_ml_feedback.sql"
    )
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    if not os.path.isfile(path):
        print(f"Migration file not found: {path}")
        return 1
    return run_migration(path)


if __name__ == "__main__":
    raise SystemExit(main())
