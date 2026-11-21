"""Member reading-progress report.

Everything is derived from the existing issues / books / book_feedback tables;
there is no extra data entry.  Both the member dashboard and the admin member
page call get_progress(user_id).
"""
from __future__ import annotations

from datetime import date

from db import query_all, query_one

LEVELS = [
    ("Newcomer", 0, 3),
    ("Reader", 3, 10),
    ("Bookworm", 10, 25),
    ("Scholar", 25, None),
]


def reading_level(returned_count: int) -> dict:
    """Return the badge and progress-to-next-level for a returned count."""
    count = max(0, int(returned_count or 0))
    for name, low, high in LEVELS:
        if high is None or count < high:
            if high is None:
                return {
                    "name": name,
                    "returned": count,
                    "next_level": None,
                    "books_to_next": 0,
                    "progress_pct": 100,
                }
            span = high - low
            progress = (count - low) / span if span else 0
            return {
                "name": name,
                "returned": count,
                "next_level": next(
                    (lvl[0] for lvl in LEVELS if lvl[1] == high), None
                ),
                "books_to_next": high - count,
                "progress_pct": int(round(max(0, min(1, progress)) * 100)),
            }
    # Unreachable, kept for safety.
    return {
        "name": "Scholar",
        "returned": count,
        "next_level": None,
        "books_to_next": 0,
        "progress_pct": 100,
    }


def _last_six_months() -> list[tuple[str, str]]:
    today = date.today()
    months: list[tuple[str, str]] = []
    year, month = today.year, today.month
    for _ in range(6):
        months.append((f"{year:04d}-{month:02d}", date(year, month, 1).strftime("%b %Y")))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(months))


def get_progress(user_id: int) -> dict:
    issues = query_all(
        "SELECT i.issue_id, i.book_id, i.issue_date, i.due_date, i.return_date, "
        "i.fine, b.title, b.genre "
        "FROM issues i JOIN books b ON b.book_id = i.book_id "
        "WHERE i.user_id = %s ORDER BY i.issue_id DESC",
        (user_id,),
    )

    today = date.today()
    borrowed = len(issues)
    returned = [row for row in issues if row["return_date"] is not None]
    reading = [row for row in issues if row["return_date"] is None]
    on_time = sum(
        1 for row in returned if row["return_date"] and row["return_date"] <= row["due_date"]
    )
    total_fines = sum(float(row["fine"] or 0) for row in issues)

    rating_stats = query_one(
        "SELECT COUNT(*) AS rated_count, AVG(rating) AS avg_rating "
        "FROM book_feedback WHERE user_id = %s",
        (user_id,),
    ) or {"rated_count": 0, "avg_rating": None}

    unrated = query_all(
        "SELECT b.book_id, b.title, MAX(i.return_date) AS last_returned "
        "FROM issues i "
        "JOIN books b ON b.book_id = i.book_id "
        "LEFT JOIN book_feedback bf "
        "  ON bf.user_id = i.user_id AND bf.book_id = i.book_id "
        "WHERE i.user_id = %s AND i.return_date IS NOT NULL "
        "  AND bf.feedback_id IS NULL "
        "GROUP BY b.book_id, b.title "
        "ORDER BY last_returned DESC",
        (user_id,),
    )

    monthly_rows = query_all(
        "SELECT DATE_FORMAT(return_date, '%%Y-%%m') AS ym, COUNT(*) AS c "
        "FROM issues "
        "WHERE user_id = %s AND return_date IS NOT NULL "
        "  AND return_date >= DATE_SUB(DATE_FORMAT(CURDATE(), '%%Y-%%m-01'), INTERVAL 5 MONTH) "
        "GROUP BY ym",
        (user_id,),
    )
    monthly_counts = {row["ym"]: int(row["c"]) for row in monthly_rows}
    months = _last_six_months()
    monthly = [
        {"key": key, "label": label, "count": monthly_counts.get(key, 0)}
        for key, label in months
    ]
    max_month = max((item["count"] for item in monthly), default=0)

    genre_rows = query_all(
        "SELECT COALESCE(NULLIF(TRIM(b.genre), ''), 'Unspecified') AS genre, "
        "COUNT(*) AS c "
        "FROM issues i JOIN books b ON b.book_id = i.book_id "
        "WHERE i.user_id = %s AND i.return_date IS NOT NULL "
        "GROUP BY genre ORDER BY c DESC, genre ASC",
        (user_id,),
    )
    max_genre = max((int(row["c"]) for row in genre_rows), default=0)
    genres = [
        {
            "genre": row["genre"],
            "count": int(row["c"]),
            "pct": int(round(100 * int(row["c"]) / max_genre)) if max_genre else 0,
        }
        for row in genre_rows
    ]

    currently_reading = []
    for row in reading:
        days_left = (row["due_date"] - today).days
        currently_reading.append(
            {
                "issue_id": row["issue_id"],
                "book_id": row["book_id"],
                "title": row["title"],
                "due_date": row["due_date"],
                "days_left": days_left,
                "overdue_days": abs(days_left) if days_left < 0 else 0,
            }
        )
    currently_reading.sort(key=lambda item: item["days_left"])

    level = reading_level(len(returned))

    return {
        "borrowed": borrowed,
        "returned": len(returned),
        "reading": len(reading),
        "on_time_rate": round(100 * on_time / len(returned), 1) if returned else 0.0,
        "on_time_count": on_time,
        "total_fines": round(total_fines, 2),
        "avg_rating": round(float(rating_stats["avg_rating"]), 2)
        if rating_stats["avg_rating"] is not None
        else None,
        "rated_count": int(rating_stats["rated_count"] or 0),
        "unrated": unrated,
        "monthly": monthly,
        "max_month": max_month,
        "genres": genres,
        "currently_reading": currently_reading,
        "level": level,
    }
