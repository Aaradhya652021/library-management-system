"""Seed a realistic demo dataset for the ML recommendations and feedback UI.

Usage:
    python scripts/seed_demo.py --yes      # create demo members, books, issues, ratings
    python scripts/seed_demo.py --remove   # remove only the rows created by this script

The seed is deliberately isolated:

* demo members use the reserved e-mail domain ``demo.*@example.com``;
* demo books are only the ones listed in ``DEMO_BOOKS`` (matched to the ML
  catalog by exact title) and are recorded in ``seed_demo_manifest.json``;
* issues and ratings always belong to demo members / demo books;
* ``--yes`` first removes a previous demo seed, so running it twice is safe.

Existing members, books, issues and ratings are never modified or deleted
(except reusing an existing library copy of a demo title, which is left intact
on ``--remove``).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from werkzeug.security import generate_password_hash  # noqa: E402

from db import get_connection, query_all, query_one  # noqa: E402
from recommender import get_recommender  # noqa: E402

MANIFEST_PATH = os.path.join(ROOT, "scripts", "seed_demo_manifest.json")
DEMO_PASSWORD = "demo1234"
DEMO_PREFIX = "demo."

# A spread of well-known catalog titles across genres.  Titles are resolved
# against Machine_Learning/books_clean.csv (case-insensitive exact match).
DEMO_BOOKS = [
    "It Ends with Us",
    "Crown of Midnight",
    "A Voice in the Wind",
    "Harry Potter and the Deathly Hallows",
    "The Way of Kings",
    "The Godfather",
    "The Martian",
    "Cress",
    "Wonder",
    "The Hunger Games Box Set",
    "Americanah",
    "A Dog's Purpose",
    "The Nightingale",
    "The Help",
    "The Complete Sherlock Holmes",
    "The Giving Tree",
    "The Lorax",
    "Calvin and Hobbes",
    "Born a Crime: Stories From a South African Childhood",
    "When Breath Becomes Air",
    "Still Alice",
    "Cosmos",
    "Being Mortal: Medicine and What Matters in the End",
    "The Revenge of the Baby-Sat: A Calvin and Hobbes Collection",
    "milk and honey",
    "The Stand",
]

DEMO_MEMBERS = [
    ("Aarav Mehta", "demo.aarav.mehta@example.com", "+91-90000-00001"),
    ("Priya Sharma", "demo.priya.sharma@example.com", "+91-90000-00002"),
    ("Rohan Iyer", "demo.rohan.iyer@example.com", "+91-90000-00003"),
    ("Ananya Nair", "demo.ananya.nair@example.com", "+91-90000-00004"),
    ("Kabir Singh", "demo.kabir.singh@example.com", "+91-90000-00005"),
    ("Meera Joshi", "demo.meera.joshi@example.com", "+91-90000-00006"),
    ("Arjun Rao", "demo.arjun.rao@example.com", "+91-90000-00007"),
    ("Diya Kapoor", "demo.diya.kapoor@example.com", "+91-90000-00008"),
    ("Vihaan Gupta", "demo.vihaan.gupta@example.com", "+91-90000-00009"),
    ("Ishita Verma", "demo.ishita.verma@example.com", "+91-90000-00010"),
    ("Aditya Menon", "demo.aditya.menon@example.com", "+91-90000-00011"),
    ("Saanvi Desai", "demo.saanvi.desai@example.com", "+91-90000-00012"),
    ("Naveen Kumar", "demo.naveen.kumar@example.com", "+91-90000-00013"),
    ("Riya Bhatt", "demo.riya.bhatt@example.com", "+91-90000-00014"),
    ("Karan Malhotra", "demo.karan.malhotra@example.com", "+91-90000-00015"),
    ("Tanvi Shah", "demo.tanvi.shah@example.com", "+91-90000-00016"),
    ("Rahul Pillai", "demo.rahul.pillai@example.com", "+91-90000-00017"),
    ("Neha Reddy", "demo.neha.reddy@example.com", "+91-90000-00018"),
    ("Siddharth Bose", "demo.siddharth.bose@example.com", "+91-90000-00019"),
    ("Pooja Chawla", "demo.pooja.chawla@example.com", "+91-90000-00020"),
]

COMMENTS = {
    5: [
        "Loved every page - staying on my shelf.",
        "A new favourite. I finished it in two sittings.",
        "Beautifully written and impossible to put down.",
        "Exactly the kind of book I hoped it would be.",
    ],
    4: [
        "Really enjoyed it, with a couple of slow chapters.",
        "Strong story and characters I cared about.",
        "A great read - happy to recommend it.",
    ],
    3: [
        "Decent, but it did not fully win me over.",
        "Some parts were excellent and others dragged.",
        "Fine for a rainy weekend.",
    ],
    2: [
        "Not for me, though I see why others like it.",
        "The pacing lost me halfway through.",
    ],
    1: [
        "I struggled to finish this one.",
        "Sadly not a good fit for my taste.",
    ],
}

# Rating pattern used to make a few clear consensus panels.  Index matches
# DEMO_BOOKS; the first four deliberately produce strong 5/4/3/2-star buckets.
RATING_PATTERN = [
    5, 4, 5, 5, 4, 4, 5, 3, 4, 5,
    4, 5, 5, 4, 5, 3, 3, 5, 5, 3,
    2, 2, 4, 5, 4, 2,
]


def load_manifest() -> dict:
    if not os.path.isfile(MANIFEST_PATH):
        return {}
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_manifest(manifest: dict) -> None:
    with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)


def _placeholders(values) -> str:
    return ", ".join(["%s"] * len(values))


def remove_demo() -> None:
    """Delete demo rows recorded in the manifest (and any demo members left)."""
    manifest = load_manifest()
    created_books = [int(v) for v in manifest.get("book_ids_created", [])]
    recorded_users = {int(v) for v in manifest.get("user_ids", [])}

    rows = query_all(
        "SELECT user_id FROM users WHERE email LIKE %s", (DEMO_PREFIX + "%@example.com",)
    )
    user_ids = recorded_users | {int(row["user_id"]) for row in rows}

    conn = get_connection()
    try:
        cur = conn.cursor()
        if user_ids:
            marks = _placeholders(user_ids)
            cur.execute(
                f"DELETE FROM book_feedback WHERE user_id IN ({marks})",
                tuple(user_ids),
            )
            cur.execute(
                f"DELETE FROM issues WHERE user_id IN ({marks})", tuple(user_ids)
            )
            cur.execute(
                f"DELETE FROM segment_members WHERE user_id IN ({marks})",
                tuple(user_ids),
            )
        segment_ids = {int(v) for v in manifest.get("segment_ids", [])}
        if segment_ids:
            marks = _placeholders(segment_ids)
            cur.execute(
                f"DELETE FROM segments WHERE segment_id IN ({marks}) "
                f"AND name LIKE 'Demo %'",
                tuple(segment_ids),
            )
        # Commit before checking book references, otherwise this connection
        # would still see the rows just deleted.
        conn.commit()

        removed_books = 0
        skipped_books = []
        for book_id in created_books:
            used = query_one(
                "SELECT COUNT(*) AS c FROM issues WHERE book_id = %s", (book_id,)
            )
            rated = query_one(
                "SELECT COUNT(*) AS c FROM book_feedback WHERE book_id = %s", (book_id,)
            )
            if (used and used["c"]) or (rated and rated["c"]):
                skipped_books.append(book_id)
                continue
            cur.execute("DELETE FROM books WHERE book_id = %s", (book_id,))
            removed_books += 1

        if user_ids:
            marks = _placeholders(user_ids)
            cur.execute(
                f"DELETE FROM users WHERE user_id IN ({marks}) "
                f"AND email LIKE %s",
                tuple(user_ids) + (DEMO_PREFIX + "%@example.com",),
            )
        conn.commit()
        cur.close()
    finally:
        conn.close()

    if os.path.isfile(MANIFEST_PATH):
        os.remove(MANIFEST_PATH)

    print(f"Removed {len(user_ids)} demo member(s) and {removed_books} demo book(s).")
    if skipped_books:
        print(
            "Kept demo book(s) still referenced by other records: "
            + ", ".join(str(i) for i in skipped_books)
        )


def _find_catalog_row(catalog, title: str):
    wanted = title.strip().lower()
    rows = catalog[catalog["title"].fillna("").str.strip().str.lower() == wanted]
    if rows.empty:
        raise SystemExit(f"Catalog title not found: {title!r}")
    return rows.iloc[0]


def _clean_isbn(value):
    try:
        text = str(int(float(value)))
    except (TypeError, ValueError):
        text = str(value or "").strip()
    if text.lower() in ("", "nan", "none"):
        return None
    return text


def _rating_for(book_index: int, position: int) -> int:
    base = RATING_PATTERN[book_index % len(RATING_PATTERN)]
    if book_index < 4 or book_index in (15, 20, 21):
        return base  # deliberate positive / neutral / negative consensus buckets
    if position == 0:
        return base
    return max(1, min(5, base + (1 if (book_index + position) % 3 == 0 else 0)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes", action="store_true", help="confirm creating demo data"
    )
    parser.add_argument(
        "--remove", action="store_true", help="remove demo data created earlier"
    )
    args = parser.parse_args()

    if args.remove:
        remove_demo()
        return 0

    if not args.yes:
        print("This script writes demo data.")
        print("Run with --yes to create it, or --remove to delete it.")
        return 1

    # Re-running --yes replaces the previous demo seed cleanly.
    if load_manifest() or query_one(
        "SELECT user_id FROM users WHERE email LIKE %s LIMIT 1",
        (DEMO_PREFIX + "%@example.com",),
    ):
        remove_demo()

    recommender = get_recommender()
    if not recommender.ok:
        print(f"Recommender unavailable: {recommender.error}")
        return 1
    catalog = recommender.catalog

    admin = query_one("SELECT admin_id FROM admin ORDER BY admin_id LIMIT 1")
    admin_id = admin["admin_id"] if admin else None
    today = date.today()
    rng = random.Random(20261105)
    password_hash = generate_password_hash(DEMO_PASSWORD)

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "catalog": "Machine_Learning/books_clean.csv",
        "ml_indices": [],
        "book_ids_created": [],
        "book_ids_reused": [],
        "user_ids": [],
        "user_emails": [],
        "issue_ids": [],
        "feedback_ids": [],
        "segment_ids": [],
    }

    # ------------------------------------------------------------- members --
    user_ids = []
    for name, email, phone in DEMO_MEMBERS:
        existing = query_one("SELECT user_id FROM users WHERE email = %s", (email,))
        if existing:
            user_ids.append(int(existing["user_id"]))
            continue
        joined = today - timedelta(days=rng.randint(30, 500))
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (name, email, phone_no, password_hash, joined_on) "
                "VALUES (%s, %s, %s, %s, %s)",
                (name, email, phone, password_hash, joined.isoformat()),
            )
            user_ids.append(int(cur.lastrowid))
            conn.commit()
            cur.close()
        finally:
            conn.close()

    manifest["user_ids"] = user_ids
    manifest["user_emails"] = [email for _n, email, _p in DEMO_MEMBERS]

    # --------------------------------------------------------------- books --
    book_ids = []
    book_meta = {}
    for title in DEMO_BOOKS:
        row = _find_catalog_row(catalog, title)
        ml_idx = int(row.name)
        existing = query_one(
            "SELECT book_id, total_copies FROM books WHERE ml_idx = %s", (ml_idx,)
        )
        if existing:
            book_id = int(existing["book_id"])
            manifest["book_ids_reused"].append(book_id)
            total = int(existing["total_copies"] or 1)
        else:
            conn = get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO books (title, author, isbn, genre, total_copies, "
                    "available_copies, ml_idx, weighted_rating, added_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        str(row["title"]).strip()[:100],
                        (str(row["primary_author"]) or str(row["author"]))[:300],
                        _clean_isbn(row.get("isbn13")),
                        (str(row["category_grouped"]) or "Fiction")[:100],
                        6,
                        6,
                        ml_idx,
                        None
                        if row.get("weighted_rating") is None
                        else round(float(row["weighted_rating"]), 2),
                        admin_id,
                    ),
                )
                book_id = int(cur.lastrowid)
                manifest["book_ids_created"].append(book_id)
                conn.commit()
                cur.close()
            finally:
                conn.close()
            total = 6
        book_ids.append(book_id)
        book_meta[book_id] = {"ml_idx": ml_idx, "total": total, "title": str(row["title"]).strip()}
        manifest["ml_indices"].append(ml_idx)

    # The manifest is written early so a crash can still be cleaned up.
    save_manifest(manifest)

    # ------------------------------------------------- returned issues+ratings --
    book_borrowers = {}
    returned_rows = []
    for position, book_id in enumerate(book_ids):
        count = 2 + (position % 3)  # 2-4 agreeing borrowers per book
        # Round-robin with a coprime step spreads issues evenly over members.
        start = (position * 2) % len(user_ids)
        borrowers = [
            user_ids[(start + offset * 7) % len(user_ids)]
            for offset in range(count)
        ]
        book_borrowers[book_id] = borrowers
        for user_id in borrowers:
            issue_date = today - timedelta(days=rng.randint(30, 240))
            due_date = issue_date + timedelta(days=14)
            return_date = issue_date + timedelta(days=rng.randint(6, 27))
            if return_date > today:
                return_date = today
            late_days = max((return_date - due_date).days, 0)
            fine = round(late_days * 5.0, 2)
            returned_rows.append(
                (book_id, user_id, issue_date, due_date, return_date, fine)
            )

    # -------------------------------------------------------- active issues --
    outstanding_rows = query_all(
        "SELECT book_id, COUNT(*) AS c FROM issues "
        "WHERE return_date IS NULL GROUP BY book_id"
    )
    outstanding = {row["book_id"]: int(row["c"]) for row in outstanding_rows}
    created_set = set(manifest["book_ids_created"])
    active_plan = []  # (book_id, user_id, issue_date, due_date)
    active_count = {book_id: 0 for book_id in book_ids}
    for member_no, user_id in enumerate(user_ids):
        book_id = book_ids[(member_no * 5 + 3) % len(book_ids)]
        # Keep each member reading something they have not just returned.
        if user_id in book_borrowers.get(book_id, []):
            for offset in range(1, len(book_ids)):
                candidate = book_ids[(member_no * 5 + 3 + offset) % len(book_ids)]
                if user_id not in book_borrowers.get(candidate, []):
                    book_id = candidate
                    break
        capacity = 99 if book_id in created_set else max(
            0, book_meta[book_id]["total"] - outstanding.get(book_id, 0)
        )
        if active_count[book_id] >= capacity:
            continue
        issue_date = today - timedelta(days=rng.randint(0, 38))
        due_date = issue_date + timedelta(days=14)
        active_plan.append((book_id, user_id, issue_date, due_date))
        active_count[book_id] += 1

    # ---------------------------------------------------------- write issues --
    issue_lookup = {}
    conn = get_connection()
    try:
        cur = conn.cursor()
        for book_id, user_id, issue_date, due_date, return_date, fine in returned_rows:
            cur.execute(
                "INSERT INTO issues (book_id, user_id, issue_date, due_date, "
                "return_date, fine, issued_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    book_id,
                    user_id,
                    issue_date.isoformat(),
                    due_date.isoformat(),
                    return_date.isoformat(),
                    fine,
                    admin_id,
                ),
            )
            manifest["issue_ids"].append(int(cur.lastrowid))
            issue_lookup[(book_id, user_id)] = int(cur.lastrowid)

        for book_id, user_id, issue_date, due_date in active_plan:
            cur.execute(
                "INSERT INTO issues (book_id, user_id, issue_date, due_date, "
                "fine, issued_by) VALUES (%s, %s, %s, %s, 0, %s)",
                (
                    book_id,
                    user_id,
                    issue_date.isoformat(),
                    due_date.isoformat(),
                    admin_id,
                ),
            )
            manifest["issue_ids"].append(int(cur.lastrowid))

        # Copy availability: total = already-outstanding + demo-active + 2 spare.
        for book_id in book_ids:
            total = book_meta[book_id]["total"]
            active = active_count.get(book_id, 0)
            already = outstanding.get(book_id, 0)
            if book_id in created_set:
                total = max(3, already + active + 2)
            available = max(total - already - active, 0)
            cur.execute(
                "UPDATE books SET total_copies = %s, available_copies = %s "
                "WHERE book_id = %s",
                (total, available, book_id),
            )
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # ------------------------------------------------------------- feedback --
    feedback_rows = 0
    conn = get_connection()
    try:
        cur = conn.cursor()
        for position, book_id in enumerate(book_ids):
            for member_position, user_id in enumerate(book_borrowers[book_id]):
                # Leave a realistic handful of returned books unrated.
                if position >= 4 and (position + member_position) % 9 == 0:
                    continue
                rating = _rating_for(position, member_position)
                comment = None
                if member_position == 0 and rating in COMMENTS:
                    comment = COMMENTS[rating][position % len(COMMENTS[rating])]
                cur.execute(
                    "INSERT INTO book_feedback (user_id, book_id, issue_id, rating, comment) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE issue_id = VALUES(issue_id), "
                    "rating = VALUES(rating), comment = VALUES(comment)",
                    (
                        user_id,
                        book_id,
                        issue_lookup.get((book_id, user_id)),
                        rating,
                        comment,
                    ),
                )
                feedback_rows += 1
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # Guarantee every demo member has at least one 4/5-star rating so the ML
    # segment, recommendations and "average rating given" tile all have data.
    for user_id in user_ids:
        has_liked = query_one(
            "SELECT feedback_id FROM book_feedback "
            "WHERE user_id = %s AND rating >= 4 LIMIT 1",
            (user_id,),
        )
        if has_liked:
            continue
        for book_id in book_ids:
            if user_id in book_borrowers.get(book_id, []):
                conn = get_connection()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO book_feedback (user_id, book_id, issue_id, rating) "
                        "VALUES (%s, %s, %s, 4) "
                        "ON DUPLICATE KEY UPDATE rating = VALUES(rating)",
                        (user_id, book_id, issue_lookup.get((book_id, user_id))),
                    )
                    conn.commit()
                    cur.close()
                finally:
                    conn.close()
                break

    manifest["feedback_ids"] = [
        int(row["feedback_id"])
        for row in query_all(
            "SELECT feedback_id FROM book_feedback WHERE user_id IN (%s)"
            % _placeholders(user_ids),
            tuple(user_ids),
        )
    ]

    # ---------------------------------------------------- ML segment refresh --
    from recs import refresh_ml_segment  # imported late to keep --remove light

    refreshed = 0
    for user_id in user_ids:
        if refresh_ml_segment(user_id):
            refreshed += 1

    # ------------------------------------------------ demo reading group ------
    # Prefer a source book with at least three positive ratings so the demo
    # group has a real consensus panel behind it.
    preferred_source = query_one(
        "SELECT book_id FROM book_feedback WHERE rating >= 4 "
        "GROUP BY book_id HAVING COUNT(*) >= 3 "
        "ORDER BY COUNT(*) DESC, book_id ASC LIMIT 1"
    )
    source_book = preferred_source["book_id"] if preferred_source else book_ids[0]
    source_ml_idx = book_meta[source_book]["ml_idx"]
    fans = query_all(
        "SELECT bf.user_id, u.name FROM book_feedback bf "
        "JOIN users u ON u.user_id = bf.user_id "
        "WHERE bf.book_id = %s AND bf.rating >= 4 "
        "ORDER BY bf.rating DESC, bf.user_id ASC LIMIT 3",
        (source_book,),
    )
    if len(fans) >= 2:
        segment_name = f"Demo · Loved {book_meta[source_book]['title']}"[:140]
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO segments (label, name, description, kind, "
                "source_book_id, sentiment, created_by) "
                "VALUES (%s, %s, %s, 'feedback', %s, 'positive', %s)",
                (
                    segment_name,
                    segment_name,
                    "Demo reading group built from positive feedback.",
                    source_book,
                    admin_id,
                ),
            )
            segment_id = int(cur.lastrowid)
            for fan in fans:
                cur.execute(
                    "INSERT IGNORE INTO segment_members "
                    "(segment_id, user_id, assigned_by) VALUES (%s, %s, 'admin')",
                    (segment_id, fan["user_id"]),
                )
            similar = recommender.similar_books(source_ml_idx, k=8)
            candidates = [
                item for item in similar if int(item["ml_idx"]) != source_ml_idx
            ]
            pick = None
            library_pick = None
            for item in candidates:
                in_library = query_one(
                    "SELECT book_id FROM books WHERE ml_idx = %s",
                    (int(item["ml_idx"]),),
                )
                if in_library:
                    pick, library_pick = item, in_library
                    break
            if pick is None and candidates:
                pick = candidates[0]
            if pick:
                cur.execute(
                    "INSERT INTO segment_books "
                    "(segment_id, ml_idx, book_id, note, created_by) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        segment_id,
                        int(pick["ml_idx"]),
                        library_pick["book_id"] if library_pick else None,
                        "Demo pick: readers who liked the source book also liked this.",
                        admin_id,
                    ),
                )
            conn.commit()
            cur.close()
            manifest["segment_ids"].append(segment_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    save_manifest(manifest)

    print(f"Demo members:        {len(user_ids)}")
    print(f"Demo books created:  {len(manifest['book_ids_created'])}")
    print(f"Demo books reused:   {len(manifest['book_ids_reused'])}")
    print(f"Issues created:      {len(manifest['issue_ids'])}")
    print(f"Ratings created:     {feedback_rows}")
    print(f"ML segments set:     {refreshed}")
    print(f"Reading groups:      {len(manifest['segment_ids'])}")
    print(f"Demo member login:   <e-mail> / {DEMO_PASSWORD}")
    print(f"Manifest:            {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
