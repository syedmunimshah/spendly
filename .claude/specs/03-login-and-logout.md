# Spec: Login and Logout

## Overview

Give the accounts created in Step 2 somewhere to go. Right now a successful
registration redirects to `/login`, and submitting that form returns
405 Method Not Allowed — the route is GET-only and there is no session anywhere
in the app. This step adds the other half: verify an email and password against
the stored hash, put the user's id in a signed session cookie, and clear it
again on logout. It also introduces the `@login_required` decorator and makes
the navbar reflect who is signed in, which every later step (profile, the
expense CRUD) depends on to know whose rows to show.

---

## Depends on

- **Step 1 — Database setup.** `get_db()` and the `users` table.
- **Step 2 — Registration.** `create_user()` and `get_user_by_email()` already
  exist in `database/db.py`; this step reuses the lookup rather than writing a
  second one, and relies on registration having stored a werkzeug hash.

---

## Routes

- `GET /login` — render the sign-in form — public
- `POST /login` — verify credentials, set the session, redirect — public
- `GET /logout` — clear the session and redirect to the landing page — logged-in
- `GET /profile` — stays a placeholder string, but gains `@login_required` so
  the decorator is exercised by something real — logged-in

No new URL paths. `/login` gains `methods=["GET", "POST"]`; `/logout` moves out
of the placeholder block into the implemented block.

### Where login redirects to

There is no dashboard route yet — the roadmap puts profile at Step 4 and the
expense list later. Login redirects to `url_for("profile")`, the only
logged-in destination that exists. Because that is a placeholder returning a
plain string, the redirect target is defined once as a module-level constant so
Step 4 or Step 6 can repoint it in one edit instead of hunting through routes.

Supporting a `?next=` parameter is **out of scope** — it needs open-redirect
validation and nothing yet links to a protected page.

---

## Database changes

No database changes. `users` already stores everything login needs
(`email` UNIQUE, `password_hash`), and sessions live in the client cookie, not
in a table.

One new read helper in `database/db.py`, alongside the Step 2 pair:

- `get_user_by_id(user_id)` — returns the row or `None`, used by
  `current_user()` to turn `session["user_id"]` back into a user

---

## Templates

- **Create:** none.
- **Modify:**
  - `templates/login.html` — `action="/login"` becomes
    `url_for('login')`; the email field repopulates from `form.email` after a
    failed attempt (password never does). The `{% if error %}` block already
    exists and needs no change.
  - `templates/base.html` — the navbar's "Sign in" / "Get started" pair is
    wrapped in `{% if session.user_id %}`. Signed in, it shows the user's name
    linking to `/profile` and a "Sign out" link to `/logout`; signed out, it
    stays exactly as it is today. Flask exposes `session` to Jinja
    automatically, so no context processor is needed.

---

## Files to change

- `app.py` — `secret_key`; `login()` accepts POST; `logout()` implemented and
  moved above the placeholder banner; `login_required` decorator and
  `current_user()` helper; `@login_required` applied to `profile`
- `database/db.py` — add `get_user_by_id()` to the existing `Users` section
- `templates/login.html` — `url_for` action, sticky email
- `templates/base.html` — session-aware navbar
- `static/css/style.css` — only if the signed-in navbar needs a rule for the
  user's name; reuse the existing `.nav-links` styling if it fits

---

## Files to create

- None.

---

## New dependencies

No new dependencies. `check_password_hash` sits in `werkzeug.security` next to
the `generate_password_hash` already in use, and Flask's `session` is built in.

---

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug — verify with `check_password_hash`, never by
  comparing hashes or re-hashing the input
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Keep SQL in `database/db.py`; `app.py` calls helpers
- `secret_key` reads from the `SPENDLY_SECRET_KEY` environment variable with a
  hardcoded development fallback, and a comment saying the fallback must not be
  used in production. No `python-dotenv` — that is a new dependency
- **One error message for both failure cases:** a wrong password and an
  unknown email both return "Incorrect email or password." Distinguishing them
  tells an attacker which addresses are registered
- Run `check_password_hash` even when the email is unknown, against a dummy
  hash, so a missing account and a wrong password take the same time to answer
- Normalise the submitted email with `.strip().lower()`, matching how Step 2
  stored it — otherwise nobody who typed a capital letter can ever sign in
- `session.clear()` on logout, not `session.pop("user_id")` — clear removes
  anything later steps put there
- `login_required` must use `functools.wraps`, or Flask sees every decorated
  view as the same endpoint name and refuses to start
- Store only `user_id` in the session. Names and emails go stale; the id is
  looked up fresh per request
- Redirect after a successful POST, never render — a rendered response leaves
  the form resubmittable on refresh

### Validation and outcomes

| Case | Outcome |
| --- | --- |
| email blank or password blank | "Please enter your email and password." |
| email not found | "Incorrect email or password." |
| password does not match hash | "Incorrect email or password." |
| valid | `session["user_id"]` set, redirect to `/profile` |
| `GET /logout` while signed in | session cleared, redirect to `/` |
| `GET /logout` while signed out | no error, redirect to `/` |
| `GET /profile` while signed out | redirect to `/login` |

---

## Definition of done

- [ ] `GET /login` renders the form unchanged, no error box
- [ ] Signing in as `demo@spendly.com` / `demo123` redirects to `/profile` and
      the placeholder string is reached
- [ ] `DEMO@Spendly.com` with trailing spaces signs in the same account
- [ ] An account registered through `/register` in Step 2 can sign in with the
      password it was created with — the full register-then-login round trip
      works
- [ ] A wrong password shows "Incorrect email or password."
- [ ] An unregistered email shows the **same** message, not "user not found"
- [ ] A blank email or password shows the missing-fields message
- [ ] After a failed attempt the email field is still filled and the password
      field is empty
- [ ] While signed in, the navbar shows the user's name and "Sign out"; while
      signed out it shows "Sign in" and "Get started"
- [ ] `GET /logout` clears the session, returns to `/`, and the navbar flips
      back to signed-out
- [ ] After logout, `GET /profile` redirects to `/login` instead of rendering
- [ ] `GET /profile` while signed out redirects to `/login`
- [ ] The session cookie survives a server restart only if
      `SPENDLY_SECRET_KEY` is set — with the fallback it may not, and that is
      expected
- [ ] `/`, `/register`, `/terms`, `/privacy` still load for signed-out visitors
- [ ] App starts clean on port 5001 with no errors on repeated restarts
