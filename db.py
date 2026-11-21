import os

import mysql.connector
from decimal import Decimal
from dotenv import load_dotenv

# Loads .env from the project root (or the nearest parent) when present.
load_dotenv()

# Credentials come from the environment / .env file only. There is deliberately
# no hard-coded password fallback here.
db_config = {
    "host": os.getenv("DB_HOST") or os.getenv("db_host", "localhost"),
    "user": os.getenv("DB_USER") or os.getenv("db_user", "root"),
    "password": os.getenv("DB_PASSWORD") or os.getenv("db_password"),
    "database": os.getenv("DB_NAME") or os.getenv("db_database", "library_management_system"),
}


def get_connection():
    return mysql.connector.connect(**db_config)


# Shared constants
FINE_PER_DAY = Decimal("5.00")
LOAN_DAYS = 14


def query_all(sql, params=()):
    """Execute SQL and return all rows as dicts."""
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def query_one(sql, params=()):
    """Execute SQL and return single row as dict."""
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def execute(sql, params=()):
    """Execute SQL with commit."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        conn.commit()
    finally:
        cur.close()
        conn.close()
