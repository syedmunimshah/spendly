import math
import os
import sqlite3
from datetime import date, datetime
from functools import wraps

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import (
    CATEGORIES,
    create_user,
    get_category_totals_for_user,
    get_db,
    get_expense_totals_for_user,
    get_expenses_for_user,
    get_user_by_email,
    get_user_by_id,
    init_db,
    insert_expense,
    seed_db,
)

app = Flask(__name__)

# Signs the session cookie. The fallback keeps the dev server runnable out of
# the box — a real deployment must set SPENDLY_SECRET_KEY, or every restart
# would hand out forgeable sessions.
app.secret_key = os.environ.get("SPENDLY_SECRET_KEY", "dev-only-not-for-production")

# Where a successful sign-in lands. Kept as one constant so later steps can
# repoint it at the dashboard without touching the login route.
LOGIN_REDIRECT = "profile"

# A throwaway hash to check against when the email is unknown. Without it that
# path returns immediately while a wrong password pays for a real hash check,
# and the timing difference alone would reveal which emails are registered.
_DUMMY_HASH = generate_password_hash("not-a-real-password")

# Make sure the tables (and the demo data) exist before any route runs.
with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Authentication helpers                                              #
# ------------------------------------------------------------------ #

def current_user():
    """The signed-in user's row, or None if nobody is signed in.

    Only the id lives in the session — names and emails would go stale the
    moment a profile is edited, so the row is fetched fresh each time.
    """
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_user_by_id(user_id)


def login_required(view):
    """Send anonymous visitors to the sign-in page.

    wraps() is not decoration here: Flask keys its route table on the function
    name, so without it every protected view would register as "wrapper" and
    the second one would fail at import.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapper


def anonymous_only(view):
    """Keep signed-in visitors off the sign-in and sign-up pages.

    Rendering them again is confusing at best, and submitting one would swap
    the session out from under whoever is already signed in.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is not None:
            return redirect(url_for(LOGIN_REDIRECT))
        return view(*args, **kwargs)

    return wrapper


@app.context_processor
def inject_user():
    """Give every template a `user` variable for the navbar."""
    return {"user": current_user()}


# ------------------------------------------------------------------ #
# Formatting helpers                                                  #
# ------------------------------------------------------------------ #

# Presentation lives here, not in SQL and not in the template: the queries
# return numbers, the template prints strings, and this is the one seam where
# a rupee becomes "13,420.00".

# Shown wherever a value is missing — an em dash, not an empty cell, so the
# row still reads as a row.
EMPTY = "—"


def format_rupees(amount):
    """1234.5 -> "1,234.50". The template supplies the sign."""
    return "{:,.2f}".format(amount or 0)


def _parse_stored(value):
    """Parse what SQLite handed back, whether or not it carries a time.

    `expenses.date` is a bare date, `users.created_at` has a time appended by
    datetime('now'), and both arrive as plain strings.
    """
    text = str(value or "").strip()
    for length, fmt in ((19, "%Y-%m-%d %H:%M:%S"), (10, "%Y-%m-%d")):
        try:
            return datetime.strptime(text[:length], fmt)
        except ValueError:
            continue
    return None


def format_date(value):
    """ISO date -> "12 Apr 2025", or the em dash if it cannot be read."""
    parsed = _parse_stored(value)
    # Zero-padded, matching the dates the page was designed against — the day
    # column stays the same width down the table.
    return parsed.strftime("%d %b %Y") if parsed else EMPTY


def format_member_since(value):
    """users.created_at -> "January 2026"."""
    parsed = _parse_stored(value)
    return parsed.strftime("%B %Y") if parsed else EMPTY


# ------------------------------------------------------------------ #
# Date filter                                                         #
# ------------------------------------------------------------------ #

# The whole filter lives in the query string: `?date_from=...&date_to=...` on
# /profile. Nothing is kept in the session, so a filtered view is a URL you can
# bookmark, share and refresh, and the back button does what it looks like it
# does.

RANGE_ERROR = "Start date must be before end date."


def _parse_iso(value):
    """A query-string date -> date, or None if it is missing or malformed.

    Anything the user can type into a URL ends up here, so a bad value returns
    None for the caller to treat as "no bound" rather than raising a 500.
    """
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _months_back(today, months):
    """`months` calendar months before `today`, clamping the day.

    Stepping back from the 31st lands on months that have no 31st, so the day
    is pulled in to the end of the target month: 31 May minus 3 months is
    28 (or 29) February, not an error.
    """
    month_index = today.month - 1 - months
    year = today.year + month_index // 12
    month = month_index % 12 + 1

    # Walk the day down instead of computing month lengths — at most three
    # steps, and it needs no leap-year rule of its own.
    day = today.day
    while day > 1:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, 1)


def build_filters(today, date_from, date_to):
    """The preset links for the filter bar, with the active one marked.

    Every range is computed here rather than in the template: Jinja has no
    business doing calendar arithmetic, and the same numbers have to reach the
    queries anyway. "All time" deliberately carries no parameters so it lands
    back on a clean /profile.
    """
    presets = [
        ("This Month", today.replace(day=1), today),
        ("Last 3 Months", _months_back(today, 3), today),
        ("Last 6 Months", _months_back(today, 6), today),
        ("All Time", None, None),
    ]

    filters = []
    for label, start, end in presets:
        params = {}
        if start and end:
            params = {"date_from": start.isoformat(), "date_to": end.isoformat()}
        filters.append(
            {
                "label": label,
                "url": url_for("profile", **params),
                # A custom range matches no preset, and then nothing lights up
                # — the date inputs are already showing what is applied.
                "active": start == date_from and end == date_to,
            }
        )
    return filters


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
@anonymous_only
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    # Emails are matched case-insensitively, so store the normalised form and
    # compare against that. Passwords are never stripped — spaces are valid.
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    # Whatever the user typed comes back with the page, minus the password.
    form = {"name": name, "email": email}

    def fail(error):
        return render_template("register.html", error=error, form=form)

    if not name:
        return fail("Please enter your name.")

    # Deliberately loose: the only real proof of an address is a mail that
    # arrives, and a strict pattern here would reject valid addresses.
    at = email.find("@")
    if at < 1 or "." not in email[at:]:
        return fail("Please enter a valid email address.")

    if get_user_by_email(email) is not None:
        return fail("An account with that email already exists.")

    if len(password) < 8:
        return fail("Password must be at least 8 characters.")

    if password != confirm_password:
        return fail("Passwords do not match.")

    try:
        create_user(name, email, generate_password_hash(password))
    except sqlite3.IntegrityError:
        # Two submissions can clear the check above at the same time; the UNIQUE
        # constraint is what actually decides who gets the email.
        return fail("An account with that email already exists.")

    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
@anonymous_only
def login():
    if request.method == "GET":
        return render_template("login.html")

    # Same normalisation registration used when storing the address, or nobody
    # who typed a capital letter could ever sign in.
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    form = {"email": email}

    def fail(error):
        return render_template("login.html", error=error, form=form)

    if not email or not password:
        return fail("Please enter your email and password.")

    user = get_user_by_email(email)

    # One message for both failures, and a hash check on both paths. Saying
    # "no such account" would turn this form into a way to find out who has one.
    if user is None:
        check_password_hash(_DUMMY_HASH, password)
        return fail("Incorrect email or password.")

    if not check_password_hash(user["password_hash"], password):
        return fail("Incorrect email or password.")

    # Drop any existing session before granting the new one, so a value planted
    # before sign-in can't survive into the authenticated session.
    session.clear()
    session["user_id"] = user["id"]
    return redirect(url_for(LOGIN_REDIRECT))


@app.route("/logout")
def logout():
    # No login_required — signing out when already signed out should quietly
    # work, not bounce the visitor to a sign-in form.
    session.clear()
    return redirect(url_for("landing"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# How many rows the transactions panel shows. The summary cards and the
# breakdown deliberately cover everything — only the table is trimmed.
RECENT_LIMIT = 10

# Matches the maxlength on the description input. The browser enforces it for
# anyone using the form; this constant is what enforces it for anyone not.
DESCRIPTION_MAX = 200


def build_breakdown(category_totals):
    """Turn per-category totals into the rows the breakdown panel renders.

    Two different percentages come out of this, and they are not
    interchangeable. `width` drives the bar and is the share of the *largest*
    category, so the biggest one fills the track and the rest are readable
    against it. `pct` is the share of the total, rounded to whole numbers that
    add up to exactly 100 — the label, not the bar.
    """
    rows = [(row["category"], row["total"]) for row in category_totals]
    if not rows:
        return []

    largest = rows[0][1] or 0
    grand_total = sum(total for _, total in rows)

    breakdown = [
        {
            "category": category,
            "amount": format_rupees(total),
            # Guard the division: every amount could legitimately be 0.
            "width": round(total / largest * 100) if largest else 0,
            "pct": round(total / grand_total * 100) if grand_total else 0,
        }
        for category, total in rows
    ]

    # Rounding each share independently rarely lands on 100. The largest row
    # absorbs the difference because a point or two moves it least.
    breakdown[0]["pct"] += 100 - sum(row["pct"] for row in breakdown)

    return breakdown


@app.route("/profile")
@login_required
def profile():
    user = current_user()

    # Each bound is validated on its own: a typo in one should not throw away
    # the other, and neither should ever reach SQL unparsed.
    date_from = _parse_iso(request.args.get("date_from"))
    date_to = _parse_iso(request.args.get("date_to"))

    error = None
    if date_from and date_to and date_from > date_to:
        # A backwards range would quietly return nothing, which reads as "you
        # spent nothing" rather than "you asked for an impossible window".
        error = RANGE_ERROR
        date_from = date_to = None

    filters = build_filters(date.today(), date_from, date_to)

    # The queries take strings, in the same ISO form the column stores.
    start = date_from.isoformat() if date_from else None
    end = date_to.isoformat() if date_to else None

    totals = get_expense_totals_for_user(user["id"], date_from=start, date_to=end)
    category_totals = get_category_totals_for_user(
        user["id"], date_from=start, date_to=end
    )

    transactions = [
        {
            "date": format_date(expense["date"]),
            # A description is optional in the schema; the cell still needs
            # something in it.
            "description": (expense["description"] or "").strip() or EMPTY,
            "category": expense["category"],
            "amount": format_rupees(expense["amount"]),
        }
        for expense in get_expenses_for_user(
            user["id"], limit=RECENT_LIMIT, date_from=start, date_to=end
        )
    ]

    summary = {
        "total_spent": format_rupees(totals["total"]),
        "transaction_count": totals["count"],
        # The heaviest category, which is the first row by construction. A user
        # with nothing logged yet has no answer, and says so.
        "top_category": category_totals[0]["category"] if category_totals else EMPTY,
    }

    # `user` reaches the template through the context processor.
    return render_template(
        "profile.html",
        member_since=format_member_since(user["created_at"]),
        summary=summary,
        transactions=transactions,
        breakdown=build_breakdown(category_totals),
        filters=filters,
        # Empty strings, not None — these go straight into the date inputs, and
        # value="None" would show up as a stuck, unclearable value.
        date_from=start or "",
        date_to=end or "",
        error=error,
    )


@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    today = date.today().isoformat()

    if request.method == "GET":
        return render_template(
            "add_expense.html", categories=CATEGORIES, today=today
        )

    amount_raw = request.form.get("amount", "").strip()
    category = request.form.get("category", "").strip()
    date_raw = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip()

    # Whatever was typed comes back with the page, unparsed, so a rejected
    # submission looks exactly as the user left it.
    form = {
        "amount": amount_raw,
        "category": category,
        "date": date_raw,
        "description": description,
    }

    def fail(error):
        return render_template(
            "add_expense.html",
            error=error,
            form=form,
            categories=CATEGORIES,
            today=today,
        )

    if not amount_raw:
        return fail("Please enter an amount.")

    try:
        amount = float(amount_raw)
    except ValueError:
        return fail("Amount must be a number.")

    # float() happily returns nan and inf, and both would sail past the check
    # below — nan fails every comparison, inf passes them all — straight into
    # the REAL column. Neither is reachable through the form, only a raw POST.
    if not math.isfinite(amount):
        return fail("Amount must be a number.")

    if amount <= 0:
        return fail("Amount must be greater than zero.")

    if category not in CATEGORIES:
        return fail("Please choose a category.")

    # Missing and malformed collapse into one message: the field is required
    # and must parse, and the user cannot act differently on the two.
    parsed_date = _parse_iso(date_raw)
    if parsed_date is None:
        return fail("Please enter a valid date.")

    if len(description) > DESCRIPTION_MAX:
        return fail(
            "Description must be {} characters or less.".format(DESCRIPTION_MAX)
        )

    insert_expense(
        session["user_id"],
        # Rounded so the stored figure matches what format_rupees prints —
        # otherwise the summary total would not reconcile with the rows.
        round(amount, 2),
        category,
        # isoformat(), not date_raw: strptime accepts "2026-3-20", which sorts
        # wrong as TEXT and would quietly fall outside the Step 6 date filter.
        parsed_date.isoformat(),
        description or None,
    )

    return redirect(url_for("profile"))


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
