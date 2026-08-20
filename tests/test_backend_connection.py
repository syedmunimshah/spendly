"""Step 5 — the profile page reads from the database."""

import pytest

import app as app_module
from conftest import sign_in
from database.db import (
    get_category_totals_for_user,
    get_expense_totals_for_user,
    get_expenses_for_user,
    get_user_by_id,
)

# The eight rows seed_db() inserts.
SEED_TOTAL = 13420.0
SEED_COUNT = 8
SEED_CATEGORIES = 7
SEED_TOP_CATEGORY = "Bills"  # 4,500 — the largest single-category total


# ------------------------------------------------------------------ #
# Query helpers                                                       #
# ------------------------------------------------------------------ #

def test_expenses_come_back_newest_first(demo_user_id):
    rows = get_expenses_for_user(demo_user_id)
    dates = [row["date"] for row in rows]
    assert len(rows) == SEED_COUNT
    assert dates == sorted(dates, reverse=True)


def test_expenses_respect_the_limit(demo_user_id):
    assert len(get_expenses_for_user(demo_user_id, limit=3)) == 3


def test_expenses_are_empty_for_a_new_user(empty_user_id):
    assert get_expenses_for_user(empty_user_id) == []


def test_totals_for_a_user_with_expenses(demo_user_id):
    totals = get_expense_totals_for_user(demo_user_id)
    assert totals["total"] == pytest.approx(SEED_TOTAL)
    assert totals["count"] == SEED_COUNT


def test_totals_are_zero_not_none_for_a_new_user(empty_user_id):
    totals = get_expense_totals_for_user(empty_user_id)
    assert totals["total"] == 0
    assert totals["count"] == 0


def test_category_totals_are_ordered_biggest_first(demo_user_id):
    rows = get_category_totals_for_user(demo_user_id)
    totals = [row["total"] for row in rows]
    assert len(rows) == SEED_CATEGORIES
    assert totals == sorted(totals, reverse=True)
    assert rows[0]["category"] == SEED_TOP_CATEGORY


def test_category_totals_are_empty_for_a_new_user(empty_user_id):
    assert get_category_totals_for_user(empty_user_id) == []


def test_queries_do_not_leak_between_users(demo_user_id, other_user_id):
    descriptions = [row["description"] for row in get_expenses_for_user(demo_user_id)]
    assert "Ayesha private purchase" not in descriptions


# ------------------------------------------------------------------ #
# Formatting                                                          #
# ------------------------------------------------------------------ #

def test_format_rupees_separates_thousands():
    assert app_module.format_rupees(13420.0) == "13,420.00"
    assert app_module.format_rupees(1234.5) == "1,234.50"


def test_format_rupees_handles_nothing():
    assert app_module.format_rupees(0) == "0.00"
    assert app_module.format_rupees(None) == "0.00"


def test_format_date_renders_a_display_date():
    assert app_module.format_date("2025-04-12") == "12 Apr 2025"


def test_format_member_since_reads_a_timestamp():
    assert app_module.format_member_since("2026-01-15 09:30:00") == "January 2026"


def test_formatters_fall_back_to_an_em_dash():
    assert app_module.format_date(None) == app_module.EMPTY
    assert app_module.format_member_since("not a date") == app_module.EMPTY


# ------------------------------------------------------------------ #
# Breakdown assembly                                                  #
# ------------------------------------------------------------------ #

def test_breakdown_bar_is_relative_to_the_largest(demo_user_id):
    rows = app_module.build_breakdown(get_category_totals_for_user(demo_user_id))
    assert rows[0]["width"] == 100
    assert all(0 <= row["width"] <= 100 for row in rows)


def test_breakdown_percentages_sum_to_one_hundred(demo_user_id):
    rows = app_module.build_breakdown(get_category_totals_for_user(demo_user_id))
    assert all(isinstance(row["pct"], int) for row in rows)
    assert sum(row["pct"] for row in rows) == 100


def test_breakdown_is_empty_without_expenses(empty_user_id):
    assert app_module.build_breakdown(get_category_totals_for_user(empty_user_id)) == []


# ------------------------------------------------------------------ #
# The /profile route                                                  #
# ------------------------------------------------------------------ #

def test_profile_redirects_when_signed_out(client):
    response = client.get("/profile")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_profile_shows_the_signed_in_users_own_details(client, demo_user_id):
    sign_in(client, demo_user_id)
    body = client.get("/profile").get_data(as_text=True)
    assert "Demo User" in body
    assert "demo@spendly.com" in body


def test_profile_shows_real_summary_figures(client, demo_user_id):
    sign_in(client, demo_user_id)
    response = client.get("/profile")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "₹" in body
    assert "13,420.00" in body
    assert SEED_TOP_CATEGORY in body


def test_profile_lists_every_seeded_expense_newest_first(client, demo_user_id):
    sign_in(client, demo_user_id)
    body = client.get("/profile").get_data(as_text=True)
    rows = [row["date"] for row in get_expenses_for_user(demo_user_id)]
    positions = [body.index(app_module.format_date(date)) for date in rows]
    assert body.count('class="txn-date"') == SEED_COUNT
    assert positions == sorted(positions)


def test_profile_breaks_down_every_category(client, demo_user_id):
    sign_in(client, demo_user_id)
    body = client.get("/profile").get_data(as_text=True)
    assert body.count('class="breakdown-row') == SEED_CATEGORIES


def test_profile_shows_member_since_from_the_user_row(client, demo_user_id):
    sign_in(client, demo_user_id)
    body = client.get("/profile").get_data(as_text=True)
    expected = app_module.format_member_since(get_user_by_id(demo_user_id)["created_at"])
    assert "Member since {}".format(expected) in body


def test_profile_survives_a_user_with_no_expenses(client, empty_user_id):
    sign_in(client, empty_user_id)
    response = client.get("/profile")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "₹0.00" in body
    assert "No expenses yet" in body
    assert "Nothing to break down yet." in body


def test_profile_never_shows_another_users_expenses(client, demo_user_id, other_user_id):
    sign_in(client, demo_user_id)
    body = client.get("/profile").get_data(as_text=True)
    assert "Ayesha private purchase" not in body
    assert "99,999.00" not in body
