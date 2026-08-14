# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Spendly** — a Flask expense tracker used as a step-by-step teaching scaffold. Much of the app is intentionally unimplemented: routes return placeholder strings labelled with the step that will implement them (`"Add expense — coming in Step 7"`), and `database/db.py` is a comment block describing the functions a student must write. Do not treat these stubs as bugs or "fix" them wholesale — implement only the step being worked on, and keep the same incremental style.

## Running

Python is **not on PATH** on this machine; always call an interpreter by full path.

```bash
venv/Scripts/python.exe app.py          # dev server, http://127.0.0.1:5001
venv/Scripts/python.exe -m pytest        # pytest + pytest-flask are installed; no tests/ dir exists yet
venv/Scripts/python.exe -m pytest tests/test_x.py::test_name   # single test
venv/Scripts/python.exe -m pip install -r requirements.txt
```

If `venv/` is missing, create it with `C:\Users\syedm\AppData\Local\Programs\Python\Python312\python.exe -m venv venv`. `run.bat` is a gitignored double-click wrapper for the dev server.

Port is **5001**, not the Flask default 5000.

## Architecture

Single-module Flask app — `app.py` holds every route, split by comment banner into implemented routes (landing, register, login, terms, privacy — all GET-only, render-only) and placeholder routes. There is no blueprint layer, no ORM, and no app factory; `app` is a module-level global.

Persistence is planned as raw SQLite through `database/db.py`, whose contract is fixed by its own comments: `get_db()` (connection with `row_factory` + foreign keys on), `init_db()` (`CREATE TABLE IF NOT EXISTS`), `seed_db()`. The DB file is `expense_tracker.db` at the repo root (gitignored). Follow that contract rather than introducing SQLAlchemy.

Templates all `{% extends "base.html" %}` and fill `title` / `head` / `content` / `scripts` blocks. `base.html` owns the nav, footer, Google Fonts link, and `main.js` include. Internal links use `url_for('<route_function>')` — adding a page means adding both a route function in `app.py` and a template, or `url_for` will raise at render time.

Note the auth templates already `POST` to `/register` and `/login`, but those routes currently accept GET only. Wiring them up means adding `methods=["GET", "POST"]` and re-rendering the template with an `error` variable — the templates already render `{% if error %}` blocks.

## Styling

`static/css/style.css` is the single stylesheet for the whole app (no build step, no framework). It opens with a `:root` design-token block — `--ink*` for text, `--paper*` for surfaces, `--accent` (deep green) / `--accent-2` (amber), `--font-display` (DM Serif Display) for headings, `--font-body` (DM Sans), plus `--radius-*` and `--max-width`. Use these variables instead of literal colors or sizes. Sections are separated by full-width comment banners; keep that structure when adding rules.

Page-specific CSS that would bloat the shared sheet goes in a `{% block head %}<style>` in that template (see the modal styles in `landing.html`). `static/js/main.js` is still an empty placeholder — per-page scripts currently live in `{% block scripts %}`.

## Conventions

- Commit messages are lowercase `area: imperative summary` (e.g. `landing: add privacy policy page and route`).
- Copy is Pakistan/India-oriented ("Track every rupee", rupee amounts, local example names) — match it in new UI text.
