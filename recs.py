"""Recommendation, feedback and segmentation routes.

Registered as a blueprint from app.py.  URLs stay under the existing app
(no prefix) so the old routes keep working.
"""
from __future__ import annotations

import logging

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)
import mysql.connector

from auth_utils import admin_required, member_required
from db import execute, get_connection, query_all, query_one
from progress import get_progress
from recommender import get_recommender

logger = logging.getLogger(__name__)

recs_bp = Blueprint("recs", __name__)

# A bucket becomes a consensus panel at two distinct members; 3+ is "strong".
CONSENSUS_MIN_USERS = 2
STRONG_CONSENSUS_USERS = 3


# --------------------------------------------------------------- utilities --
def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rating_stats(book_ids):
    """Return {book_id: {count, avg_rating}} for a list of library books."""
    book_ids = [int(i) for i in book_ids if i is not None]
    if not book_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(book_ids))
    rows = query_all(
        f"SELECT book_id, COUNT(*) AS count, AVG(rating) AS avg_rating "
        f"FROM book_feedback WHERE book_id IN ({placeholders}) GROUP BY book_id",
        tuple(book_ids),
    )
    return {
        row["book_id"]: {
            "count": int(row["count"]),
            "avg_rating": round(float(row["avg_rating"]), 2),
        }
        for row in rows
    }


def _member_ratings(user_id):
    rows = query_all(
        "SELECT book_id, rating FROM book_feedback WHERE user_id = %s", (user_id,)
    )
    return {row["book_id"]: int(row["rating"]) for row in rows}


def member_feedback_context(user_id, book_ids=None):
    """Template context for star widgets and average-rating captions."""
    my_ratings = _member_ratings(user_id)
    if book_ids is None:
        book_ids = list(my_ratings)
    else:
        book_ids = [int(i) for i in book_ids if i is not None]
    return {"my_ratings": my_ratings, "rating_stats": _rating_stats(book_ids)}


def _library_map():
    """All library books that are linked to the ML catalog, keyed by ml_idx."""
    rows = query_all(
        "SELECT book_id, title, author, isbn, genre, total_copies, "
        "available_copies, ml_idx FROM books WHERE ml_idx IS NOT NULL"
    )
    stats = _rating_stats([row["book_id"] for row in rows])
    mapping = {}
    for row in rows:
        item = dict(row)
        item.update(stats.get(row["book_id"], {"count": 0, "avg_rating": None}))
        mapping[int(row["ml_idx"])] = item
    return mapping


def _availability_text(book):
    if not book:
        return "Not in our library yet"
    if int(book["available_copies"] or 0) > 0:
        return f"{book['available_copies']} of {book['total_copies']} copies available"
    return "All copies issued"


def _split_tiers(recommendations, library_map):
    in_library = []
    suggested = []
    for item in recommendations:
        book = library_map.get(int(item["ml_idx"]))
        if book:
            enriched = dict(item)
            enriched["library"] = book
            enriched["available_text"] = _availability_text(book)
            enriched["library_rating"] = book.get("avg_rating")
            enriched["library_rating_count"] = book.get("count", 0)
            in_library.append(enriched)
        else:
            suggested.append(item)
    return in_library, suggested


def _preferred_genres(user_id):
    rows = query_all(
        "SELECT COALESCE(NULLIF(TRIM(b.genre), ''), 'Unspecified') AS genre, "
        "COUNT(*) AS c "
        "FROM book_feedback bf JOIN books b ON b.book_id = bf.book_id "
        "WHERE bf.user_id = %s AND bf.rating >= 4 "
        "GROUP BY genre ORDER BY c DESC, genre ASC LIMIT 5",
        (user_id,),
    )
    if not rows:
        rows = query_all(
            "SELECT COALESCE(NULLIF(TRIM(b.genre), ''), 'Unspecified') AS genre, "
            "COUNT(*) AS c "
            "FROM issues i JOIN books b ON b.book_id = i.book_id "
            "WHERE i.user_id = %s AND i.return_date IS NOT NULL "
            "GROUP BY genre ORDER BY c DESC, genre ASC LIMIT 5",
            (user_id,),
        )
    return [row["genre"] for row in rows]


def _member_recs(user_id, k=24):
    recommender = get_recommender()
    if not recommender.ok:
        return [], []
    rows = query_all(
        "SELECT b.ml_idx, bf.rating FROM book_feedback bf "
        "JOIN books b ON b.book_id = bf.book_id "
        "WHERE bf.user_id = %s AND b.ml_idx IS NOT NULL",
        (user_id,),
    )
    ratings = {int(row["ml_idx"]): int(row["rating"]) for row in rows}
    recommendations = recommender.recommend_for_user(
        ratings, k=k, preferred_genres=_preferred_genres(user_id)
    )
    return _split_tiers(recommendations, _library_map())


def _segment_picks(user_id):
    recommender = get_recommender()
    rows = query_all(
        "SELECT s.segment_id, s.name AS segment_name, s.kind, s.sentiment, "
        "sb.id AS pick_id, sb.ml_idx, sb.book_id, sb.note, "
        "b.title, b.author, b.genre, b.available_copies, b.total_copies "
        "FROM segment_members sm "
        "JOIN segments s ON s.segment_id = sm.segment_id "
        "JOIN segment_books sb ON sb.segment_id = s.segment_id "
        "LEFT JOIN books b ON b.book_id = sb.book_id "
        "WHERE sm.user_id = %s "
        "ORDER BY s.name ASC, sb.id ASC",
        (user_id,),
    )
    picks = []
    for row in rows:
        item = dict(row)
        if item["book_id"]:
            item["in_library"] = True
            item["available_text"] = _availability_text(item)
            item["display_title"] = item["title"]
            item["display_author"] = item["author"]
        else:
            item["in_library"] = False
            item["available_text"] = "Suggested, not in library yet"
            catalog_item = recommender.get_item(item["ml_idx"]) if recommender.ok else None
            item["display_title"] = catalog_item["title"] if catalog_item else f"Catalog #{item['ml_idx']}"
            item["display_author"] = catalog_item["author"] if catalog_item else ""
            item["genre"] = catalog_item["category"] if catalog_item else ""
        picks.append(item)
    return picks


def member_dashboard_data(user_id):
    in_library, suggested = _member_recs(user_id)
    ratings = _member_ratings(user_id)
    feedback = member_feedback_context(user_id, list(ratings))
    return {
        "recommended_in_library": in_library,
        "recommended_suggested": suggested,
        "segment_picks": _segment_picks(user_id),
        "progress": get_progress(user_id),
        **feedback,
    }


def refresh_ml_segment(user_id):
    """Recompute a member's single auto ML segment. Safe to call repeatedly."""
    recommender = get_recommender()
    if not recommender.ok:
        return None
    rows = query_all(
        "SELECT b.ml_idx, bf.rating FROM book_feedback bf "
        "JOIN books b ON b.book_id = bf.book_id "
        "WHERE bf.user_id = %s AND b.ml_idx IS NOT NULL",
        (user_id,),
    )
    liked = [row for row in rows if int(row["rating"]) >= 4]
    profile: dict[str, int] = {}
    for row in liked:
        item = recommender.get_item(row["ml_idx"])
        if item and item["category"]:
            profile[item["category"]] = profile.get(item["category"], 0) + 1
    if not profile:
        return None
    cluster = recommender.user_segment(profile)
    if cluster is None:
        return None
    segment = query_one(
        "SELECT segment_id FROM segments WHERE kind = 'ml' AND ml_cluster = %s",
        (cluster,),
    )
    if not segment:
        return None
    execute(
        "DELETE sm FROM segment_members sm "
        "JOIN segments s ON s.segment_id = sm.segment_id "
        "WHERE sm.user_id = %s AND sm.assigned_by = 'auto' AND s.kind = 'ml'",
        (user_id,),
    )
    execute(
        "INSERT IGNORE INTO segment_members (segment_id, user_id, assigned_by) "
        "VALUES (%s, %s, 'auto')",
        (segment["segment_id"], user_id),
    )
    return segment["segment_id"]


# ----------------------------------------------------------------- feedback --
@recs_bp.post("/feedback")
@member_required
def feedback():
    user_id = session["user_id"]
    book_id = _to_int(request.form.get("book_id"))
    rating = _to_int(request.form.get("rating"))
    comment = (request.form.get("comment") or "").strip()[:500]

    book = query_one("SELECT * FROM books WHERE book_id = %s", (book_id,))
    if not book:
        flash("That book could not be found.", "error")
        return redirect(url_for("index"))
    if rating < 1 or rating > 5:
        flash("Rating must be between 1 and 5 stars.", "error")
        return redirect(url_for("index"))

    issue = query_one(
        "SELECT issue_id FROM issues WHERE user_id = %s AND book_id = %s "
        "AND return_date IS NOT NULL ORDER BY return_date DESC, issue_id DESC LIMIT 1",
        (user_id, book_id),
    )
    if not issue:
        flash("You can only rate books you have borrowed and returned.", "error")
        return redirect(url_for("index"))

    try:
        execute(
            "INSERT INTO book_feedback (user_id, book_id, issue_id, rating, comment) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE rating = VALUES(rating), "
            "comment = VALUES(comment), issue_id = VALUES(issue_id)",
            (user_id, book_id, issue["issue_id"], rating, comment or None),
        )
        refresh_ml_segment(user_id)
        flash(f"Thanks! Your {rating}-star rating for '{book['title']}' was saved.", "ok")
    except mysql.connector.Error as err:
        logger.exception("Could not save feedback")
        flash(f"Could not save your rating: {err.msg}", "error")

    target = request.form.get("next") or request.referrer
    if target and target.startswith("/"):
        return redirect(target)
    return redirect(url_for("index"))


# ------------------------------------------------------------ admin: feedback --
@recs_bp.get("/admin/feedback")
@admin_required
def admin_feedback():
    min_raters = max(0, _to_int(request.args.get("min_raters"), 0))
    sort = request.args.get("sort", "avg")
    order = "raters DESC, avg_rating DESC" if sort == "count" else "avg_rating DESC, raters DESC"

    rows = query_all(
        "SELECT b.book_id, b.title, COUNT(*) AS raters, AVG(bf.rating) AS avg_rating "
        "FROM book_feedback bf JOIN books b ON b.book_id = bf.book_id "
        "GROUP BY b.book_id, b.title "
        "HAVING COUNT(*) >= %s "
        f"ORDER BY {order}, b.title ASC",
        (min_raters,),
    )

    distribution_rows = query_all(
        "SELECT book_id, rating, COUNT(*) AS c FROM book_feedback "
        "GROUP BY book_id, rating"
    )
    distribution: dict[int, dict[int, int]] = {}
    for row in distribution_rows:
        distribution.setdefault(row["book_id"], {})[int(row["rating"])] = int(row["c"])

    books = []
    for row in rows:
        counts = distribution.get(row["book_id"], {})
        raters = int(row["raters"])
        books.append(
            {
                "book_id": row["book_id"],
                "title": row["title"],
                "raters": raters,
                "avg_rating": round(float(row["avg_rating"]), 2),
                "distribution": [
                    {
                        "stars": stars,
                        "count": counts.get(stars, 0),
                        "pct": int(round(100 * counts.get(stars, 0) / raters)) if raters else 0,
                    }
                    for stars in (5, 4, 3, 2, 1)
                ],
            }
        )

    totals = query_one(
        "SELECT COUNT(*) AS total_ratings, AVG(rating) AS avg_rating FROM book_feedback"
    )
    return render_template(
        "admin_feedback.html",
        books=books,
        min_raters=min_raters,
        sort=sort,
        totals=totals,
    )


@recs_bp.get("/admin/feedback/book/<int:book_id>")
@admin_required
def admin_feedback_book(book_id):
    book = query_one("SELECT * FROM books WHERE book_id = %s", (book_id,))
    if not book:
        abort(404)
    ratings = query_all(
        "SELECT bf.rating, bf.comment, bf.created_at, bf.updated_at, "
        "u.user_id, u.name, u.email "
        "FROM book_feedback bf JOIN users u ON u.user_id = bf.user_id "
        "WHERE bf.book_id = %s "
        "ORDER BY bf.rating DESC, bf.updated_at DESC",
        (book_id,),
    )
    buckets = [
        ("positive", "4-5 stars", lambda r: r >= 4, "Loved {title}"),
        ("neutral", "3 stars", lambda r: r == 3, "On the fence about {title}"),
        ("negative", "1-2 stars", lambda r: r <= 2, "Disliked {title}"),
    ]
    result = []
    for sentiment, label, predicate, name_template in buckets:
        entries = [row for row in ratings if predicate(int(row["rating"]))]
        distinct_users = {row["user_id"] for row in entries}
        result.append(
            {
                "sentiment": sentiment,
                "label": label,
                "entries": entries,
                "count": len(distinct_users),
                "consensus": len(distinct_users) >= CONSENSUS_MIN_USERS,
                "strong": len(distinct_users) >= STRONG_CONSENSUS_USERS,
                "suggested_name": name_template.format(title=book["title"]),
            }
        )
    avg = query_one(
        "SELECT COUNT(*) AS c, AVG(rating) AS a FROM book_feedback WHERE book_id = %s",
        (book_id,),
    )
    return render_template(
        "admin_feedback_book.html",
        book=book,
        buckets=result,
        summary={
            "count": int(avg["c"] or 0),
            "avg": round(float(avg["a"]), 2) if avg["a"] is not None else None,
        },
        consensus_min=CONSENSUS_MIN_USERS,
    )


@recs_bp.post("/admin/segments/from-book/<int:book_id>")
@admin_required
def create_feedback_segment(book_id):
    book = query_one("SELECT * FROM books WHERE book_id = %s", (book_id,))
    if not book:
        abort(404)
    sentiment = request.form.get("sentiment")
    if sentiment not in ("positive", "neutral", "negative"):
        flash("Choose a valid sentiment bucket.", "error")
        return redirect(url_for("recs.admin_feedback_book", book_id=book_id))
    user_ids = []
    for raw in request.form.getlist("user_ids"):
        value = _to_int(raw)
        if value > 0:
            user_ids.append(value)
    if not user_ids:
        flash("Select at least one member for the segment.", "error")
        return redirect(url_for("recs.admin_feedback_book", book_id=book_id))

    name = (request.form.get("name") or f"Segment for {book['title']}").strip()[:140]
    description = (request.form.get("description") or "").strip()[:500] or None

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO segments (label, name, description, kind, source_book_id, "
            "sentiment, created_by) VALUES (%s, %s, %s, 'feedback', %s, %s, %s)",
            (name, name, description, book_id, sentiment, session.get("admin_id")),
        )
        segment_id = cur.lastrowid
        for user_id in sorted(set(user_ids)):
            cur.execute(
                "INSERT IGNORE INTO segment_members (segment_id, user_id, assigned_by) "
                "VALUES (%s, %s, 'admin')",
                (segment_id, user_id),
            )
        conn.commit()
    except mysql.connector.Error as err:
        conn.rollback()
        logger.exception("Could not create feedback segment")
        flash(f"Could not create segment: {err.msg}", "error")
        return redirect(url_for("recs.admin_feedback_book", book_id=book_id))
    finally:
        conn.close()

    flash(f"Segment '{name}' created with {len(set(user_ids))} member(s).", "ok")
    return redirect(url_for("recs.admin_segment_detail", segment_id=segment_id))


# ------------------------------------------------------------ admin: segments --
@recs_bp.get("/admin/segments")
@admin_required
def admin_segments():
    ml_segments = query_all(
        "SELECT s.segment_id, s.name, s.description, s.ml_cluster, s.top_genres, "
        "COUNT(sm.user_id) AS member_count "
        "FROM segments s LEFT JOIN segment_members sm ON sm.segment_id = s.segment_id "
        "WHERE s.kind = 'ml' "
        "GROUP BY s.segment_id, s.name, s.description, s.ml_cluster, s.top_genres "
        "ORDER BY s.ml_cluster ASC"
    )
    feedback_segments = query_all(
        "SELECT s.segment_id, s.name, s.sentiment, s.created_at, "
        "b.book_id AS source_book_id, b.title AS source_title, "
        "COUNT(sm.user_id) AS member_count "
        "FROM segments s "
        "LEFT JOIN books b ON b.book_id = s.source_book_id "
        "LEFT JOIN segment_members sm ON sm.segment_id = s.segment_id "
        "WHERE s.kind = 'feedback' "
        "GROUP BY s.segment_id, s.name, s.sentiment, s.created_at, "
        "b.book_id, b.title "
        "ORDER BY s.created_at DESC, s.segment_id DESC"
    )
    return render_template(
        "admin_segments.html",
        ml_segments=ml_segments,
        feedback_segments=feedback_segments,
    )


@recs_bp.post("/admin/segments/recompute")
@admin_required
def admin_segments_recompute():
    rows = query_all("SELECT DISTINCT user_id FROM book_feedback")
    updated = 0
    for row in rows:
        if refresh_ml_segment(row["user_id"]):
            updated += 1
    flash(f"Recomputed ML segments for {updated} member(s) with ratings.", "ok")
    return redirect(url_for("recs.admin_segments"))


@recs_bp.get("/admin/segments/<int:segment_id>")
@admin_required
def admin_segment_detail(segment_id):
    segment = query_one("SELECT * FROM segments WHERE segment_id = %s", (segment_id,))
    if not segment:
        abort(404)
    members = query_all(
        "SELECT u.user_id, u.name, u.email, sm.assigned_by, sm.created_at "
        "FROM segment_members sm JOIN users u ON u.user_id = sm.user_id "
        "WHERE sm.segment_id = %s ORDER BY u.name",
        (segment_id,),
    )
    picks = query_all(
        "SELECT sb.id, sb.ml_idx, sb.book_id, sb.note, sb.created_at, "
        "b.title AS library_title, b.author AS library_author, "
        "b.available_copies, b.total_copies "
        "FROM segment_books sb LEFT JOIN books b ON b.book_id = sb.book_id "
        "WHERE sb.segment_id = %s ORDER BY sb.id",
        (segment_id,),
    )
    recommender = get_recommender()
    picks_out = []
    for row in picks:
        item = dict(row)
        if not item["library_title"] and recommender.ok:
            catalog_item = recommender.get_item(item["ml_idx"])
            item["display_title"] = catalog_item["title"] if catalog_item else f"Catalog #{item['ml_idx']}"
            item["display_author"] = catalog_item["author"] if catalog_item else ""
        else:
            item["display_title"] = item["library_title"] or f"Catalog #{item['ml_idx']}"
            item["display_author"] = item["library_author"] or ""
        item["in_library"] = bool(item["book_id"])
        picks_out.append(item)

    candidates = []
    if recommender.ok:
        if segment["kind"] == "feedback" and segment["source_book_id"]:
            source = query_one(
                "SELECT ml_idx FROM books WHERE book_id = %s", (segment["source_book_id"],)
            )
            if source and source["ml_idx"] is not None:
                candidates = recommender.similar_books(source["ml_idx"], k=24)
        elif segment["kind"] == "ml" and segment["ml_cluster"] is not None:
            candidates = recommender.books_like_cluster(segment["ml_cluster"], k=24)
        else:
            candidates = recommender.recommend_for_user({}, k=24)
    existing = {int(row["ml_idx"]) for row in picks}
    candidates = [item for item in candidates if int(item["ml_idx"]) not in existing]
    candidate_in_library, candidate_suggested = _split_tiers(candidates, _library_map())

    source_title = None
    if segment["source_book_id"]:
        source_book = query_one(
            "SELECT title FROM books WHERE book_id = %s", (segment["source_book_id"],)
        )
        source_title = source_book["title"] if source_book else None

    return render_template(
        "admin_segment_detail.html",
        segment=segment,
        members=members,
        picks=picks_out,
        candidate_in_library=candidate_in_library,
        candidate_suggested=candidate_suggested,
        source_title=source_title,
    )


@recs_bp.post("/admin/segments/<int:segment_id>/recommend")
@admin_required
def admin_segment_recommend(segment_id):
    segment = query_one("SELECT * FROM segments WHERE segment_id = %s", (segment_id,))
    if not segment:
        abort(404)
    note = (request.form.get("note") or "").strip()[:255] or None
    recommender = get_recommender()
    saved = 0
    for raw in request.form.getlist("ml_idx"):
        ml_idx = _to_int(raw, -1)
        if ml_idx < 0 or (recommender.ok and ml_idx >= len(recommender.catalog)):
            continue
        book = query_one("SELECT book_id FROM books WHERE ml_idx = %s", (ml_idx,))
        execute(
            "INSERT INTO segment_books (segment_id, ml_idx, book_id, note, created_by) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE book_id = VALUES(book_id), note = VALUES(note)",
            (segment_id, ml_idx, book["book_id"] if book else None, note,
             session.get("admin_id")),
        )
        saved += 1
    flash(f"Saved {saved} recommendation(s) for this segment.", "ok")
    return redirect(url_for("recs.admin_segment_detail", segment_id=segment_id))


@recs_bp.post("/admin/segments/<int:segment_id>/picks/<int:pick_id>/remove")
@admin_required
def admin_segment_pick_remove(segment_id, pick_id):
    execute(
        "DELETE FROM segment_books WHERE id = %s AND segment_id = %s",
        (pick_id, segment_id),
    )
    flash("Recommendation removed.", "ok")
    return redirect(url_for("recs.admin_segment_detail", segment_id=segment_id))


@recs_bp.post("/admin/segments/<int:segment_id>/members/<int:user_id>/remove")
@admin_required
def admin_segment_member_remove(segment_id, user_id):
    segment = query_one("SELECT kind FROM segments WHERE segment_id = %s", (segment_id,))
    if not segment:
        abort(404)
    if segment["kind"] != "feedback":
        flash("Members can only be removed from feedback segments.", "error")
    else:
        execute(
            "DELETE FROM segment_members WHERE segment_id = %s AND user_id = %s",
            (segment_id, user_id),
        )
        flash("Member removed from segment.", "ok")
    return redirect(url_for("recs.admin_segment_detail", segment_id=segment_id))


# --------------------------------------------------------------- admin: user --
@recs_bp.get("/admin/users/<int:user_id>")
@admin_required
def admin_user(user_id):
    user = query_one("SELECT * FROM users WHERE user_id = %s", (user_id,))
    if not user:
        abort(404)
    ratings = query_all(
        "SELECT bf.rating, bf.comment, bf.updated_at, b.book_id, b.title "
        "FROM book_feedback bf JOIN books b ON b.book_id = bf.book_id "
        "WHERE bf.user_id = %s ORDER BY bf.updated_at DESC",
        (user_id,),
    )
    segments = query_all(
        "SELECT s.segment_id, s.name, s.kind, s.ml_cluster, s.sentiment, "
        "sm.assigned_by "
        "FROM segment_members sm JOIN segments s ON s.segment_id = sm.segment_id "
        "WHERE sm.user_id = %s ORDER BY s.kind, s.name",
        (user_id,),
    )
    dashboard = member_dashboard_data(user_id)
    return render_template(
        "admin_user.html",
        user=user,
        ratings=ratings,
        segments=segments,
        dashboard=dashboard,
    )


# ---------------------------------------------------------- admin dashboard --
def admin_dashboard_data():
    recommender = get_recommender()
    library = _library_map()
    seeds = query_all(
        "SELECT ml_idx, title FROM books WHERE ml_idx IS NOT NULL "
        "ORDER BY COALESCE(weighted_rating, 0) DESC, book_id DESC LIMIT 5"
    )
    seed_ratings = {int(row["ml_idx"]): 5 for row in seeds}
    if recommender.ok:
        recommendations = recommender.recommend_for_user(
            seed_ratings, k=16, exclude=set(seed_ratings)
        )
    else:
        recommendations = []
    in_library, consider = _split_tiers(recommendations, library)

    feedback_total = query_one(
        "SELECT COUNT(*) AS c, AVG(rating) AS a FROM book_feedback"
    ) or {"c": 0, "a": None}
    recent_ratings = query_all(
        "SELECT bf.rating, bf.comment, bf.updated_at, b.book_id, b.title, u.name "
        "FROM book_feedback bf "
        "JOIN books b ON b.book_id = bf.book_id "
        "JOIN users u ON u.user_id = bf.user_id "
        "ORDER BY bf.updated_at DESC LIMIT 5"
    )
    segment_counts = query_all(
        "SELECT s.segment_id, s.name, s.kind, s.ml_cluster, "
        "COUNT(sm.user_id) AS member_count "
        "FROM segments s LEFT JOIN segment_members sm ON sm.segment_id = s.segment_id "
        "GROUP BY s.segment_id, s.name, s.kind, s.ml_cluster "
        "ORDER BY s.kind ASC, s.ml_cluster ASC, s.name ASC"
    )
    return {
        "admin_recommendations_in_library": in_library,
        "admin_recommendations_consider": consider,
        "feedback_total": {
            "count": int(feedback_total["c"] or 0),
            "avg": round(float(feedback_total["a"]), 2)
            if feedback_total["a"] is not None
            else None,
        },
        "recent_ratings": recent_ratings,
        "segment_counts": segment_counts,
    }
