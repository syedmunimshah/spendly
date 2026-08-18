"""Verify a UI-first Spendly page.

Run from the repo root:

    venv/Scripts/python.exe .claude/skills/ui-first-page/scripts/verify_page.py <page-slug>

Five checks, in the order the skill lists them:

1. the route redirects to /login when signed out
2. the route returns 200 when signed in
3. the template holds no hex colours
4. the rendered HTML holds no inline style attributes
5. the pages that existed before still return what they returned before

Every check prints its own actual output, because a summary line saying
"all good" is exactly what gets skimmed past when it isn't true.
"""

import argparse
import re
import sys
from pathlib import Path

# scripts/ -> ui-first-page/ -> skills/ -> .claude/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

# Signed-out expectations for the routes that already existed. /login and
# /register are absent on purpose: anonymous_only redirects a signed-in
# visitor away from them, so they answer differently depending on the client
# and are checked separately below.
EXISTING_ROUTES = {
    "/": 200,
    "/login": 200,
    "/register": 200,
    "/terms": 200,
    "/privacy": 200,
}

# Tried in order when --session-key is not given. login_required reads
# session["user_id"] today; the alternatives cost nothing and stop the script
# reporting a broken page when all that changed is the key name.
SESSION_KEY_CANDIDATES = ("user_id", "uid", "id")

HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def first_user_id():
    """An id that actually exists, so check 2 tests the page and not the seed."""
    try:
        from database.db import get_db
    except Exception as exc:
        print(f"    (could not import get_db: {exc})")
        return None

    try:
        conn = get_db()
        try:
            row = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        finally:
            conn.close()
    except Exception as exc:
        print(f"    (could not read users table: {exc})")
        return None

    return row["id"] if row else None


def check(number, label, passed, detail):
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {number}. {label}")
    for line in str(detail).splitlines():
        print(f"       {line}")
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", help="page slug, e.g. dashboard")
    parser.add_argument("--session-key", help="session key login_required reads")
    parser.add_argument("--user-id", type=int, help="user id to sign in as")
    args = parser.parse_args()

    slug = args.slug.strip("/")
    url = f"/{slug}"
    template = REPO_ROOT / "templates" / f"{slug}.html"

    import app as spendly

    spendly.app.config["TESTING"] = True
    results = []

    print(f"Verifying {url} (template: {template.relative_to(REPO_ROOT)})\n")

    # --- 1. signed out -----------------------------------------------------
    client = spendly.app.test_client()
    response = client.get(url)
    location = response.headers.get("Location", "")
    results.append(
        check(
            1,
            f"GET {url} signed out redirects to /login",
            response.status_code == 302 and "/login" in location,
            f"status={response.status_code} location={location or '(none)'}",
        )
    )

    # --- 2. signed in ------------------------------------------------------
    user_id = args.user_id if args.user_id is not None else first_user_id()
    keys = [args.session_key] if args.session_key else list(SESSION_KEY_CANDIDATES)

    html = ""
    signed_in_detail = f"no user found to sign in as (user_id={user_id})"
    signed_in_ok = False

    if user_id is not None:
        tried = []
        for key in keys:
            client = spendly.app.test_client()
            with client.session_transaction() as sess:
                sess[key] = user_id
            response = client.get(url)
            tried.append(f"{key}={user_id} -> {response.status_code}")
            if response.status_code == 200:
                html = response.get_data(as_text=True)
                signed_in_ok = True
                break
        signed_in_detail = "tried: " + ", ".join(tried)
        if not signed_in_ok:
            signed_in_detail += (
                "\nnone returned 200 — read login_required in app.py, then re-run"
                "\nwith --session-key and --user-id set explicitly"
            )

    results.append(check(2, f"GET {url} signed in returns 200", signed_in_ok, signed_in_detail))

    # --- 3. no hex colours in the template ---------------------------------
    if template.exists():
        source = template.read_text(encoding="utf-8")
        hexes = HEX_COLOUR.findall(source)
        detail = "none found" if not hexes else f"{len(hexes)} found: {', '.join(sorted(set(hexes)))}"
        results.append(check(3, f"{template.name} uses design tokens, not hex", not hexes, detail))
    else:
        results.append(check(3, f"{template.name} exists", False, f"missing: {template}"))

    # --- 4. no inline styles in the rendered page --------------------------
    if signed_in_ok:
        inline = html.count('style="')
        results.append(
            check(
                4,
                "rendered HTML has no inline style attributes",
                inline == 0,
                f'style=" occurrences: {inline}',
            )
        )
    else:
        results.append(check(4, "rendered HTML has no inline style attributes", False, "skipped — check 2 failed"))

    # --- 5. existing routes unchanged --------------------------------------
    client = spendly.app.test_client()
    lines, unchanged = [], True
    for path, expected in EXISTING_ROUTES.items():
        actual = client.get(path).status_code
        ok = actual == expected
        unchanged = unchanged and ok
        lines.append(f"{path} -> {actual} (expected {expected}) {'ok' if ok else 'CHANGED'}")
    results.append(check(5, "pre-existing routes still respond as before", unchanged, "\n".join(lines)))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
