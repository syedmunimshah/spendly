"""Steps 8 & 9 — editing and deleting an expense.

The behavioural model these tests hold the code to:

* Both edit and delete are behind login, same as add-expense — a logged-out
  request must not only redirect, it must not write anything.
* Ownership is the headline rule: an id that belongs to someone else must
  behave exactly like an id that does not exist. Both are a bare 404, on
  every verb (GET edit, POST edit, POST delete), and neither leaks a "yes
  but it's not yours" distinction.
* Edit validation is the same contract as add-expense (step 7), re-checked
  here because a raw POST can carry anything regardless of what the form's
  HTML attributes would have stopped in a browser.
* A rejected edit re-renders at 200 with the typed values intact — it never
  redirects and the stored row is left exactly as it was.
* Delete is POST-only: a GET must 405, not silently do nothing and not
  delete either — a link, a prefetch or an <img src> must never be able to
  remove a row.

There is no per-test database reset — conftest's temp DB lives for the whole
session — so any test that counts rows or asserts isolation creates its own
user first.
"""

import re
import uuid

import pytest
from flask import url_for

from conftest import sign_in
from database.db import CATEGORIES, create_user, get_db, insert_expense


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

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


def row_by_id(expense_id):
    """Fetch by id alone, no user filter — used to check a row survived (or
    didn't) regardless of who it belongs to."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
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


def description_value(body):
    """The value= attribute of the description input specifically."""
    match = re.search(r'name="description"[^>]*value="([^"]*)"', body)
    return match.group(1) if match else None


def edit_url(flask_app, expense_id):
    with flask_app.test_request_context():
        return url_for("edit_expense", expense_id=expense_id)


def delete_url(flask_app, expense_id):
    with flask_app.test_request_context():
        return url_for("delete_expense", expense_id=expense_id)


NONEXISTENT_ID = 999_999_999


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture
def fresh_user_id():
    """A user nobody else has touched, so row counts and edits mean something."""
    return create_user("Edit Tester", "edit-%s@example.com" % uuid.uuid4().hex, "x")


@pytest.fixture
def login_location(flask_app):
    with flask_app.test_request_context():
        return url_for("login")


@pytest.fixture
def profile_location(flask_app):
    with flask_app.test_request_context():
        return url_for("profile")


@pytest.fixture
def own_expense_id(fresh_user_id):
    """One expense belonging to fresh_user_id, with known original values —
    the baseline every "unchanged after a rejection/404" assertion compares
    against."""
    return insert_expense(fresh_user_id, 100.0, "Food", "2026-01-10", "Original lunch")


@pytest.fixture
def other_expense_id(other_user_id):
    """The expense conftest already seeded for other_user_id. Never targeted
    by a *successful* write in this file, so its values stay the ones
    conftest set: 99999.0 / Shopping / 2026-01-05 / "Ayesha private purchase"."""
    return rows_for(other_user_id)[0]["id"]


# ------------------------------------------------------------------ #
# 1. Auth guard                                                       #
# ------------------------------------------------------------------ #

def test_get_edit_redirects_to_login_when_logged_out(
    client, flask_app, own_expense_id, login_location
):
    response = client.get(edit_url(flask_app, own_expense_id))

    assert response.status_code == 302
    assert response.headers["Location"].endswith(login_location)


def test_post_edit_redirects_to_login_and_writes_nothing_when_logged_out(
    client, flask_app, own_expense_id, login_location
):
    before = row_by_id(own_expense_id)

    response = client.post(edit_url(flask_app, own_expense_id), data=valid_form())

    assert response.status_code == 302
    assert response.headers["Location"].endswith(login_location)
    after = row_by_id(own_expense_id)
    assert after["amount"] == before["amount"]
    assert after["category"] == before["category"]
    assert after["date"] == before["date"]
    assert after["description"] == before["description"]


def test_post_delete_redirects_to_login_and_deletes_nothing_when_logged_out(
    client, flask_app, own_expense_id, login_location
):
    response = client.post(delete_url(flask_app, own_expense_id))

    assert response.status_code == 302
    assert response.headers["Location"].endswith(login_location)
    assert row_by_id(own_expense_id) is not None, "the row must survive a logged-out delete"


# ------------------------------------------------------------------ #
# 2. Ownership — "missing" and "not yours" are the same 404            #
# ------------------------------------------------------------------ #

def test_get_edit_404s_for_a_nonexistent_id(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    response = client.get("/expenses/%d/edit" % NONEXISTENT_ID)

    assert response.status_code == 404


def test_get_edit_404s_for_someone_elses_expense(
    client, flask_app, fresh_user_id, other_expense_id
):
    sign_in(client, fresh_user_id)

    response = client.get(edit_url(flask_app, other_expense_id))

    assert response.status_code == 404


def test_post_edit_404s_for_a_nonexistent_id(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    response = client.post("/expenses/%d/edit" % NONEXISTENT_ID, data=valid_form())

    assert response.status_code == 404


def test_post_edit_404s_for_someone_elses_expense_and_leaves_it_untouched(
    client, flask_app, fresh_user_id, other_expense_id
):
    sign_in(client, fresh_user_id)
    before = row_by_id(other_expense_id)

    response = client.post(edit_url(flask_app, other_expense_id), data=valid_form())

    assert response.status_code == 404
    after = row_by_id(other_expense_id)
    assert after["amount"] == before["amount"]
    assert after["category"] == before["category"]
    assert after["date"] == before["date"]
    assert after["description"] == before["description"]


def test_post_delete_404s_for_a_nonexistent_id(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    response = client.post("/expenses/%d/delete" % NONEXISTENT_ID)

    assert response.status_code == 404


def test_post_delete_404s_for_someone_elses_expense_and_leaves_it_untouched(
    client, flask_app, fresh_user_id, other_expense_id
):
    sign_in(client, fresh_user_id)

    response = client.post(delete_url(flask_app, other_expense_id))

    assert response.status_code == 404
    assert row_by_id(other_expense_id) is not None, "someone else's row must survive"


# ------------------------------------------------------------------ #
# 3. The edit form, pre-filled                                        #
# ------------------------------------------------------------------ #

def test_edit_form_prefills_the_existing_values(
    client, flask_app, fresh_user_id, own_expense_id
):
    sign_in(client, fresh_user_id)

    response = client.get(edit_url(flask_app, own_expense_id))
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'value="100.00"' in body, "amount should be formatted to two decimals"
    assert '<option value="Food" selected>' in body
    assert 'value="2026-01-10"' in body
    assert "Original lunch" in body


def test_edit_form_shows_an_empty_description_when_the_stored_value_is_null(
    client, flask_app, fresh_user_id
):
    expense_id = insert_expense(fresh_user_id, 20.0, "Bills", "2026-02-01", None)
    sign_in(client, fresh_user_id)

    body = client.get(edit_url(flask_app, expense_id)).get_data(as_text=True)

    assert description_value(body) == ""


def test_edit_category_dropdown_lists_exactly_the_seven_categories(
    client, flask_app, fresh_user_id, own_expense_id
):
    sign_in(client, fresh_user_id)

    body = client.get(edit_url(flask_app, own_expense_id)).get_data(as_text=True)

    # Compared against db.py's own tuple, so the test cannot drift from the
    # source of truth if a category is ever added.
    assert select_options(body) == list(CATEGORIES)


def test_the_profile_row_carries_a_delete_form(
    client, flask_app, fresh_user_id, own_expense_id
):
    """Deleting is reachable from the list, not buried inside the edit page."""
    sign_in(client, fresh_user_id)

    body = client.get("/profile").get_data(as_text=True)

    assert delete_url(flask_app, own_expense_id) in body, (
        "each row should carry a form posting to the delete route"
    )
    # A form rather than an anchor: the route is POST only, so a link here
    # would be dead anyway — and a GET one could be fired by a prefetch.
    assert "<form" in body


def test_the_edit_page_does_not_repeat_the_delete_control(
    client, flask_app, fresh_user_id, own_expense_id
):
    """One place to delete from, so there is one habit to learn."""
    sign_in(client, fresh_user_id)

    body = client.get(edit_url(flask_app, own_expense_id)).get_data(as_text=True)

    assert delete_url(flask_app, own_expense_id) not in body


# ------------------------------------------------------------------ #
# 4. Valid submissions                                                #
# ------------------------------------------------------------------ #

def test_valid_edit_redirects_to_the_profile(
    client, flask_app, fresh_user_id, own_expense_id, profile_location
):
    sign_in(client, fresh_user_id)

    response = client.post(edit_url(flask_app, own_expense_id), data=valid_form())

    assert response.status_code == 302
    assert response.headers["Location"].endswith(profile_location)


def test_valid_edit_updates_the_stored_row(
    client, flask_app, fresh_user_id, own_expense_id
):
    sign_in(client, fresh_user_id)

    client.post(
        edit_url(flask_app, own_expense_id),
        data=valid_form(
            amount="75.5", category="Transport", date="2026-04-01", description="Bus fare"
        ),
    )

    row = row_by_id(own_expense_id)
    assert row["amount"] == pytest.approx(75.5)
    assert row["category"] == "Transport"
    assert row["date"] == "2026-04-01"
    assert row["description"] == "Bus fare"


def test_valid_edit_normalises_a_short_date(
    client, flask_app, fresh_user_id, own_expense_id
):
    sign_in(client, fresh_user_id)

    client.post(edit_url(flask_app, own_expense_id), data=valid_form(date="2026-3-20"))

    # strptime accepts the short form, but "2026-3-20" sorts wrong as TEXT and
    # would drop the row out of the step 6 date filter.
    assert row_by_id(own_expense_id)["date"] == "2026-03-20"


def test_valid_edit_rounds_an_over_precise_amount(
    client, flask_app, fresh_user_id, own_expense_id
):
    sign_in(client, fresh_user_id)

    client.post(edit_url(flask_app, own_expense_id), data=valid_form(amount="50.999"))

    assert row_by_id(own_expense_id)["amount"] == pytest.approx(51.0)


def test_valid_edit_stores_a_whitespace_only_description_as_null(
    client, flask_app, fresh_user_id, own_expense_id
):
    sign_in(client, fresh_user_id)

    client.post(edit_url(flask_app, own_expense_id), data=valid_form(description="   "))

    assert row_by_id(own_expense_id)["description"] is None


def test_valid_edit_stores_a_missing_description_as_null(
    client, flask_app, fresh_user_id, own_expense_id
):
    sign_in(client, fresh_user_id)

    client.post(edit_url(flask_app, own_expense_id), data=valid_form(description=None))

    assert row_by_id(own_expense_id)["description"] is None


def test_edit_ignores_a_smuggled_user_id_and_leaves_the_other_users_row_alone(
    client, flask_app, fresh_user_id, own_expense_id, other_user_id, other_expense_id
):
    sign_in(client, fresh_user_id)
    other_before = row_by_id(other_expense_id)

    # A hand-rolled POST carrying someone else's id must be ignored — the
    # session is the only thing that decides which row gets updated.
    response = client.post(
        edit_url(flask_app, own_expense_id),
        data=valid_form(user_id=str(other_user_id), description="Mine, not theirs"),
    )

    assert response.status_code == 302
    assert row_by_id(own_expense_id)["description"] == "Mine, not theirs"
    other_after = row_by_id(other_expense_id)
    assert other_after["amount"] == other_before["amount"]
    assert other_after["description"] == other_before["description"]


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
def test_invalid_edit_submissions_are_rejected(
    client, flask_app, fresh_user_id, own_expense_id, overrides
):
    sign_in(client, fresh_user_id)
    before = row_by_id(own_expense_id)

    response = client.post(edit_url(flask_app, own_expense_id), data=valid_form(**overrides))
    body = response.get_data(as_text=True)

    assert response.status_code == 200, "a rejected edit re-renders, never redirects"
    assert form_error(body), "no error message was rendered"
    after = row_by_id(own_expense_id)
    assert after["amount"] == before["amount"]
    assert after["category"] == before["category"]
    assert after["date"] == before["date"]
    assert after["description"] == before["description"]


def test_a_rejected_edit_keeps_the_typed_values(
    client, flask_app, fresh_user_id, own_expense_id
):
    sign_in(client, fresh_user_id)

    body = client.post(
        edit_url(flask_app, own_expense_id),
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


def test_a_valid_category_stays_selected_after_a_rejected_edit(
    client, flask_app, fresh_user_id, own_expense_id
):
    sign_in(client, fresh_user_id)

    body = client.post(
        edit_url(flask_app, own_expense_id),
        data=valid_form(amount="0", category="Transport"),
    ).get_data(as_text=True)

    assert '<option value="Transport" selected>' in body


# ------------------------------------------------------------------ #
# 6. Delete                                                           #
# ------------------------------------------------------------------ #

def test_valid_delete_redirects_to_the_profile(
    client, flask_app, fresh_user_id, own_expense_id, profile_location
):
    sign_in(client, fresh_user_id)

    response = client.post(delete_url(flask_app, own_expense_id))

    assert response.status_code == 302
    assert response.headers["Location"].endswith(profile_location)


def test_valid_delete_removes_the_row(client, flask_app, fresh_user_id, own_expense_id):
    sign_in(client, fresh_user_id)

    client.post(delete_url(flask_app, own_expense_id))

    assert row_by_id(own_expense_id) is None


def test_delete_does_not_touch_the_users_other_expenses(client, flask_app, fresh_user_id):
    sign_in(client, fresh_user_id)
    keep_id = insert_expense(fresh_user_id, 10.0, "Food", "2026-01-01", "Keep me")
    doomed_id = insert_expense(fresh_user_id, 20.0, "Bills", "2026-01-02", "Delete me")

    client.post(delete_url(flask_app, doomed_id))

    assert row_by_id(doomed_id) is None
    assert row_by_id(keep_id) is not None
    remaining = rows_for(fresh_user_id)
    assert len(remaining) == 1
    assert remaining[0]["id"] == keep_id


def test_a_second_delete_of_the_same_id_404s(client, flask_app, fresh_user_id, own_expense_id):
    sign_in(client, fresh_user_id)
    first = client.post(delete_url(flask_app, own_expense_id))
    assert first.status_code == 302, "the first delete should succeed"

    second = client.post(delete_url(flask_app, own_expense_id))

    assert second.status_code == 404


def test_a_get_to_the_delete_route_is_not_allowed(
    client, flask_app, fresh_user_id, own_expense_id
):
    sign_in(client, fresh_user_id)

    response = client.get(delete_url(flask_app, own_expense_id))

    assert response.status_code == 405
    assert row_by_id(own_expense_id) is not None, "a GET must not delete anything"


# ------------------------------------------------------------------ #
# 7. Profile page                                                     #
# ------------------------------------------------------------------ #

def test_profile_transaction_row_links_to_its_edit_page(
    client, flask_app, fresh_user_id, own_expense_id
):
    sign_in(client, fresh_user_id)

    body = client.get("/profile").get_data(as_text=True)

    assert edit_url(flask_app, own_expense_id) in body
