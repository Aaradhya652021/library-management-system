import os
import subprocess
import threading
import webbrowser
from datetime import date, timedelta
from decimal import Decimal

from flask_wtf import CSRFProtect
import mysql.connector
from flask import (Flask, flash, g, redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from auth_utils import (admin_required, is_admin, is_user, login_required,
                        member_required)
from db import get_connection

FINE_PER_DAY = Decimal("5.00")
LOAN_DAYS = 14

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

# Extra cookie hardening only while serving through the public HTTPS tunnel.
# Local HTTP use (python app.py) keeps working because the cookie stays non-Secure.
if os.getenv("PUBLIC_MODE") == "1":
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PREFERRED_URL_SCHEME="https",
    )

csrf = CSRFProtect(app)


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response



# ---------------------------------------------------------------- db helpers
def db():
    if "db" not in g:
        g.db = get_connection()
    return g.db
   

@app.teardown_appcontext
def close_db(exc):
    conn = g.pop("db", None)
    if conn is not None:
        try:
            conn.close()
        except mysql.connector.Error:
            pass


def query_all(sql, params=()):
    with db().cursor(dictionary=True) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def query_one(sql, params=()):
    with db().cursor(dictionary=True) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(sql, params=()):
    conn = db()
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------- login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin = query_one("SELECT * FROM admin WHERE username = %s", (username,))
        if admin and check_password_hash(admin["password_hash"], password):
            session["admin_id"] = admin["admin_id"]
            session["admin_name"] = admin["full_name"] or admin["username"]
            return redirect(url_for("index"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------- user login
@app.route("/user/login", methods=["GET", "POST"])
def user_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = query_one(
            "SELECT * FROM users WHERE name = %s OR email = %s", (username, username)
        )
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["user_id"]
            session["user_name"] = user["name"]
            return redirect(url_for("index"))
        flash("Invalid username or password.", "error")
    return render_template("user_login.html")


@app.post("/user/logout")
def user_logout():
    session.clear()
    return redirect(url_for("user_login"))


# --------------------------------------------------------------- user register
@app.route("/user/register", methods=["GET", "POST"])
def user_register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone_no", "").strip()
        password = request.form.get("password", "")
        if not name or not email or not password:
            flash("All fields are required.", "error")
            return redirect(url_for("user_register"))
        hashed = generate_password_hash(password)
        try:
            execute(
                "INSERT INTO users (name, email, phone_no, password_hash) VALUES (%s, %s, %s, %s)",
                (name, email, phone, hashed),
            )
            flash("Account created successfully. Please log in.", "ok")
            return redirect(url_for("user_login"))
        except mysql.connector.Error as err:
            if getattr(err, "errno", None) == 1062:
                flash("Email already exists.", "error")
            else:
                flash(f"Could not create account: {err.msg}", "error")
    return render_template("user_register.html")


# --------------------------------------------------------------- dashboard
@app.get("/")
@login_required
def index():
    if is_admin():
        stats = query_one(
            "SELECT COUNT(*) AS books, COALESCE(SUM(total_copies), 0) AS copies, "
            "COALESCE(SUM(available_copies), 0) AS available FROM books"
        )
        stats["members"] = query_one("SELECT COUNT(*) AS c FROM users")["c"]
        stats["issued"] = query_one(
            "SELECT COUNT(*) AS c FROM issues WHERE return_date IS NULL"
        )["c"]
        stats["overdue"] = query_one(
            "SELECT COUNT(*) AS c FROM issues "
            "WHERE return_date IS NULL AND due_date < CURDATE()"
        )["c"]

        recent = query_all(
            "SELECT i.issue_id, b.title, u.name AS member, i.issue_date, i.due_date, "
            "i.return_date FROM issues i "
            "JOIN books b ON b.book_id = i.book_id "
            "JOIN users u ON u.user_id = i.user_id "
            "ORDER BY i.issue_id DESC LIMIT 8"
        )
        from recs import admin_dashboard_data
        return render_template(
            "index.html", stats=stats, recent=recent, is_admin=True,
            **admin_dashboard_data(),
        )
    else:
        # User dashboard
        user_id = session.get("user_id")
        if not user_id:
            return redirect(url_for("user_login"))

        # Get user's issued books (not yet returned)
        issued = query_all(
            "SELECT i.*, b.title, b.author, i.issue_date, i.due_date "
            "FROM issues i "
            "JOIN books b ON b.book_id = i.book_id "
            "WHERE i.user_id = %s AND i.return_date IS NULL "
            "ORDER BY i.issue_date DESC",
            (user_id,)
        )

        # Get user's returned books with fines
        returned = query_all(
            "SELECT i.*, b.title, i.return_date, i.fine, "
            "GREATEST(DATEDIFF(CURDATE(), i.due_date), 0) as late_days "
            "FROM issues i "
            "JOIN books b ON b.book_id = i.book_id "
            "WHERE i.user_id = %s AND i.return_date IS NOT NULL "
            "ORDER BY i.return_date DESC",
            (user_id,)
        )

        # Get user's profile
        user = query_one("SELECT * FROM users WHERE user_id = %s", (user_id,))

        from recs import member_dashboard_data, member_feedback_context
        context = member_dashboard_data(user_id)
        book_ids = [row["book_id"] for row in issued + returned]
        context.update(member_feedback_context(user_id, book_ids))

        return render_template(
            "user_dashboard.html",
            user=user,
            issued=issued,
            returned=returned,
            FINE_PER_DAY=FINE_PER_DAY,
            is_admin=False,
            **context,
        )


# ------------------------------------------------------------------- books
@app.get("/books")
@admin_required
def books():
    rows = query_all("SELECT * FROM books ORDER BY title")
    stats_rows = query_all(
        "SELECT book_id, COUNT(*) AS count, AVG(rating) AS avg_rating "
        "FROM book_feedback GROUP BY book_id"
    )
    rating_stats = {
        row["book_id"]: {
            "count": int(row["count"]),
            "avg_rating": round(float(row["avg_rating"]), 2),
        }
        for row in stats_rows
    }
    return render_template("books.html", books=rows, rating_stats=rating_stats)


@app.route("/books/add", methods=["GET", "POST"])
@admin_required
def book_add():
    if request.method == "POST":
        form = request.form
        total = to_int(form.get("total_copies"), 1)
        raw_ml_idx = (form.get("ml_idx") or "").strip()
        ml_idx = to_int(raw_ml_idx) if raw_ml_idx else None
        if total < 0:
            flash("Total copies cannot be negative.", "error")
        else:
            if ml_idx is not None:
                clash = query_one(
                    "SELECT book_id FROM books WHERE ml_idx = %s", (ml_idx,)
                )
                if clash:
                    flash("That catalog title is already linked to another book.", "error")
                    ml_idx = None
            try:
                conn = db()
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO books (title, author, isbn, genre, total_copies, "
                        "available_copies, ml_idx) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (form.get("title", "").strip(),
                         form.get("author", "").strip(),
                         form.get("isbn", "").strip() or None,
                         form.get("genre", "").strip() or None,
                         total, total, ml_idx),
                    )
                    new_book_id = cur.lastrowid
                conn.commit()
                if ml_idx is None:
                    from recommender import get_recommender
                    get_recommender().match_single_book(new_book_id)
                flash("Book added.", "ok")
                return redirect(url_for("books"))
            except mysql.connector.Error as err:
                db().rollback()
                flash(f"Could not add book: {err.msg}", "error")
        prefill = {**request.form}
        prefill["ml_idx"] = raw_ml_idx
        return render_template("book_form.html", book=prefill, mode="add")
    prefill = {
        "title": request.args.get("title", ""),
        "author": request.args.get("author", ""),
        "isbn": request.args.get("isbn", ""),
        "genre": request.args.get("genre", ""),
        "ml_idx": request.args.get("ml_idx", ""),
    }
    return render_template("book_form.html", book=prefill, mode="add")


@app.route("/books/<int:book_id>/edit", methods=["GET", "POST"])
@admin_required
def book_edit(book_id):
    book = query_one("SELECT * FROM books WHERE book_id = %s", (book_id,))
    if not book:
        flash("Book not found.", "error")
        return redirect(url_for("books"))

    if request.method == "POST":
        form = request.form
        total = to_int(form.get("total_copies"), book["total_copies"])
        issued = book["total_copies"] - book["available_copies"]
        raw_ml_idx = form.get("ml_idx")
        if raw_ml_idx is None:
            ml_idx = book.get("ml_idx")
        else:
            raw_ml_idx = raw_ml_idx.strip()
            ml_idx = to_int(raw_ml_idx) if raw_ml_idx else None
        if ml_idx is not None and ml_idx != book.get("ml_idx"):
            clash = query_one(
                "SELECT book_id FROM books WHERE ml_idx = %s AND book_id <> %s",
                (ml_idx, book_id),
            )
            if clash:
                flash("That catalog title is already linked to another book.", "error")
                ml_idx = book.get("ml_idx")
        if total < issued:
            flash(f"Cannot set total below {issued} (copies currently issued).", "error")
        else:
            available = book["available_copies"] + (total - book["total_copies"])
            try:
                execute(
                    "UPDATE books SET title=%s, author=%s, isbn=%s, genre=%s, "
                    "total_copies=%s, available_copies=%s, ml_idx=%s WHERE book_id=%s",
                    (form.get("title", "").strip(),
                     form.get("author", "").strip(),
                     form.get("isbn", "").strip() or None,
                     form.get("genre", "").strip() or None,
                     total, available, ml_idx, book_id),
                )
                if ml_idx is None:
                    from recommender import get_recommender
                    get_recommender().match_single_book(book_id)
                flash("Book updated.", "ok")
                return redirect(url_for("books"))
            except mysql.connector.Error as err:
                flash(f"Could not update book: {err.msg}", "error")
        book = {**book, **request.form}
    return render_template("book_form.html", book=book, mode="edit")


@app.post("/books/<int:book_id>/delete")
@admin_required
def book_delete(book_id):
    try:
        execute("DELETE FROM books WHERE book_id = %s", (book_id,))
        flash("Book deleted.", "ok")
    except mysql.connector.Error:
        flash("Cannot delete: this book has issue records.", "error")
    return redirect(url_for("books"))


# ------------------------------------------------------------------- users
@app.get("/users")
@admin_required
def users():
    rows = query_all("SELECT * FROM users ORDER BY name")
    return render_template("users.html", users=rows)


@app.route("/users/add", methods=["GET", "POST"])
@admin_required
def user_add():
    if request.method == "POST":
        form = request.form
        try:
            execute(
                "INSERT INTO users (name, email, phone_no) VALUES (%s, %s, %s)",
                (form.get("name", "").strip(),
                 form.get("email", "").strip(),
                 form.get("phone_no", "").strip()),
            )
            flash("Member added.", "ok")
            return redirect(url_for("users"))
        except mysql.connector.Error as err:
            flash(f"Could not add member: {err.msg}", "error")
        return render_template("user_form.html", user=request.form, mode="add")
    return render_template("user_form.html", user={}, mode="add")


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id):
    user = query_one("SELECT * FROM users WHERE user_id = %s", (user_id,))
    if not user:
        flash("Member not found.", "error")
        return redirect(url_for("users"))

    if request.method == "POST":
        form = request.form
        try:
            execute(
                "UPDATE users SET name=%s, email=%s, phone_no=%s WHERE user_id=%s",
                (form.get("name", "").strip(),
                 form.get("email", "").strip(),
                 form.get("phone_no", "").strip(),
                 user_id),
            )
            flash("Member updated.", "ok")
            return redirect(url_for("users"))
        except mysql.connector.Error as err:
            flash(f"Could not update member: {err.msg}", "error")
        user = {**user, **request.form}
    return render_template("user_form.html", user=user, mode="edit")


@app.post("/users/<int:user_id>/delete")
@admin_required
def user_delete(user_id):
    # Check for unreturned (active) issues first
    active = query_one(
        "SELECT COUNT(*) AS c FROM issues WHERE user_id = %s AND return_date IS NULL",
        (user_id,),
    )
    if active and active["c"] > 0:
        flash(f"Cannot delete: member has {active['c']} unreturned book(s).", "error")
        return redirect(url_for("users"))
    # All books returned (or no issues): delete issue records first,
    # then the user (MySQL FK constraint allows it after child rows removed)
    try:
        execute("DELETE FROM issues WHERE user_id = %s", (user_id,))
        execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        flash("Member deleted.", "ok")
    except mysql.connector.Error:
        flash("Could not delete member.", "error")
    return redirect(url_for("users"))


# ------------------------------------------------------------------ issues
@app.get("/issues")
@login_required
def issues():
    if is_admin():
        rows = query_all(
            "SELECT i.*, b.title, u.name AS member FROM issues i "
            "JOIN books b ON b.book_id = i.book_id "
            "JOIN users u ON u.user_id = i.user_id "
            "ORDER BY i.issue_id DESC"
        )
        available_books = query_all(
            "SELECT book_id, title, available_copies FROM books "
            "WHERE available_copies > 0 ORDER BY title"
        )
        members = query_all("SELECT user_id, name FROM users ORDER BY name")
        default_due = date.today() + timedelta(days=LOAN_DAYS)
        return render_template(
            "issues.html", issues=rows, books=available_books, members=members,
            default_due=default_due.isoformat(), today=date.today().isoformat(),
            fine_per_day=FINE_PER_DAY,
        )
    else:
        # User: show only their own issues
        user_id = session.get("user_id")
        if not user_id:
            return redirect(url_for("user_login"))
        my_issues = query_all(
            "SELECT i.*, b.title FROM issues i "
            "JOIN books b ON b.book_id = i.book_id "
            "WHERE i.user_id = %s ORDER BY i.issue_id DESC",
            (user_id,)
        )
        from recs import member_feedback_context
        feedback = member_feedback_context(
            user_id, [row["book_id"] for row in my_issues]
        )
        return render_template(
            "user_issues.html", issues=my_issues, is_admin=False, **feedback
        )


@app.post("/issues/add")
@admin_required
def issue_add():
    book_id = to_int(request.form.get("book_id"))
    user_id = to_int(request.form.get("user_id"))
    due_raw = request.form.get("due_date", "")

    book = query_one("SELECT * FROM books WHERE book_id = %s", (book_id,))
    member = query_one("SELECT * FROM users WHERE user_id = %s", (user_id,))
    if not book or not member:
        flash("Pick a valid book and member.", "error")
        return redirect(url_for("issues"))
    if book["available_copies"] < 1:
        flash("That book has no copies available.", "error")
        return redirect(url_for("issues"))

    try:
        due_date = date.fromisoformat(due_raw)
    except ValueError:
        due_date = date.today() + timedelta(days=LOAN_DAYS)

    try:
        conn = db()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO issues (book_id, user_id, due_date, issued_by) "
                "VALUES (%s, %s, %s, %s)",
                (book_id, user_id, due_date.isoformat(), session["admin_id"]),
            )
            cur.execute(
                "UPDATE books SET available_copies = available_copies - 1 "
                "WHERE book_id = %s",
                (book_id,),
            )
        conn.commit()
        flash(f"'{book['title']}' issued to {member['name']}.", "ok")
    except mysql.connector.Error as err:
        db().rollback()
        flash(f"Could not issue book: {err.msg}", "error")
    return redirect(url_for("issues"))


@app.post("/issues/<int:issue_id>/return")
@login_required
def issue_return(issue_id):
    if is_admin():
        issue = query_one(
            "SELECT i.*, b.title FROM issues i JOIN books b ON b.book_id = i.book_id "
            "WHERE i.issue_id = %s",
            (issue_id,),
        )
        if not issue:
            flash("Issue record not found.", "error")
        elif issue["return_date"]:
            flash("This book was already returned.", "error")
        else:
            late_days = max((date.today() - issue["due_date"]).days, 0)
            fine = Decimal(late_days) * FINE_PER_DAY
            try:
                conn = db()
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE issues SET return_date = CURDATE(), fine = %s, "
                        "returned_by = %s WHERE issue_id = %s",
                        (fine, session["admin_id"], issue_id),
                    )
                    cur.execute(
                        "UPDATE books SET available_copies = "
                        "LEAST(available_copies + 1, total_copies) WHERE book_id = %s",
                        (issue["book_id"],),
                    )
                conn.commit()
                msg = f"'{issue['title']}' returned."
                if fine:
                    msg += f" Fine: {fine} ({late_days} day(s) late)."
                flash(msg, "ok")
            except mysql.connector.Error as err:
                db().rollback()
                flash(f"Could not return book: {err.msg}", "error")
        return redirect(url_for("issues"))
    else:
        # User: return their own issue
        user_id = session.get("user_id")
        if not user_id:
            return redirect(url_for("user_login"))
        issue = query_one(
            "SELECT i.*, b.title FROM issues i JOIN books b ON b.book_id = i.book_id "
            "WHERE i.issue_id = %s AND i.user_id = %s",
            (issue_id, user_id),
        )
        if not issue:
            flash("Issue record not found.", "error")
        elif issue["return_date"]:
            flash("This book was already returned.", "error")
        else:
            late_days = max((date.today() - issue["due_date"]).days, 0)
            fine = Decimal(late_days) * FINE_PER_DAY
            try:
                conn = db()
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE issues SET return_date = CURDATE(), fine = %s WHERE issue_id = %s",
                        (fine, issue_id),
                    )
                    cur.execute(
                        "UPDATE books SET available_copies = "
                        "LEAST(available_copies + 1, total_copies) WHERE book_id = %s",
                        (issue["book_id"],),
                    )
                conn.commit()
                flash(f"'{issue['title']}' returned. Fine: {fine} ({late_days} day(s) late).", "ok")
            except mysql.connector.Error as err:
                db().rollback()
                flash(f"Could not return book: {err.msg}", "error")
        return redirect(url_for("index"))


# --------------------------------------------------------- recommendation bp
from recs import recs_bp  # noqa: E402  (imported after app helpers exist)

app.register_blueprint(recs_bp)


def open_in_chrome(url="http://127.0.0.1:5000/"):
    """Open the app in Chrome, falling back to the default browser."""
    chrome_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in chrome_paths:
        if os.path.isfile(path):
            subprocess.Popen([path, url])
            return
    webbrowser.open(url)


if __name__ == "__main__":
    # Launch Chrome once the dev server is up. The reloader spawns a child
    # process, so only the parent should open the browser.
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Timer(1.5, open_in_chrome).start()
    app.run(debug=True)