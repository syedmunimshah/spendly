"""Data layer for Spendly — raw SQLite, no ORM.

Three functions make up the whole contract:
    get_db()   — a connection with dict-like rows and foreign keys on
    init_db()  — creates the tables (safe to call repeatedly)
    seed_db()  — inserts demo data once, for development
"""

import sqlite3
from datetime import date
from pathlib import Path

from werkzeug.security import generate_password_hash

# The database file lives at the project root, next to app.py. Resolving it
# from __file__ (rather than a relative path) means it lands in the same place
# no matter which directory the app was started from.
DB_PATH = Path(__file__).resolve().parent.parent / "expense_tracker.db"

# The fixed category list. Later steps (the add/edit expense forms) import this
# so the options stay in one place.
CATEGORIES = (
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
)


# ------------------------------------------------------------------ #
# Connection                                                          #
# ------------------------------------------------------------------ #

def get_db():
    """Open a connection to the database.

    row_factory makes rows behave like dicts (row["email"] instead of row[1]).
    SQLite disables foreign keys by default on *every* connection, so the
    PRAGMA has to be set here rather than once at table-creation time.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ------------------------------------------------------------------ #
# Schema                                                              #
# ------------------------------------------------------------------ #

def init_db():
    """Create the tables if they don't exist yet."""
    conn = get_db()
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT NOT NULL,
                    email         TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS expenses (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    amount      REAL NOT NULL,
                    category    TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    description TEXT,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Users                                                               #
# ------------------------------------------------------------------ #

def get_user_by_email(email):
    """Look up a single user by email, or None if there isn't one.

    The caller is responsible for normalising the address first — this stays a
    plain lookup so there is only one place (the register route) deciding what
    "the same email" means.
    """
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id):
    """Look up a single user by id, or None if there isn't one.

    Returning None rather than raising matters for sessions: a cookie can
    outlive the row it points at, and that should sign the visitor out quietly
    instead of erroring on every page.
    """
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()


def create_user(name, email, password_hash):
    """Insert one user and return the new id.

    Takes an already-hashed password on purpose: hashing at the call site keeps
    it obvious that no plaintext ever reaches the database layer. A duplicate
    email raises sqlite3.IntegrityError for the caller to handle.
    """
    conn = get_db()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, password_hash),
            )
            return cur.lastrowid
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Expenses                                                            #
# ------------------------------------------------------------------ #

# Every query here filters on user_id. That filter is the only thing keeping
# one person's spending off another person's page, so it is not optional on
# any expense query added later either.

def _date_clause(date_from, date_to):
    """Extra WHERE conditions for an optional date range, plus their params.

    Bounds are inclusive and independent — either can be None — so a half-open
    range still narrows instead of being silently ignored. Comparing the dates
    as strings is safe because `expenses.date` is ISO YYYY-MM-DD, which sorts
    in date order; the day the format changes, this breaks loudly.
    """
    sql = ""
    params = []
    if date_from:
        sql += " AND date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND date <= ?"
        params.append(date_to)
    return sql, params


def get_expenses_for_user(user_id, limit=None, date_from=None, date_to=None):
    """One user's expenses, newest first.

    The `id DESC` tiebreak matters because dates are stored to the day: two
    expenses logged on the same date would otherwise come back in whatever
    order SQLite felt like, and the list would reshuffle between page loads.
    """
    conn = get_db()
    try:
        date_sql, date_params = _date_clause(date_from, date_to)
        # The range narrows what user_id already selected — it is appended to
        # that condition, never in place of it.
        sql = "SELECT * FROM expenses WHERE user_id = ?" + date_sql
        sql += " ORDER BY date DESC, id DESC"
        params = [user_id] + date_params
        if limit is not None:
            # Bound, not formatted in — a LIMIT is still a value, and the habit
            # of interpolating "just a number" is how injections start.
            sql += " LIMIT ?"
            params.append(limit)
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def get_expense_totals_for_user(user_id, date_from=None, date_to=None):
    """A single row with the user's `total` spend and `count` of expenses.

    COALESCE is doing real work: SUM over no rows is NULL, not 0, so without it
    a freshly registered user — or one who picked a range with nothing in it —
    would reach the template with None as their total.
    """
    conn = get_db()
    try:
        date_sql, date_params = _date_clause(date_from, date_to)
        return conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total,
                   COUNT(*)                 AS count
            FROM expenses
            WHERE user_id = ?
            """
            + date_sql,
            [user_id] + date_params,
        ).fetchone()
    finally:
        conn.close()


def get_category_totals_for_user(user_id, date_from=None, date_to=None):
    """Per-category totals for one user, biggest first.

    Ordering here rather than in the caller keeps the "top category" and the
    breakdown list reading from the same source of truth — the first row is
    both the widest bar and the headline figure. A category with nothing inside
    the range drops out of the result entirely rather than showing a zero bar.
    """
    conn = get_db()
    try:
        date_sql, date_params = _date_clause(date_from, date_to)
        return conn.execute(
            """
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE user_id = ?
            """
            + date_sql
            + """
            GROUP BY category
            ORDER BY total DESC
            """,
            [user_id] + date_params,
        ).fetchall()
    finally:
        conn.close()


def get_monthly_totals_for_user(user_id, since=None):
    """One row per month the user spent anything in, oldest first.

    Grouping happens in SQLite rather than Python because the whole point is
    to avoid pulling every row across just to add them up — a user with years
    of history should still send twelve rows to the page.

    strftime works here only because `expenses.date` is ISO YYYY-MM-DD; the
    first six characters are the month, and they sort in date order. Months
    with no spending simply do not come back, so a caller drawing a timeline
    has to fill the gaps itself.
    """
    conn = get_db()
    try:
        sql = """
            SELECT strftime('%Y-%m', date) AS month,
                   SUM(amount) AS total,
                   COUNT(*) AS count
            FROM expenses
            WHERE user_id = ?
        """
        params = [user_id]
        if since:
            sql += " AND date >= ?"
            params.append(since)
        sql += " GROUP BY month ORDER BY month"
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def insert_expense(user_id, amount, category, date, description=None):
    """Store one expense and hand back its new id.

    Everything arriving here is already validated — the route owns that, the
    same split that has create_user() take an already-hashed password.

    `created_at` is deliberately absent from the column list so the table's
    own DEFAULT fills it in. `description` defaults to None rather than "" so
    a caller that simply omits it stores NULL.

    The `date` parameter shadows the module-level datetime.date import, which
    is harmless here: this body never needs it, and naming the parameter after
    its column keeps the call site readable.
    """
    conn = get_db()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO expenses (user_id, amount, category, date, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, amount, category, date, description),
            )
        return cur.lastrowid
    finally:
        conn.close()


def get_expense_for_user(expense_id, user_id):
    """One expense, but only if it belongs to this user — otherwise None.

    Both ids are in the WHERE clause on purpose. Fetching by id alone and
    comparing user_id afterwards would work too, but it puts the ownership
    check somewhere a caller can forget; here a row simply does not come back
    for somebody else's expense, and "missing" and "not yours" become the
    same answer. That also means an attacker cannot tell the two apart.
    """
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        ).fetchone()
    finally:
        conn.close()


def update_expense_row(expense_id, user_id, amount, category, date, description=None):
    """Overwrite one expense and report whether anything was actually changed.

    Returns the number of rows touched, so a caller can tell an edit that
    landed from one aimed at a row that is missing or belongs to somebody
    else. The user_id in the WHERE clause is what makes the second case
    impossible rather than merely unlikely.
    """
    conn = get_db()
    try:
        with conn:
            cur = conn.execute(
                """
                UPDATE expenses
                SET amount = ?, category = ?, date = ?, description = ?
                WHERE id = ? AND user_id = ?
                """,
                (amount, category, date, description, expense_id, user_id),
            )
        return cur.rowcount
    finally:
        conn.close()


def delete_expense_row(expense_id, user_id):
    """Remove one expense, returning how many rows went.

    Scoped by user_id for the same reason as update_expense_row: somebody else's
    id in the URL deletes nothing rather than deleting their row.
    """
    conn = get_db()
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM expenses WHERE id = ? AND user_id = ?",
                (expense_id, user_id),
            )
        return cur.rowcount
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Sample data                                                         #
# ------------------------------------------------------------------ #

def seed_db():
    """Insert a demo user and a handful of expenses — once.

    Called on every app start, so it returns early if anything is already
    there. Without that guard the debug reloader alone would double the data.
    """
    conn = get_db()
    try:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            return

        with conn:
            cur = conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                ("Demo User", "demo@spendly.com", generate_password_hash("demo123")),
            )
            user_id = cur.lastrowid

            # Spread the sample expenses across the current month so the demo
            # data never looks stale.
            def day(n):
                return date.today().replace(day=n).isoformat()

            conn.executemany(
                """
                INSERT INTO expenses (user_id, amount, category, date, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (user_id, 850.0, "Food", day(2), "Groceries from Imtiaz"),
                    (user_id, 1200.0, "Transport", day(4), "Careem rides this week"),
                    (user_id, 4500.0, "Bills", day(6), "Electricity bill"),
                    (user_id, 1650.0, "Health", day(9), "Pharmacy — monthly medicines"),
                    (user_id, 900.0, "Entertainment", day(12), "Cinema tickets"),
                    (user_id, 3200.0, "Shopping", day(15), "Winter jacket"),
                    (user_id, 500.0, "Other", day(18), "Gift for Ayesha"),
                    (user_id, 620.0, "Food", day(21), "Dinner at Student Biryani"),
                ],
            )
    finally:
        conn.close()
