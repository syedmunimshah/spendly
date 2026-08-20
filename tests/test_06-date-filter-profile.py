"""Step 6 -- the date-range filter on the profile page.

Based on `.claude/specs/06-date-filter-profile.md`. `GET /profile` gains two
optional query parameters, `date_from` and `date_to`, that narrow the summary
stats, recent-transactions list and category breakdown to a period. No new
routes are added and there are no writes, so "DB side effects" here means:
expenses planted directly in the database show up, or are correctly excluded,
depending on the requested range.

Behavioural model this file tests, read directly off the spec:

  * Both `date_from` and `date_to` must be present *and* well-formed
    (`YYYY-MM-DD`) for a filter to apply at all. The Overview section is
    explicit that if *either* parameter is absent or malformed, the route
    falls back to the unfiltered ("All Time") view -- and every UI element
    the Templates section describes (each preset link, the custom-range
    form) always supplies both parameters together, never one alone. So a
    single valid bound with the other missing or broken is *not* a
    half-open filter; it is a full fallback to unfiltered, silently, with no
    flash message.
  * When both bounds are present and well-formed and `date_from > date_to`,
    the route flashes "Start date must be before end date." and *also*
    falls back to unfiltered (both bounds dropped) -- this is the one
    fallback case that *does* flash a message.
  * `date_from == date_to` is a valid (not reversed) single-day range.
  * Bounds are inclusive at both ends.

The demo user seeded by `seed_db()` has all eight of its expenses spread
across the *current* calendar month by construction, which makes it useless
for proving a filter actually excludes something. Narrowing/boundary tests
therefore use a dedicated, function-scoped user created fresh per test (via
`create_user`, like `conftest.py`'s own `other_user_id` fixture does) so they
never depend on, or pollute, the session-scoped fixtures other test files
rely on.
"""

import re
import uuid
from datetime import date

import pytest
from flask import url_for

from conftest import sign_in
from database.db import create_user, get_db

RANGE_ERROR = "Start date must be before end date."


# ------------------------------------------------------------------ #
# Local helpers                                                       #
# ------------------------------------------------------------------ #

def insert_expense(user_id, amount, category, iso_date, description=""):
    """Plant one expense row directly, bypassing any route."""
    conn = get_db()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO expenses (user_id, amount, category, date, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, amount, category, iso_date, description),
            )
    finally:
        conn.close()


@pytest.fixture
def fresh_user_id():
    """A brand-new user, private to one test, with no seeded expenses."""
    email = "filter-{}@example.com".format(uuid.uuid4().hex)
    return create_user("Filter Tester", email, "x")


def seed_old_and_recent(user_id):
    """Plant one expense far in the past and one dated today.

    Used by the single-bound tests: a lone lower bound drops the 2015 one,
    a lone upper bound drops today's, and a genuinely unfiltered page shows
    both -- so each case is told apart by which of the two survives.
    """
    insert_expense(user_id, 111.0, "Shopping", "2015-06-15", "ancient expense")
    insert_expense(user_id, 222.0, "Food", date.today().isoformat(), "todays expense")


def find_preset_href(body, label):
    """Pull the href a preset link points at, out of the rendered page.

    Assumes a plain `<a href="...">Label</a>` per the spec's description of
    the preset buttons as simple labelled links.
    """
    pattern = r'<a\b[^>]*href="([^"]*)"[^>]*>\s*{}\s*</a>'.format(re.escape(label))
    match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
    assert match, "Could not find a preset link labelled {!r} in the rendered page".format(label)
    return match.group(1).replace("&amp;", "&")


def login_location(flask_app):
    with flask_app.test_request_context():
        return url_for("login")


# ------------------------------------------------------------------ #
# 1. No query params -- unfiltered, same as Step 5                    #
# ------------------------------------------------------------------ #

def test_no_query_params_shows_every_expense(client, fresh_user_id):
    seed_old_and_recent(fresh_user_id)
    sign_in(client, fresh_user_id)

    response = client.get("/profile")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "ancient expense" in body
    assert "todays expense" in body
    assert RANGE_ERROR not in body


# ------------------------------------------------------------------ #
# 2. Auth guard -- still enforced with query params present           #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize(
    "query",
    ["", "?date_from=2026-01-01&date_to=2026-01-31", "?date_from=not-a-date"],
)
def test_profile_redirects_to_login_when_signed_out(client, flask_app, query):
    response = client.get("/profile" + query)
    assert response.status_code == 302
    assert login_location(flask_app) in response.headers["Location"]


# ------------------------------------------------------------------ #
# 3. A valid custom range narrows the page                            #
# ------------------------------------------------------------------ #

def test_valid_custom_range_shows_only_expenses_inside_it(client, fresh_user_id):
    insert_expense(fresh_user_id, 100.0, "Food", "2024-05-10", "may expense")
    insert_expense(fresh_user_id, 200.0, "Transport", "2024-06-10", "june expense")
    insert_expense(fresh_user_id, 300.0, "Bills", "2024-07-10", "july expense")
    sign_in(client, fresh_user_id)

    response = client.get("/profile?date_from=2024-06-01&date_to=2024-06-30")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "june expense" in body
    assert "may expense" not in body
    assert "july expense" not in body
    # The June-only total is exactly the one expense in range.
    assert "200.00" in body
    assert RANGE_ERROR not in body


def test_valid_range_narrows_category_breakdown_too(client, fresh_user_id):
    insert_expense(fresh_user_id, 150.0, "Shopping", "2024-06-15", "in-range shopping")
    insert_expense(fresh_user_id, 500.0, "Health", "2024-01-01", "out-of-range health")
    sign_in(client, fresh_user_id)

    body = client.get("/profile?date_from=2024-06-01&date_to=2024-06-30").get_data(as_text=True)

    assert "Shopping" in body
    assert "Health" not in body


def test_range_from_equal_to_to_is_a_valid_single_day_filter(client, fresh_user_id):
    insert_expense(fresh_user_id, 50.0, "Food", "2024-03-15", "on the day")
    insert_expense(fresh_user_id, 75.0, "Food", "2024-03-14", "day before")
    insert_expense(fresh_user_id, 80.0, "Food", "2024-03-16", "day after")
    sign_in(client, fresh_user_id)

    body = client.get("/profile?date_from=2024-03-15&date_to=2024-03-15").get_data(as_text=True)

    assert "on the day" in body
    assert "day before" not in body
    assert "day after" not in body
    assert RANGE_ERROR not in body


# ------------------------------------------------------------------ #
# 4. Bounds are inclusive at both endpoints                           #
# ------------------------------------------------------------------ #

def test_range_bounds_are_inclusive_at_both_ends(client, fresh_user_id):
    insert_expense(fresh_user_id, 111.0, "Food", "2024-03-01", "start boundary")
    insert_expense(fresh_user_id, 222.0, "Food", "2024-03-31", "end boundary")
    insert_expense(fresh_user_id, 333.0, "Food", "2024-02-28", "just before start")
    insert_expense(fresh_user_id, 444.0, "Food", "2024-04-01", "just after end")
    sign_in(client, fresh_user_id)

    body = client.get("/profile?date_from=2024-03-01&date_to=2024-03-31").get_data(as_text=True)

    assert "start boundary" in body
    assert "end boundary" in body
    assert "just before start" not in body
    assert "just after end" not in body


# ------------------------------------------------------------------ #
# 5. Reversed range (date_from > date_to)                             #
# ------------------------------------------------------------------ #

def test_reversed_range_flashes_error_and_falls_back_to_unfiltered(client, fresh_user_id):
    seed_old_and_recent(fresh_user_id)
    sign_in(client, fresh_user_id)

    response = client.get("/profile?date_from=2026-06-01&date_to=2026-01-01")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert RANGE_ERROR in body
    # Fallback really is unfiltered -- both the old and the new expense show.
    assert "ancient expense" in body
    assert "todays expense" in body


# ------------------------------------------------------------------ #
# 6. A single bound is a valid half-open filter                       #
# ------------------------------------------------------------------ #
#
# Per the spec's Routes section, each bound is applied independently: an
# absent bound simply leaves that side unclamped. So date_from alone means
# "from that date onwards", and date_to alone means "up to that date".

def test_date_from_alone_filters_from_that_date_onwards(client, fresh_user_id):
    seed_old_and_recent(fresh_user_id)
    sign_in(client, fresh_user_id)

    # A lone lower bound of today clamps the start only: the 2015 expense
    # falls outside it, today's does not.
    body = client.get("/profile?date_from=" + date.today().isoformat()).get_data(as_text=True)

    assert "ancient expense" not in body
    assert "todays expense" in body
    assert RANGE_ERROR not in body


def test_date_to_alone_filters_up_to_that_date(client, fresh_user_id):
    seed_old_and_recent(fresh_user_id)
    sign_in(client, fresh_user_id)

    # A lone upper bound clamps the end only: today's expense falls outside
    # it, the 2015 one does not.
    body = client.get("/profile?date_to=2015-06-16").get_data(as_text=True)

    assert "ancient expense" in body
    assert "todays expense" not in body
    assert RANGE_ERROR not in body


# ------------------------------------------------------------------ #
# 7. Malformed dates fall back silently -- no crash, no flash          #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize(
    "query",
    [
        "date_from=not-a-date",
        "date_to=not-a-date",
        "date_from=not-a-date&date_to=also-not-a-date",
        "date_from=2026-13-40",
        "date_from=&date_to=",
    ],
)
def test_malformed_dates_fall_back_to_unfiltered_without_crashing(client, fresh_user_id, query):
    seed_old_and_recent(fresh_user_id)
    sign_in(client, fresh_user_id)

    response = client.get("/profile?{}".format(query))
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "ancient expense" in body
    assert "todays expense" in body
    # "Silently" per the spec -- a malformed date is not a reversed range.
    assert RANGE_ERROR not in body


def test_one_malformed_bound_leaves_the_valid_one_applied(client, fresh_user_id):
    """A broken date_from is discarded; the valid date_to still applies.

    A malformed value is treated exactly as an absent one, so this behaves
    like the lone-upper-bound case above rather than dropping the filter.
    """
    seed_old_and_recent(fresh_user_id)
    sign_in(client, fresh_user_id)

    body = client.get("/profile?date_from=not-a-date&date_to=2015-06-16").get_data(as_text=True)

    assert "ancient expense" in body
    assert "todays expense" not in body
    assert RANGE_ERROR not in body


# ------------------------------------------------------------------ #
# 8. The four presets                                                 #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("label", ["This Month", "Last 3 Months", "Last 6 Months"])
def test_preset_includes_todays_expense_and_excludes_a_years_old_one(client, fresh_user_id, label):
    seed_old_and_recent(fresh_user_id)
    sign_in(client, fresh_user_id)

    unfiltered_body = client.get("/profile").get_data(as_text=True)
    href = find_preset_href(unfiltered_body, label)

    body = client.get(href).get_data(as_text=True)
    assert "todays expense" in body
    assert "ancient expense" not in body


def test_all_time_preset_shows_every_expense_regardless_of_date(client, fresh_user_id):
    seed_old_and_recent(fresh_user_id)
    sign_in(client, fresh_user_id)

    body = client.get("/profile?date_from=2024-01-01&date_to=2024-01-02").get_data(as_text=True)
    href = find_preset_href(body, "All Time")

    all_time_body = client.get(href).get_data(as_text=True)
    assert "ancient expense" in all_time_body
    assert "todays expense" in all_time_body


def test_all_time_preset_link_carries_no_query_params(client, fresh_user_id):
    seed_old_and_recent(fresh_user_id)
    sign_in(client, fresh_user_id)

    body = client.get("/profile?date_from=2020-01-01&date_to=2020-01-02").get_data(as_text=True)
    href = find_preset_href(body, "All Time")

    assert "?" not in href, "All Time must be a clean /profile URL, got {!r}".format(href)


# ------------------------------------------------------------------ #
# 9. A range with nothing in it -- clean zero state, no errors        #
# ------------------------------------------------------------------ #

def test_range_with_no_matching_expenses_shows_a_zero_state(client, fresh_user_id):
    seed_old_and_recent(fresh_user_id)
    sign_in(client, fresh_user_id)

    response = client.get("/profile?date_from=1999-01-01&date_to=1999-01-02")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "₹0.00" in body
    assert "ancient expense" not in body
    assert "todays expense" not in body
    assert RANGE_ERROR not in body


def test_user_with_no_expenses_at_all_survives_any_filter(client, empty_user_id):
    sign_in(client, empty_user_id)

    response = client.get("/profile?date_from=2020-01-01&date_to=2020-12-31")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "₹0.00" in body
    assert RANGE_ERROR not in body


# ------------------------------------------------------------------ #
# 10. The rupee symbol survives an active filter                      #
# ------------------------------------------------------------------ #

def test_rupee_symbol_still_renders_with_a_filter_active(client, fresh_user_id):
    seed_old_and_recent(fresh_user_id)
    sign_in(client, fresh_user_id)

    body = client.get("/profile?date_from=2015-01-01&date_to=2015-12-31").get_data(as_text=True)
    assert "₹" in body


# ------------------------------------------------------------------ #
# 11. The active filter is visually reflected                         #
# ------------------------------------------------------------------ #

def test_custom_range_prefills_the_date_inputs_with_the_applied_values(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    body = client.get("/profile?date_from=2022-02-01&date_to=2022-02-28").get_data(as_text=True)

    assert 'value="2022-02-01"' in body
    assert 'value="2022-02-28"' in body


def test_unfiltered_page_does_not_prefill_a_stale_range(client, fresh_user_id):
    sign_in(client, fresh_user_id)

    body = client.get("/profile").get_data(as_text=True)

    assert 'value="2022-02-01"' not in body


# ------------------------------------------------------------------ #
# 12. User isolation holds with a filter active                       #
# ------------------------------------------------------------------ #

def test_date_filter_never_surfaces_another_users_expenses(client, demo_user_id, other_user_id):
    sign_in(client, demo_user_id)

    # A wide, valid window that comfortably covers Ayesha's 2026-01-05 expense.
    response = client.get("/profile?date_from=2020-01-01&date_to=2030-01-01")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Ayesha private purchase" not in body
    assert "99,999.00" not in body
