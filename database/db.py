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
