"""Step 7 — adding an expense through /expenses/add.

The behavioural model these tests hold the code to:

* Both verbs are behind login. A logged-out POST must not only redirect, it
  must not write anything.
* Validation is the server's job. maxlength, min and step are conveniences for
  whoever uses the form; every one of them is re-checked here against a raw
  POST that ignores them.
* A rejected submission re-renders at 200 with the typed values intact — it
  never redirects and never writes.
* What lands in the database is normalised, not whatever arrived: the date is
  zero-padded, the amount is rounded to two places, and a blank description
  becomes NULL rather than "".

There is no per-test database reset — conftest's temp DB lives for the whole
session — so any test that counts rows creates its own user first.
"""

import re
import uuid
from datetime import date

import pytest
from flask import url_for

from conftest import sign_in
from database.db import CATEGORIES, create_user, get_db, insert_expense


# ------------------------------------------------------------------ #
# Fixtures and helpers                                                #
# ------------------------------------------------------------------ #

@pytest.fixture
def fresh_user_id():
    """A user nobody else has touched, so row counts mean something."""
    return create_user("Expense Tester", "add-%s@example.com" % uuid.uuid4().hex, "x")


@pytest.fixture
def login_location(flask_app):
    with flask_app.test_request_context():
        return url_for("login")


@pytest.fixture
def profile_location(flask_app):
    with flask_app.test_request_context():
        return url_for("profile")


def valid_form(**overrides):
    """The happy-path payload, with individual fields swapped out per test."""
    form = {
        "amount": "50.0",
        "category": "Food",
        "date": "2026-03-20",
        "description": "Lunch",
    }
    form.update(overrides)
    return {k: v for k, v in form.items() if v is not None}


def rows_for(user_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM expenses WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
    finally:
        conn.close()


def form_error(body):
    """The rendered error text, or None. Asserts a message without pinning
    its exact wording, which is copy and free to change."""
    match = re.search(r'<div class="auth-error">\s*(.+?)\s*</div>', body, re.S)
    return match.group(1) if match else None


def select_options(body):
    """Every <option> value inside the category <select>, in page order."""
    block = re.search(r"<select[^>]*>(.*?)</select>", body, re.S)
    return re.findall(r'<option value="([^"]*)"', block.group(1)) if block else []


# ------------------------------------------------------------------ #
# 1. insert_expense                                                   #
# ------------------------------------------------------------------ #

def test_insert_expense_stores_every_field(fresh_user_id):
    new_id = insert_expense(fresh_user_id, 50.0, "Food", "2026-03-20", "Lunch")

    assert new_id, "insert_expense should return the new row id"
    row = rows_for(fresh_user_id)[0]
    assert row["id"] == new_id
    assert row["amount"] == pytest.approx(50.0)
    assert row["category"] == "Food"
    assert row["date"] == "2026-03-20"
    assert row["description"] == "Lunch"
    # Left out of the INSERT on purpose, so the column DEFAULT has to fill it.
    assert row["created_at"], "created_at should be populated by the DEFAULT"


def test_insert_expense_stores_an_explicit_none_description_as_null(fresh_user_id):
    insert_expense(fresh_user_id, 20.0, "Bills", "2026-03-21", None)

    assert rows_for(fresh_user_id)[0]["description"] is None


def test_insert_expense_defaults_description_to_null(fresh_user_id):
    insert_expense(fresh_user_id, 20.0, "Bills", "2026-03-21")

    assert rows_for(fresh_user_id)[0]["description"] is None


# ------------------------------------------------------------------ #
# 2. Auth guard                                                       #
# ------------------------------------------------------------------ #

def test_get_redirects_to_login_when_logged_out(client, login_location):
    response = client.get("/expenses/add")

    assert response.status_code == 302
    assert response.headers["Location"].endswith(login_location)


def test_post_redirects_to_login_and_writes_nothing_when_logged_out(
    client, fresh_user_id, login_location
):
    response = client.post("/expenses/add", data=valid_form())

    assert response.status_code == 302
    assert response.headers["Location"].endswith(login_location)
    # The redirect is the visible half; this is the half that matters.
    assert rows_for(fresh_user_id) == []


# ------------------------------------------------------------------ #
# 3. The form itself                                                  #
# ------------------------------------------------------------------ #

def test_form_renders_with_every_field(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    response = client.get("/expenses/add")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<form" in body
    assert 'method="POST"' in body
    for field in ("amount", "category", "date", "description"):
        assert 'name="%s"' % field in body, "missing the %s field" % field


def test_category_dropdown_lists_exactly_the_seven_categories(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    body = client.get("/expenses/add").get_data(as_text=True)

    # Compared against db.py's own tuple, so the test cannot drift from the
    # source of truth if a category is ever added.
    assert select_options(body) == list(CATEGORIES)


def test_date_field_defaults_to_today(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    body = client.get("/expenses/add").get_data(as_text=True)

    assert 'value="%s"' % date.today().isoformat() in body


# ------------------------------------------------------------------ #
# 4. Valid submissions                                                #
# ------------------------------------------------------------------ #

def test_valid_post_redirects_to_the_profile(client, fresh_user_id, profile_location):
    sign_in(client, fresh_user_id)

    response = client.post("/expenses/add", data=valid_form())

    assert response.status_code == 302
    assert response.headers["Location"].endswith(profile_location)


def test_valid_post_inserts_exactly_one_row(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    client.post("/expenses/add", data=valid_form())

    rows = rows_for(fresh_user_id)
    assert len(rows) == 1
    assert rows[0]["amount"] == pytest.approx(50.0)
    assert rows[0]["category"] == "Food"
    assert rows[0]["date"] == "2026-03-20"
    assert rows[0]["description"] == "Lunch"


def test_missing_description_is_stored_as_null(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    response = client.post("/expenses/add", data=valid_form(description=None))

    assert response.status_code == 302
    assert rows_for(fresh_user_id)[0]["description"] is None


def test_whitespace_only_description_is_stored_as_null(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    client.post("/expenses/add", data=valid_form(description="    "))

    # Stripping to "" then storing NULL keeps one representation of "nothing"
    # in the column instead of two.
    assert rows_for(fresh_user_id)[0]["description"] is None


def test_the_new_expense_appears_on_the_profile_page(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    client.post("/expenses/add", data=valid_form(description="Chai and samosa"))
    body = client.get("/profile").get_data(as_text=True)

    assert "Chai and samosa" in body


def test_a_short_date_is_zero_padded_before_storage(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    client.post("/expenses/add", data=valid_form(date="2026-3-20"))

    # strptime accepts the short form, but "2026-3-20" sorts after "2026-12-01"
    # as TEXT, which would drop the row out of the Step 6 date filter.
    assert rows_for(fresh_user_id)[0]["date"] == "2026-03-20"


def test_an_over_precise_amount_is_rounded_to_two_places(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    client.post("/expenses/add", data=valid_form(amount="50.999"))

    # Otherwise the summary total would not add up to the rows on screen.
    assert rows_for(fresh_user_id)[0]["amount"] == pytest.approx(51.0)


def test_the_expense_is_saved_against_the_session_user(
    client, fresh_user_id, other_user_id
):
    sign_in(client, fresh_user_id)
    before = len(rows_for(other_user_id))

    # A hand-rolled POST carrying someone else's id must be ignored — the
    # session is the only thing that decides ownership.
    client.post("/expenses/add", data=valid_form(user_id=str(other_user_id)))

    assert len(rows_for(fresh_user_id)) == 1
    assert len(rows_for(other_user_id)) == before


# ------------------------------------------------------------------ #
# 5. Rejected submissions                                             #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"amount": None}, id="amount-missing"),
        pytest.param({"amount": ""}, id="amount-blank"),
        pytest.param({"amount": "0"}, id="amount-zero"),
        pytest.param({"amount": "-5"}, id="amount-negative"),
        pytest.param({"amount": "abc"}, id="amount-not-a-number"),
        pytest.param({"amount": "nan"}, id="amount-nan"),
        pytest.param({"amount": "inf"}, id="amount-inf"),
        pytest.param({"category": "Crypto"}, id="category-unknown"),
        pytest.param({"category": ""}, id="category-blank"),
        pytest.param({"category": None}, id="category-missing"),
        pytest.param({"date": "not-a-date"}, id="date-garbage"),
        pytest.param({"date": "2026-13-45"}, id="date-impossible"),
        pytest.param({"date": ""}, id="date-blank"),
        pytest.param({"date": None}, id="date-missing"),
        pytest.param({"description": "x" * 201}, id="description-too-long"),
    ],
)
def test_invalid_submissions_are_rejected(client, fresh_user_id, overrides):
    sign_in(client, fresh_user_id)

    response = client.post("/expenses/add", data=valid_form(**overrides))
    body = response.get_data(as_text=True)

    assert response.status_code == 200, "a rejected submission re-renders, never redirects"
    assert form_error(body), "no error message was rendered"
    assert rows_for(fresh_user_id) == [], "a rejected submission must not write"


def test_a_rejected_submission_keeps_the_typed_values(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    body = client.post(
        "/expenses/add",
        data=valid_form(
            amount="123.45",
            category="Crypto",
            date="2026-03-20",
            description="Lunch with Ayesha",
        ),
    ).get_data(as_text=True)

    assert 'value="123.45"' in body
    assert 'value="2026-03-20"' in body
    assert "Lunch with Ayesha" in body


def test_a_valid_category_stays_selected_after_a_rejection(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    body = client.post(
        "/expenses/add", data=valid_form(amount="0", category="Transport")
    ).get_data(as_text=True)

    assert '<option value="Transport" selected>' in body
