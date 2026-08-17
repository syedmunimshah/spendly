# Spec: Registration

## Overview

Turn `/register` from a render-only page into a working sign-up flow. The
template, the form markup and the `{% if error %}` block already exist — what is
missing is the server side: accept the POST, validate the three fields, reject
duplicate emails, hash the password with werkzeug and insert a row into the
`users` table built in Step 1. This is the first step that writes user data, so
it is the point where the app stops being a static brochure and starts having
accounts. Login and sessions arrive in Step 3, so a successful registration ends
by redirecting to `/login`, not by signing the user in.

---

## Depends on

- **Step 1 — Database setup.** Requires `get_db()` and the `users` table
  (`name`, `email` UNIQUE, `password_hash`, `created_at`) already implemented in
  `database/db.py`.

No other steps are required. Nothing here depends on sessions, which land in
Step 3.

---

## Routes

- `GET /register` — render the empty sign-up form — public
- `POST /register` — validate and create the account, then redirect to
  `/login` — public

No new URL paths. The existing `register()` function gains
`methods=["GET", "POST"]`; the template already posts to `/register`.

---

## Database changes

No database changes. The `users` table from Step 1 already has every column this
feature writes, and the `UNIQUE` constraint on `email` is the backstop for
duplicate sign-ups.

One new helper is added to `database/db.py` rather than putting SQL in `app.py`:

- `create_user(name, email, password_hash)` — inserts one row, returns the new
  `id`
- `get_user_by_email(email)` — returns the row or `None`, used for the duplicate
  check

Both use parameterised queries and follow the existing `conn = get_db()` /
`try` / `finally: conn.close()` shape in that file.

---

## Templates

- **Create:** none — `templates/register.html` already exists and already
  renders `{{ error }}`.
- **Modify:** `templates/register.html` — repopulate `name` and `email` from a
  `form` variable after a failed submit (`value="{{ form.name or '' }}"`) so a
  validation error does not wipe what the user typed. The password field is
  never repopulated. Change the hardcoded `action="/register"` to
  `url_for('register')` to match the convention used elsewhere.

---

## Files to change

- `app.py` — `register()` accepts POST; import `redirect`, `url_for`, `request`
  and the new db helpers
- `database/db.py` — add `create_user()` and `get_user_by_email()` under a new
  `Users` comment banner
- `templates/register.html` — sticky form values, `url_for` in the action
- `static/css/style.css` — only if `.auth-error` is not already styled; add it
  in the existing auth section using `--accent-2` / `--paper*` tokens

---

## Files to create

- None.

---

## New dependencies

No new dependencies. `werkzeug.security` ships with Flask and is already
imported in `database/db.py`.

---

## Rules for implementation

- No SQLAlchemy or ORMs — raw `sqlite3` through `get_db()` only
- Parameterised queries only; never f-strings or `%` formatting in SQL
- Passwords hashed with `werkzeug.security.generate_password_hash` — never store
  or log the plaintext
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Keep SQL in `database/db.py`; `app.py` calls helpers, it does not open cursors
- Validation happens server-side even though the inputs are `required` — the
  HTML attribute is a convenience, not a control
- Strip whitespace and lowercase the email before checking and storing it
- Re-render `register.html` with `error` on failure (HTTP 200, same as the
  existing pattern); redirect only on success
- One error message shown at a time, in the order the fields appear
- Catch `sqlite3.IntegrityError` around the insert as well as doing the
  pre-check — two simultaneous submits can both pass the check
- Do not set `session[...]` or add a `secret_key` — that belongs to Step 3
- Copy stays Pakistan/India-oriented, matching the existing placeholder names

### Validation rules

| Field | Rule | Message |
| --- | --- | --- |
| name | required, non-blank after strip | "Please enter your name." |
| email | required, contains `@` and a `.` after it | "Please enter a valid email address." |
| email | not already registered | "An account with that email already exists." |
| password | at least 8 characters | "Password must be at least 8 characters." |

---

## Definition of done

- [ ] `GET /register` still renders the form exactly as before
- [ ] Submitting a valid new name/email/password redirects to `/login`
- [ ] The new row appears in `users` with a hashed `password_hash` — verified
      with `venv/Scripts/python.exe -c "..."` or a SQLite browser; the value
      starts with `pbkdf2:` or `scrypt:` and is never the plaintext
- [ ] Registering `demo@spendly.com` (the seeded user) re-renders the form with
      "An account with that email already exists." and creates no row
- [ ] `DEMO@Spendly.com ` (different case, trailing space) is also rejected as a
      duplicate
- [ ] A blank name, a malformed email, and a 7-character password each
      re-render the form with the matching message
- [ ] After any failed submit the name and email fields still hold what was
      typed and the password field is empty
- [ ] No route or template outside registration changed behaviour — `/login`,
      `/terms`, `/privacy` and the landing page still load
- [ ] App starts clean on port 5001 with no errors on repeated restarts
