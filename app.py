import os
import sqlite3
from functools import wraps

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import (
    create_user,
    get_db,
    get_user_by_email,
    get_user_by_id,
    init_db,
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


# ------------------------------------------------------------------ #
# Placeholder data for the profile page                               #
# ------------------------------------------------------------------ #

# Hardcoded on purpose: the layout is being agreed before any of it is wired
# to the expenses table. A later step swaps these three constants for queries
# and deletes this banner — the template does not change when that happens.
#
# The numbers are internally consistent and must stay that way: the rows below
# sum to PROFILE_SUMMARY["total_spent"], the per-category totals sum to the
# same figure, and "top_category" is the one appearing most often.

PROFILE_TRANSACTIONS = [
    {"date": "12 Apr 2025", "description": "Groceries", "category": "Food", "amount": "850.00"},
    {"date": "11 Apr 2025", "description": "Metro card recharge", "category": "Transport", "amount": "500.00"},
    {"date": "10 Apr 2025", "description": "Electricity bill", "category": "Bills", "amount": "2,200.00"},
    {"date": "09 Apr 2025", "description": "Doctor visit", "category": "Health", "amount": "800.00"},
    {"date": "08 Apr 2025", "description": "Netflix subscription", "category": "Entertainment", "amount": "649.00"},
    {"date": "07 Apr 2025", "description": "New shoes", "category": "Shopping", "amount": "3,200.00"},
    {"date": "05 Apr 2025", "description": "Dinner with friends", "category": "Food", "amount": "1,450.00"},
    {"date": "01 Apr 2025", "description": "Miscellaneous", "category": "Other", "amount": "2,801.75"},
]

# Placeholder too. The name and email are not here on purpose — those come
# from the signed-in user, so the card cannot contradict the navbar.
PROFILE_MEMBER_SINCE = "15 Jan 2025"

PROFILE_SUMMARY = {
    "total_spent": "12,450.75",
    "transaction_count": len(PROFILE_TRANSACTIONS),
    # Food, not Shopping: this is the category logged most often, which is the
    # one worth surfacing. Shopping is the single largest amount and already
    # sits at the top of the breakdown below.
    "top_category": "Food",
}

# Biggest first, the way the real GROUP BY will return them. `width` drives the
# bar and is the share of the largest category, not of the total — otherwise
# every bar sits in the left third and the comparison stops being readable.
PROFILE_BREAKDOWN = [
    {"category": "Shopping", "amount": "3,200.00", "width": 100},
    {"category": "Other", "amount": "2,801.75", "width": 88},
    {"category": "Food", "amount": "2,300.00", "width": 72},
    {"category": "Bills", "amount": "2,200.00", "width": 69},
    {"category": "Health", "amount": "800.00", "width": 25},
    {"category": "Entertainment", "amount": "649.00", "width": 20},
    {"category": "Transport", "amount": "500.00", "width": 16},
]


@app.route("/profile")
@login_required
def profile():
    # `user` reaches the template through the context processor; everything
    # with a rupee sign is still placeholder data.
    return render_template(
        "profile.html",
        member_since=PROFILE_MEMBER_SINCE,
        summary=PROFILE_SUMMARY,
        transactions=PROFILE_TRANSACTIONS,
        breakdown=PROFILE_BREAKDOWN,
    )


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
