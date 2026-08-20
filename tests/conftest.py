"""Test fixtures for Spendly.

The one tricky bit: `app.py` calls init_db() and seed_db() at import time, so
the database has to be redirected *before* the app module is imported or the
suite would seed the developer's real expense_tracker.db.
"""

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import database.db as db  # noqa: E402

_TMP_DIR = tempfile.TemporaryDirectory()
db.DB_PATH = Path(_TMP_DIR.name) / "test.db"

import app as app_module  # noqa: E402  (imports last, on purpose)


@pytest.fixture(scope="session")
def flask_app():
    app_module.app.config["TESTING"] = True
    return app_module.app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def sign_in(client, user_id):
    """Put a user in the session without going through the login form."""
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


@pytest.fixture(scope="session")
def demo_user_id():
    """The user seed_db() created, with its eight expenses."""
    return db.get_user_by_email("demo@spendly.com")["id"]


@pytest.fixture(scope="session")
def other_user_id():
    """A second user with expenses of their own, for isolation checks."""
    user_id = db.create_user("Ayesha Khan", "ayesha@example.com", "x")
    conn = db.get_db()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO expenses (user_id, amount, category, date, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, 99999.0, "Shopping", "2026-01-05", "Ayesha private purchase"),
            )
    finally:
        conn.close()
    return user_id


@pytest.fixture(scope="session")
def empty_user_id():
    """A freshly registered user who has logged nothing yet."""
    return db.create_user("New Person", "new@example.com", "x")
