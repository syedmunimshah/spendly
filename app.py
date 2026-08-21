import math
import os
import sqlite3
from datetime import date, datetime
from functools import wraps

from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import (
    CATEGORIES,
    create_user,
    delete_expense_row,
    get_category_totals_for_user,
    get_db,
    get_expense_for_user,
    get_expense_totals_for_user,
    get_expenses_for_user,
    get_monthly_totals_for_user,
    get_user_by_email,
    get_user_by_id,
    init_db,
    insert_expense,
    seed_db,
    update_expense_row,
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
            # Carried through so each row can link to its own edit page.
            "id": expense["id"],
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


# ------------------------------------------------------------------ #
# Analytics                                                           #
# ------------------------------------------------------------------ #

# Both charts are plain SVG built here and rendered as markup. The geometry
# is arithmetic, and arithmetic belongs in Python — Jinja would make a mess
# of it, and doing it server-side means the charts draw with JavaScript off.

# How many months the trend covers, including the current one.
TREND_MONTHS = 12

# Bar chart canvas. The plot sits inside these margins; the viewBox scales to
# whatever width the panel ends up being.
CHART_W = 720
CHART_H = 260
PLOT_LEFT = 52
PLOT_RIGHT = 704
PLOT_TOP = 16
PLOT_BOTTOM = 196

# Donut geometry. The radius and stroke together decide how thick the ring is.
DONUT_R = 70
DONUT_CIRCUMFERENCE = 2 * math.pi * DONUT_R


def _month_starts(today, months):
    """The first day of each of the last `months` months, oldest first."""
    starts = []
    for step in range(months - 1, -1, -1):
        index = today.month - 1 - step
        starts.append(date(today.year + index // 12, index % 12 + 1, 1))
    return starts


def _nice_ceiling(value):
    """Round a maximum up to something a gridline label can say out loud.

    2,847 becomes 3,000 rather than 2,847 — the axis is there to be read at a
    glance, and an axis that ends on the exact tallest bar tells you nothing
    the bar did not already.
    """
    if value <= 0:
        return 1
    magnitude = 10 ** (len(str(int(value))) - 1)
    return int(math.ceil(value / magnitude) * magnitude)


def build_trend(rows, today, months=TREND_MONTHS):
    """Bar geometry for the monthly trend, with empty months filled in.

    The query only returns months that had spending. Drawing straight from it
    would silently close the gaps and turn a three-month break into three
    adjacent bars, so the timeline is rebuilt here and the totals dropped in.
    """
    totals = {row["month"]: row["total"] for row in rows}
    starts = _month_starts(today, months)

    top = _nice_ceiling(max([totals.get(m.strftime("%Y-%m"), 0) for m in starts] or [0]))
    plot_h = PLOT_BOTTOM - PLOT_TOP
    slot = (PLOT_RIGHT - PLOT_LEFT) / months
    # A gap either side of each bar, so twelve bars read as twelve and not as
    # one solid block.
    width = slot * 0.62

    bars = []
    for i, start in enumerate(starts):
        amount = totals.get(start.strftime("%Y-%m"), 0)
        height = plot_h * amount / top
        bars.append(
            {
                "label": start.strftime("%b"),
                # Only January carries its year, which is enough to tell two
                # Januaries apart without repeating "2026" twelve times.
                "year": start.strftime("%Y") if start.month == 1 else "",
                "amount": format_rupees(amount),
                "empty": amount == 0,
                "x": PLOT_LEFT + slot * i + (slot - width) / 2,
                "y": PLOT_BOTTOM - height,
                "width": width,
                "height": height,
                "mid": PLOT_LEFT + slot * i + slot / 2,
            }
        )

    # Four gridlines plus the baseline, evenly spaced.
    lines = [
        {
            "y": PLOT_BOTTOM - plot_h * step / 4,
            "label": format_rupees(top * step / 4),
        }
        for step in range(5)
    ]

    return {"bars": bars, "lines": lines, "empty": top == 1 and not totals}


def build_donut(category_totals):
    """Ring segments for the category split, largest first.

    Each segment is the same circle with a different dash pattern: `dash` is
    how much of the circumference it covers, `offset` rotates it to start
    where the previous one ended. One shape, seven rotations — no arc paths
    and no trigonometry in the template.
    """
    total = sum(row["total"] for row in category_totals)
    if not total:
        return {"segments": [], "total": format_rupees(0), "empty": True}

    segments = []
    consumed = 0.0
    for row in category_totals:
        share = row["total"] / total
        segments.append(
            {
                "name": row["category"],
                "slug": row["category"].lower(),
                "amount": format_rupees(row["total"]),
                "percent": round(share * 100, 1),
                "dash": DONUT_CIRCUMFERENCE * share,
                "gap": DONUT_CIRCUMFERENCE * (1 - share),
                # Negative because SVG runs the dash offset backwards.
                "offset": -DONUT_CIRCUMFERENCE * consumed,
            }
        )
        consumed += share

    return {"segments": segments, "total": format_rupees(total), "empty": False}


@app.route("/analytics")
@login_required
def analytics():
    user = current_user()
    today = date.today()

    # Only the window the chart draws — a user with years of history should
    # not ship all of it across to render twelve bars.
    since = _month_starts(today, TREND_MONTHS)[0].isoformat()
    monthly = get_monthly_totals_for_user(user["id"], since=since)

    spent = sum(row["total"] for row in monthly)
    months_with_spending = [row for row in monthly if row["total"]]
    busiest = max(monthly, key=lambda row: row["total"], default=None)

    summary = {
        "spent": format_rupees(spent),
        # Averaged over the months that actually had spending, not over all
        # twelve — a brand-new account would otherwise look frugal rather
        # than empty.
        "monthly_average": format_rupees(
            spent / len(months_with_spending) if months_with_spending else 0
        ),
        "busiest_month": (
            datetime.strptime(busiest["month"], "%Y-%m").strftime("%B %Y")
            if busiest and busiest["total"]
            else EMPTY
        ),
        "busiest_amount": format_rupees(busiest["total"]) if busiest else format_rupees(0),
    }

    return render_template(
        "analytics.html",
        summary=summary,
        trend=build_trend(monthly, today),
        donut=build_donut(get_category_totals_for_user(user["id"], date_from=since)),
        months=TREND_MONTHS,
        donut_r=DONUT_R,
    )


def read_expense_form(form_data):
    """Pull the four expense fields off a submitted form, stripped.

    Add and edit post the same shape, so both read it through here rather
    than repeating four request.form.get() calls each.
    """
    return {
        "amount": form_data.get("amount", "").strip(),
        "category": form_data.get("category", "").strip(),
        "date": form_data.get("date", "").strip(),
        "description": form_data.get("description", "").strip(),
    }


def validate_expense_form(form):
    """Turn a raw expense form into stored values, or an error message.

    Returns (values, error): exactly one of the two is None. `values` is the
    dict insert_expense/update_expense want, already normalised.

    Every rule here is re-checked server-side even though the form carries
    min, step and maxlength — those constrain the browser, not a raw POST.
    """
    if not form["amount"]:
        return None, "Please enter an amount."

    try:
        amount = float(form["amount"])
    except ValueError:
        return None, "Amount must be a number."

    # float() happily returns nan and inf, and both would sail past the check
    # below — nan fails every comparison, inf passes them all — straight into
    # the REAL column. Neither is reachable through the form, only a raw POST.
    if not math.isfinite(amount):
        return None, "Amount must be a number."

    if amount <= 0:
        return None, "Amount must be greater than zero."

    if form["category"] not in CATEGORIES:
        return None, "Please choose a category."

    # Missing and malformed collapse into one message: the field is required
    # and must parse, and the user cannot act differently on the two.
    parsed_date = _parse_iso(form["date"])
    if parsed_date is None:
        return None, "Please enter a valid date."

    if len(form["description"]) > DESCRIPTION_MAX:
        return None, "Description must be {} characters or less.".format(
            DESCRIPTION_MAX
        )

    return {
        # Rounded so the stored figure matches what format_rupees prints —
        # otherwise the summary total would not reconcile with the rows.
        "amount": round(amount, 2),
        "category": form["category"],
        # isoformat(), not the raw string: strptime accepts "2026-3-20", which
        # sorts wrong as TEXT and would quietly fall outside the date filter.
        "date": parsed_date.isoformat(),
        "description": form["description"] or None,
    }, None


@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    today = date.today().isoformat()

    if request.method == "GET":
        return render_template(
            "add_expense.html", categories=CATEGORIES, today=today
        )

    # Whatever was typed comes back with the page, unparsed, so a rejected
    # submission looks exactly as the user left it.
    form = read_expense_form(request.form)
    values, error = validate_expense_form(form)

    if error:
        return render_template(
            "add_expense.html",
            error=error,
            form=form,
            categories=CATEGORIES,
            today=today,
        )

    insert_expense(
        session["user_id"],
        values["amount"],
        values["category"],
        values["date"],
        values["description"],
    )

    return redirect(url_for("profile"))


@app.route("/expenses/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    # Scoped to the signed-in user, so somebody else's id in the URL is a 404
    # rather than a peek at their spending. "Missing" and "not yours" are
    # deliberately the same answer.
    expense = get_expense_for_user(expense_id, session["user_id"])
    if expense is None:
        abort(404)

    if request.method == "GET":
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=CATEGORIES,
            form={
                "amount": "{:.2f}".format(expense["amount"]),
                "category": expense["category"],
                "date": expense["date"],
                "description": expense["description"] or "",
            },
        )

    form = read_expense_form(request.form)
    values, error = validate_expense_form(form)

    if error:
        return render_template(
            "edit_expense.html",
            error=error,
            expense=expense,
            form=form,
            categories=CATEGORIES,
        )

    update_expense_row(
        expense_id,
        session["user_id"],
        values["amount"],
        values["category"],
        values["date"],
        values["description"],
    )

    return redirect(url_for("profile"))


# POST only. A link or a GET here would let a crawler, a prefetching browser
# or an <img src> on someone else's page wipe a row just by being followed.
@app.route("/expenses/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete_expense(expense_id):
    if not delete_expense_row(expense_id, session["user_id"]):
        abort(404)

    return redirect(url_for("profile"))


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    app.run(debug=True, port=5001)
