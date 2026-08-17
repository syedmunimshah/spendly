import sqlite3

from flask import Flask, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from database.db import create_user, get_db, get_user_by_email, init_db, seed_db

app = Flask(__name__)

# Make sure the tables (and the demo data) exist before any route runs.
with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
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


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    return "Logout — coming in Step 3"


@app.route("/profile")
def profile():
    return "Profile page — coming in Step 4"


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
