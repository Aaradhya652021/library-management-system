"""Shared session helpers and route decorators.

Kept in its own module so both app.py and the recs blueprint can use the
same role checks without importing the Flask app (and creating a cycle).
"""
from functools import wraps

from flask import flash, redirect, session, url_for


def is_admin():
    """Check if current session is admin."""
    return session.get("admin_id") is not None


def is_user():
    """Check if current session is a regular member."""
    return session.get("user_id") is not None


def login_required(view):
    """Allow any authenticated session (admin or member)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if is_admin() or is_user():
            return view(*args, **kwargs)
        if session.get("user_id"):
            return redirect(url_for("user_login"))
        return redirect(url_for("login"))
    return wrapped


def admin_required(view):
    """Admin-only route. Members are sent back to their dashboard."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if is_admin():
            return view(*args, **kwargs)
        if is_user():
            flash("Access denied. Administrator only.", "error")
            return redirect(url_for("index"))
        return redirect(url_for("login"))
    return wrapped


def member_required(view):
    """Member-only route. Admins are sent back to the admin dashboard."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if is_user() and not is_admin():
            return view(*args, **kwargs)
        if is_admin():
            flash("That page is for members. You are signed in as an admin.", "error")
            return redirect(url_for("index"))
        return redirect(url_for("user_login"))
    return wrapped
