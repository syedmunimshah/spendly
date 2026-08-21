"""Step 9 — the analytics page and the two charts it draws.

The charts are plain SVG built server-side, so their geometry is testable
arithmetic rather than something only a browser can tell you about. That is
most of what this file checks:

* the trend covers a fixed twelve-month window with no gaps, even when the
  query returns only the months that had spending
* every bar stays inside the plot area, and the axis tops out somewhere a
  label can say out loud
* the donut's slices add up to exactly one full circle, and to 100%
* the page itself is behind login and scoped to the signed-in user

There is no per-test database reset — conftest's temp DB lives for the whole
session — so any test that depends on totals creates its own user.
"""

import re
import uuid
from datetime import date

import pytest
from flask import url_for

from app import (
    DONUT_CIRCUMFERENCE,
    PLOT_BOTTOM,
    PLOT_LEFT,
    PLOT_RIGHT,
    PLOT_TOP,
    TREND_MONTHS,
    _month_starts,
    _nice_ceiling,
    build_donut,
    build_trend,
)
from conftest import sign_in
from database.db import create_user, insert_expense


# ------------------------------------------------------------------ #
# Fixtures and helpers                                                #
# ------------------------------------------------------------------ #

@pytest.fixture
def fresh_user_id():
    """A user nobody else has touched, so totals mean something."""
    return create_user("Chart Reader", "chart-%s@example.com" % uuid.uuid4().hex, "x")


@pytest.fixture
def login_location(flask_app):
    with flask_app.test_request_context():
        return url_for("login")


def rows(*pairs):
    """Fake query output: (month, total) -> the row shape build_trend wants."""
    return [{"month": month, "total": total} for month, total in pairs]


def category_rows(*pairs):
    return [{"category": name, "total": total} for name, total in pairs]


# ------------------------------------------------------------------ #
# 1. _nice_ceiling — the axis top                                     #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 1),
        (1, 1),
        (47, 50),
        (2847, 3000),
        (13420, 20000),
        (100, 100),
    ],
)
def test_nice_ceiling_rounds_up_to_a_readable_number(value, expected):
    assert _nice_ceiling(value) == expected


def test_nice_ceiling_never_returns_zero():
    """A zero top would divide by zero when scaling the bars."""
    assert _nice_ceiling(0) > 0
    assert _nice_ceiling(-5) > 0


# ------------------------------------------------------------------ #
# 2. _month_starts — the timeline                                     #
# ------------------------------------------------------------------ #

def test_month_starts_returns_one_first_of_the_month_per_step():
    starts = _month_starts(date(2026, 8, 21), 12)

    assert len(starts) == 12
    assert all(d.day == 1 for d in starts)
    assert starts[-1] == date(2026, 8, 1), "the window ends on the current month"
    assert starts[0] == date(2025, 9, 1), "and starts eleven months earlier"


def test_month_starts_walks_back_across_a_year_boundary():
    starts = _month_starts(date(2026, 2, 10), 4)

    assert starts == [
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
    ]


# ------------------------------------------------------------------ #
# 3. build_trend — bar geometry                                       #
# ------------------------------------------------------------------ #

def test_trend_fills_in_months_that_had_no_spending():
    """The query only returns months with rows; a gap must stay a gap.

    Drawing straight from the query would put March and August side by side
    and hide the five quiet months between them.
    """
    trend = build_trend(rows(("2026-03", 500.0), ("2026-08", 1000.0)), date(2026, 8, 21))

    assert len(trend["bars"]) == TREND_MONTHS
    assert [b["empty"] for b in trend["bars"]].count(True) == 10
    assert [b["label"] for b in trend["bars"]][-1] == "Aug"


def test_trend_bars_stay_inside_the_plot_area():
    trend = build_trend(rows(("2026-08", 13420.0)), date(2026, 8, 21))

    for bar in trend["bars"]:
        assert bar["x"] >= PLOT_LEFT
        assert bar["x"] + bar["width"] <= PLOT_RIGHT
        assert bar["y"] >= PLOT_TOP
        assert bar["y"] + bar["height"] <= PLOT_BOTTOM + 0.001


def test_the_tallest_bar_reaches_the_axis_top_when_the_total_is_round():
    """13,420 rounds up to 20,000, so the bar should be just over two thirds."""
    trend = build_trend(rows(("2026-08", 13420.0)), date(2026, 8, 21))

    tallest = max(b["height"] for b in trend["bars"])
    plot_height = PLOT_BOTTOM - PLOT_TOP
    assert tallest == pytest.approx(plot_height * 13420 / 20000)


def test_only_january_carries_its_year():
    """Twelve repetitions of "2026" is noise; one is orientation."""
    trend = build_trend(rows(), date(2026, 8, 21))

    labelled = [b for b in trend["bars"] if b["year"]]
    assert len(labelled) == 1
    assert labelled[0]["label"] == "Jan"


def test_trend_gridlines_are_evenly_spaced_from_the_baseline_up():
    trend = build_trend(rows(("2026-08", 1000.0)), date(2026, 8, 21))

    ys = [line["y"] for line in trend["lines"]]
    assert len(ys) == 5
    assert ys[0] == PLOT_BOTTOM
    assert ys[-1] == PLOT_TOP
    gaps = [round(ys[i] - ys[i + 1], 6) for i in range(len(ys) - 1)]
    assert len(set(gaps)) == 1, "the gridlines should be evenly spaced"


def test_a_user_with_no_spending_still_gets_a_full_row_of_bars():
    trend = build_trend(rows(), date(2026, 8, 21))

    assert len(trend["bars"]) == TREND_MONTHS
    assert all(b["empty"] for b in trend["bars"])
    assert all(b["height"] == 0 for b in trend["bars"])


# ------------------------------------------------------------------ #
# 4. build_donut — ring geometry                                      #
# ------------------------------------------------------------------ #

def test_donut_slices_add_up_to_one_full_circle():
    donut = build_donut(category_rows(("Food", 300.0), ("Bills", 700.0)))

    assert sum(s["dash"] for s in donut["segments"]) == pytest.approx(DONUT_CIRCUMFERENCE)


def test_donut_percentages_add_up_to_a_hundred():
    donut = build_donut(
        category_rows(("Bills", 4500.0), ("Shopping", 3200.0), ("Food", 1520.0))
    )

    assert sum(s["percent"] for s in donut["segments"]) == pytest.approx(100.0, abs=0.2)


def test_each_slice_starts_where_the_previous_one_ended():
    """The offsets are what rotate each slice into place — they must be
    cumulative, and negative, because SVG runs dashoffset backwards."""
    donut = build_donut(
        category_rows(("Bills", 500.0), ("Food", 300.0), ("Other", 200.0))
    )

    offsets = [s["offset"] for s in donut["segments"]]
    assert offsets[0] == 0
    assert offsets == sorted(offsets, reverse=True), "offsets should only decrease"
    # The second slice starts exactly one first-slice-width around the ring.
    assert offsets[1] == pytest.approx(-donut["segments"][0]["dash"])


def test_a_single_category_fills_the_whole_ring():
    donut = build_donut(category_rows(("Food", 250.0)))

    only = donut["segments"][0]
    assert only["percent"] == 100.0
    assert only["dash"] == pytest.approx(DONUT_CIRCUMFERENCE)
    assert only["gap"] == pytest.approx(0)


def test_an_empty_donut_reports_itself_rather_than_dividing_by_zero():
    donut = build_donut([])

    assert donut["empty"] is True
    assert donut["segments"] == []


def test_the_slug_is_what_the_css_class_needs():
    """cat-{{ slug }} is how a slice picks up its category colour."""
    donut = build_donut(category_rows(("Entertainment", 100.0)))

    assert donut["segments"][0]["slug"] == "entertainment"


# ------------------------------------------------------------------ #
# 5. The page                                                         #
# ------------------------------------------------------------------ #

def test_analytics_redirects_to_login_when_logged_out(client, login_location):
    response = client.get("/analytics")

    assert response.status_code == 302
    assert response.headers["Location"].endswith(login_location)


def test_analytics_renders_both_charts(client, fresh_user_id):
    insert_expense(fresh_user_id, 500.0, "Food", date.today().isoformat(), "Lunch")
    sign_in(client, fresh_user_id)

    response = client.get("/analytics")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert body.count('class="chart-bar') == TREND_MONTHS
    assert "<circle" in body, "the donut should have drawn at least one slice"
    assert "legend-row" in body


def test_every_bar_has_a_title_for_screen_readers_and_hover(client, fresh_user_id):
    insert_expense(fresh_user_id, 500.0, "Food", date.today().isoformat(), "Lunch")
    sign_in(client, fresh_user_id)

    body = client.get("/analytics").get_data(as_text=True)

    # One <title> per bar, plus one per donut slice.
    assert body.count("<title>") >= TREND_MONTHS


def test_a_brand_new_user_sees_an_empty_state_not_a_crash(client, fresh_user_id):
    """No expenses at all is the first thing a new account hits."""
    sign_in(client, fresh_user_id)

    response = client.get("/analytics")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Nothing logged" in body
    # The class name also appears in the page's CSS, so match the element.
    assert "<circle" not in body


def test_the_monthly_average_counts_only_months_with_spending(client, fresh_user_id):
    """Averaging over all twelve would make a new account look frugal rather
    than empty."""
    today = date.today()
    insert_expense(fresh_user_id, 1000.0, "Food", today.isoformat(), "One")
    insert_expense(fresh_user_id, 3000.0, "Bills", today.isoformat(), "Two")
    sign_in(client, fresh_user_id)

    body = client.get("/analytics").get_data(as_text=True)
    values = re.findall(r'<p class="summary-value">(.*?)</p>', body)

    assert values[0] == "₹4,000.00", "total spent"
    assert values[1] == "₹4,000.00", "one month of spending, so the average is the total"


def test_analytics_never_counts_another_users_expenses(
    client, fresh_user_id, other_user_id
):
    sign_in(client, fresh_user_id)

    body = client.get("/analytics").get_data(as_text=True)

    # other_user_id's fixture plants a 99,999 Shopping expense.
    assert "99,999" not in body
