# Spendly

A personal expense tracker built with Flask and SQLite. Log what you spend, group it by category, and see where the month actually went — amounts in rupees, no spreadsheet required.

<p align="left">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/Flask-3.1-000000?style=flat-square&logo=flask&logoColor=white" alt="Flask 3.1" />
  <img src="https://img.shields.io/badge/SQLite-raw_SQL-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/tests-52_passing-3B6D11?style=flat-square&logo=pytest&logoColor=white" alt="52 tests passing" />
</p>

---

## What it does

Spendly is a small, deliberately un-clever web app. You sign up, sign in, and get a profile page that answers one question: **where did my money go?**

- **Summary cards** — total spent, number of transactions, and the busiest category at a glance
- **Category breakdown** — spending split across Food, Transport, Bills, Health, Entertainment, Shopping and Other, each with its own colour
- **Recent transactions** — the latest ten entries, dated and categorised
- **Date filter** — one-click presets (This Month, Last 3 Months, Last 6 Months, All Time) or a custom range. The filter lives entirely in the query string, so any filtered view is a URL you can bookmark, share, and refresh
- **Session-based auth** — register, sign in, sign out, with hashed passwords and every query scoped to the signed-in user

Adding, editing and deleting expenses are the next steps in the build — those routes are present as labelled placeholders.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Web framework | **Flask 3.1** | Small enough to read end to end |
| Database | **SQLite** via raw `sqlite3` | No ORM — the SQL is visible and parameterised |
| Passwords | **Werkzeug** `generate_password_hash` | Never stores a plaintext password |
| Templates | **Jinja2** | Every page extends one `base.html` |
| Styling | **Hand-written CSS** | One stylesheet, design tokens in `:root`, no framework and no build step |
| Tests | **pytest** + **pytest-flask** | 52 tests against the Flask test client |

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

The SQLite file `expense_tracker.db` is created on first run and is gitignored, so your data stays local.

### Running the tests

```bash
python -m pytest
```

```bash
python -m pytest tests/test_06-date-filter-profile.py -v
```

---

## Project structure

```
app.py                  every route, plus the template filters and auth decorators
database/
  db.py                 get_db / init_db / seed_db and all SQL queries
templates/
  base.html             nav, footer, and the blocks every page fills
  landing.html          marketing page with the sign-up modal
  register.html         .
  login.html            .
  profile.html          summary cards, category breakdown, transactions, date filter
  analytics.html        placeholder for the charts still to come
  terms.html            .
  privacy.html          .
static/
  css/style.css         the whole stylesheet, design tokens at the top
  js/main.js            .
tests/                  pytest suite, one file per feature
```

### Data model

Two tables, with foreign keys enforced per connection:

```sql
users     (id, name, email UNIQUE, password_hash, created_at)
expenses  (id, user_id → users.id, amount, category, date, note)
```

---

## Notes on how it's built

A few decisions worth calling out, since they were deliberate rather than accidental:

- **Every query is parameterised.** User input never reaches SQL as text — dates from the query string are parsed into real `date` objects before they go anywhere near the database.
- **Filters live in the URL, not the session.** A filtered profile page is shareable and the browser's back button behaves the way it looks like it should.
- **Malformed input degrades quietly.** A broken date in the query string falls back to an unfiltered view instead of throwing a 500.
- **One stylesheet, tokens at the top.** Colours, fonts, radii and spacing are CSS custom properties in `:root`; page-specific CSS lives in that page's `{% block head %}` rather than bloating the shared sheet.

---

## Status

| Feature | State |
|---|---|
| Landing, terms, privacy | Done |
| Register / login / logout | Done |
| Profile page | Done |
| Date filter | Done |
| Analytics | Placeholder page |
| Add / edit / delete expense | Not yet built |

---

## Author

**Syed Abdul Munim Ali Shah** — [GitHub](https://github.com/syedmunimshah) · [Portfolio](https://abdulmunim.netlify.app/) · [LinkedIn](https://www.linkedin.com/in/syedabdulmunimalishah/)
