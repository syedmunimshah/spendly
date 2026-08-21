# Spendly

A personal expense tracker built with Flask and SQLite. Log what you spend, group it by category, and see where the month actually went — amounts in rupees, no spreadsheet required.

<p align="left">
  <a href="https://spendly-production-27a9.up.railway.app"><img src="https://img.shields.io/badge/live_demo-spendly.up.railway.app-1a472a?style=flat-square&logo=railway&logoColor=white" alt="Live demo" /></a>
</p>

<p align="left">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/Flask-3.1-000000?style=flat-square&logo=flask&logoColor=white" alt="Flask 3.1" />
  <img src="https://img.shields.io/badge/SQLite-raw_SQL-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/tests-156_passing-3B6D11?style=flat-square&logo=pytest&logoColor=white" alt="156 tests passing" />
</p>

---

## What it does

Spendly is a small, deliberately un-clever web app. You sign up, sign in, and get a profile page that answers one question: **where did my money go?**

- **Summary cards** — total spent, number of transactions, and the busiest category at a glance
- **Category breakdown** — spending split across Food, Transport, Bills, Health, Entertainment, Shopping and Other, each with its own colour
- **Recent transactions** — the latest ten entries, dated and categorised
- **Add, edit and delete** — a validated form for logging an expense, the same form for changing one, and a delete that only ever reaches your own rows
- **Analytics** — a twelve-month spending trend and a category ring, both plain SVG drawn on the server, so the charts render with JavaScript off
- **Date filter** — one-click presets (This Month, Last 3 Months, Last 6 Months, All Time) or a custom range. The filter lives entirely in the query string, so any filtered view is a URL you can bookmark, share, and refresh
- **Session-based auth** — register, sign in, sign out, with hashed passwords and every query scoped to the signed-in user

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Web framework | **Flask 3.1** | Small enough to read end to end |
| Database | **SQLite** via raw `sqlite3` | No ORM — the SQL is visible and parameterised |
| Passwords | **Werkzeug** `generate_password_hash` | Never stores a plaintext password |
| Templates | **Jinja2** | Every page extends one `base.html` |
| Styling | **Hand-written CSS** | One stylesheet, design tokens in `:root`, no framework and no build step |
| Tests | **pytest** + **pytest-flask** | 156 tests against the Flask test client |

No Node, no bundler, no ORM, no CSS framework. Four dependencies total.

---

## Getting started

```bash
git clone https://github.com/syedmunimshah/spendly.git
cd spendly

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
python app.py
```

The app runs on **http://127.0.0.1:5001** — port 5001, not Flask's default 5000.

The SQLite file `expense_tracker.db` is created on first run and is gitignored, so your data stays local. A demo user is seeded on first start.

### Running the tests

```bash
python -m pytest
```

```bash
python -m pytest tests/test_08-edit-delete-expense.py -v
```

---

## Project structure

```
app.py                  every route, plus the formatting helpers and auth decorators
database/
  db.py                 get_db / init_db / seed_db and all SQL queries
templates/
  base.html             nav, footer, and the blocks every page fills
  landing.html          marketing page with the sign-up modal
  register.html         .
  login.html            .
  profile.html          summary cards, category breakdown, transactions, date filter
  _expense_form.html    the shared expense fields, included by both forms below
  add_expense.html      logging a new expense
  edit_expense.html     changing one
  analytics.html        monthly trend and category charts, drawn as inline SVG
  terms.html            .
  privacy.html          .
static/
  css/style.css         the whole stylesheet, design tokens at the top
  js/main.js            .
tests/                  pytest suite, one file per feature
```

### Data model

Two tables, with foreign keys enforced on every connection:

```sql
users     (id, name, email UNIQUE, password_hash, created_at)
expenses  (id, user_id → users.id, amount, category, date, description, created_at)
```

---

## Notes on how it's built

A few decisions worth calling out, since they were deliberate rather than accidental:

- **Every query is parameterised.** User input never reaches SQL as text — dates from the query string are parsed into real `date` objects before they go anywhere near the database.
- **Ownership comes from the session, never the form.** A crafted POST carrying someone else's user id cannot file an expense against them, and there is a regression test for exactly that.
- **Ownership is enforced in the WHERE clause, not afterwards.** Every expense query carries `user_id`, so another user's id in the URL returns nothing rather than returning a row that then has to be checked. Missing and not-yours are the same 404.
- **Destructive actions are POST only.** A `GET` delete route can be fired by a crawler, a prefetching browser, or an `<img src>` on any page you happen to visit.
- **Dates are normalised before storage.** `strptime` accepts `2026-3-20`, which sorts wrong as TEXT and would silently fall outside the date filter, so what gets stored is always `isoformat()`.
- **Filters live in the URL, not the session.** A filtered profile page is shareable and the browser's back button behaves the way it looks like it should.
- **Malformed input degrades quietly.** A broken date in the query string falls back to an unfiltered view instead of throwing a 500.
- **One stylesheet, tokens at the top.** Colours, fonts, radii and spacing are CSS custom properties in `:root`; page-specific CSS lives in that page's `{% block head %}` rather than bloating the shared sheet.

---

## How it was built

Spendly is built **spec-first**, one feature at a time. Each step starts as a written spec describing the routes, validation rules, templates and acceptance criteria. Tests are generated from that spec rather than from the implementation, so they describe what the feature *should* do instead of restating what the code happens to do. Only then is the feature implemented against them.

Every change also goes through a security pass and a code-quality pass before it is merged.

---

## Status

| Feature | State |
|---|---|
| Landing, terms, privacy | Done |
| Register / login / logout | Done |
| Profile page | Done |
| Date filter | Done |
| Add expense | Done |
| Edit / delete expense | Done |
| Analytics | Done |

---

## Deployment

Live at **[spendly-production-27a9.up.railway.app](https://spendly-production-27a9.up.railway.app)**, running on Railway.

Three things the app needed before it could be hosted:

- **gunicorn** instead of Flask's own server, bound to `0.0.0.0:$PORT`. A container listening on localhost is unreachable from outside it. One worker on purpose — several processes writing to one SQLite file over a network volume is how you collect lock errors.
- **`SPENDLY_DB_PATH`**, so the database sits on a mounted volume at `/data`. A hosted container rebuilds its own directory on every deploy, so a file next to `app.py` would be wiped by each release.
- **`SPENDLY_SECRET_KEY`** set as a real secret. The code falls back to a development key so the dev server runs out of the box, and shipping that fallback would mean forgeable sessions.

---

## Author

**Syed Abdul Munim Ali Shah** — [GitHub](https://github.com/syedmunimshah) · [Portfolio](https://abdulmunim.netlify.app/) · [LinkedIn](https://www.linkedin.com/in/syedabdulmunimalishah/)
