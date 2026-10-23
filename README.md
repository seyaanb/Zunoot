
# Zunoot
 
Zunoot is a flashcard app built around spaced repetition, with a social layer bolted on top: guilds, a shop, a community library people can pull decks from. I built it originally as my A-level Computer Science NEA project, then went back later and did a proper pass on the security and infrastructure once it had actual users on it.
 
Live at https://zunoot.onrender.com. Free tier, so cold start after any real idle time, give it a few seconds.
 
## What it does
 
Subjects contain topics, topics contain flashcards. Three levels, and a user builds the whole tree themselves.
 
### Accounts
 
Registration checks for a unique username, requires first and last name, validates the email with a regex, and enforces a minimum password length. Login and logout run through Flask-Login. Deleting an account cascades through the foreign keys, so it takes everything linked to that user with it, subjects, topics, flashcards, purchases, all of it.
 
### The tree
 
It's a straightforward composite pattern. `Node` is an abstract base class with `getName`, `getID`, `getChildren`, `getChildByName`, and `getChildByID`. `Subject`, `Topic`, and `Flashcard` all inherit from it, and `Library` sits at the root. `Library` has two tree-traversal methods, `searchNode` and `traverseSubtree`, and both work the same no matter which level they're called on. Recursive search runs through `searchNode`: one keyword search walks subjects, topics, and flashcards in a single pass and returns matches at every level.
 
### Spaced repetition
 
Each flashcard tracks `interval`, `repetition_no`, and `easiness_factor`, starting at 2.5. You rate a card 0-5 on review. Below 3 resets the interval and repetition count to zero. A pass advances things: interval goes to 1 day on the first successful review, 6 days on the second, and after that it's the previous interval multiplied by the easiness factor. The easiness factor also moves up or down depending on the rating, with a floor of 1.3 so the interval can't grow forever.
 
### Review sessions
 
A review session runs on a hand-rolled circular queue, front and rear pointers over a fixed list. Spaced mode only surfaces cards whose `next_review` date has passed, skipping past the rest. Unspaced mode goes through everything in the current subtree regardless of date. The Flask session stores only plain data: the queue pointers, whether it's spaced, and each card's ID and SM-2 state. Card text is read from the database (scoped to the logged-in user) when a card is shown. When the session ends, every reviewed card's updated SM-2 state gets written back to the database in one batch.
 
### Guilds and leaderboards
 
Create a guild and you're its leader. Joining someone else's is a request, sitting in a pending queue until the leader accepts or rejects it. Cap is 50 members. Two leaderboards: one for members within a guild, one across all guilds, both running on points. Points and coins are kept separate — coins come from reviewing regardless of guild membership, points only accrue while you're in one. Points reset every Monday at midnight UTC, tracked in a `pointsreset` table so it only fires once even if several requests land after the deadline. Leave a guild and your contributed points get deducted from its total. A leader deleting the guild resets every member's guild state.
 
### Shop and community library
 
Coins buy avatars and themes, seven built-in themes swapped through CSS custom properties on `<body>`. Owned items show as owned rather than showing a price again. The community library lets anyone upload a subject or topic. It's stored in a parallel set of `community*` tables, so an upload is its own copy, and anyone can browse, search, or import it into their own library.
 
## Stack
 
- Python, Flask, blueprints per domain (`auth`, `library`, `community`, `guild`, `shop`)
- PostgreSQL on Neon, was SQLite originally (migration details below)
- Flask-Login for sessions, Flask-WTF for CSRF, Werkzeug for password hashing
- Server-rendered Jinja2, vanilla JS, CSS custom properties for the themes
- Sortable.js off a CDN for drag-and-drop
- Service worker and web app manifest, installable as a PWA with an offline fallback page
## Data model
 
`students` and `guilds` reference each other: a student has `guild_name`, a guild has `leader_username`. Inserting either table first hits a foreign key that doesn't exist yet, which came up during the SQLite migration (more below). Subjects, topics, and flashcards each have a `position` column for drag-and-drop ordering. Every table only stores attributes describing its own entity, and the schema's normalised to 3NF/BCNF, done deliberately, not just how the tables happened to end up. `purchases` resolves the many-to-many between students and shop items. The `community*` tables mirror the subject/topic/flashcard structure separately, since an upload is its own copy rather than a live reference back to the original.
 
## Running it locally

With Docker (app + Postgres, seeded with the dev schema):

```bash
docker compose up --build        # http://localhost:5000
docker compose --profile test run --rm test   # test suite in a container
```

Without Docker, against any local Postgres:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
createdb zunoot && psql zunoot -f db/schema.sql -f db/seed_dev.sql
cp .env.example .env              # then edit
flask run
```

Tests need a local database whose name ends in `_test` (the suite resets its schema and refuses to run against anything else):

```bash
createdb zunoot_test
TEST_DATABASE_URL=postgresql://localhost/zunoot_test pytest
```

`db/schema.sql` is reconstructed from the code for dev and tests; it is never applied to production.

## Operations

| | |
|---|---|
| Health | `/livez` (process up, Render's health check), `/healthz` (process + database) |
| CI/CD | `.github/workflows/ci.yml`: lint, tests against Postgres, alert-rule tests, backup round trip, production-image boot, k6 smoke. Render deploys `main` only after CI passes. |
| Observability | Prometheus metrics on `/metrics` (token), JSON logs with request IDs, Grafana dashboard in `ops/grafana/` |
| SLOs and alerts | [`docs/SLO.md`](docs/SLO.md), rules in `ops/prometheus/rules/`, [`docs/RUNBOOK.md`](docs/RUNBOOK.md) |
| Backups | nightly, encrypted, restore-tested: [`docs/RESTORE_DRILL.md`](docs/RESTORE_DRILL.md) |
| Load testing | [`loadtest/README.md`](loadtest/README.md), results in [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) |
| Setup steps | [`SETUP_CHECKLIST.md`](SETUP_CHECKLIST.md) |
| Design notes | [`OPS_NOTES.md`](OPS_NOTES.md), with trade-offs and the questions they answer |

## What got fixed in the security pass
 
Built this for coursework first, went back to it later once people were actually using it. Found a few things.
 
`SECRET_KEY` was hardcoded as the string `"dev"` in both `config.py` and `app.py`. Changed it to an environment variable. There was also a `give_coins()` function still sitting in the code from testing, it hardcoded a specific username and gave it 10,000,000 coins with no auth check whatsoever. Removed it. CSRF protection went in through Flask-WTF, and the one endpoint that's a `fetch()` call instead of a form submit, the drag-and-drop reorder, carries its CSRF token in a custom header. A handful of queries in `queries.py` were built with f-string interpolation, including one place where it wasn't just the value being interpolated but the column name itself, in the edit routes (`edit_subject_name`, `edit_topic_name`, `edit_flashcard`, `update_order`). All of it's parameterised now.
 
The session handling took more work. It used to store the entire `Library` object tree in the Flask session through the filesystem backend, `Subject`, `Topic`, `Flashcard` objects and all. That meant pickling custom classes across every redeploy and code change, which is risky, since a change to those class definitions can invalidate sessions already sitting on disk. It also meant rebuilding the whole tree on every request even when a route only needed a handful of cards. Routes pull only what they need from the database now.
 
Migrating off SQLite was the bigger project. Rebuilt the schema in Postgres, sequenced the inserts around the students/guilds circular foreign key: students first with a null guild reference, then guilds, then backfill the guild reference. Reset every auto-increment sequence to match the migrated data's max IDs so the first insert after migration wouldn't collide with something already there. Checked row counts old to new across every table. `queries.py` needed a rewrite for `psycopg2`: `?` became `%s`, dropped the SQLite-only `PRAGMA foreign_keys` statements since Postgres enforces that anyway, swapped `cursor.lastrowid` for `RETURNING`. Found a bug during the migration too: `pointsreset` had no primary key and had two identical duplicate rows sitting in it. Deleted one using Postgres's `ctid` since there was no column value to tell them apart by, then added a primary key.
 
Two SQLite database files with real usernames and password hashes from testing had been committed at some point. Deleting them wasn't enough since they were still in git history, so I ran `git filter-repo` and checked a fresh clone afterward to confirm they were actually gone.
 
## Bugs fixed in October 2026

Writing a proper test suite turned up sixteen bugs, including a crash on every review request, a query that overwrote other users' cards, and several missing authorisation checks. Each one is written up in [`docs/BUGFIXES.md`](docs/BUGFIXES.md) (symptom, root cause, fix, regression test), and `tests/test_bugfixes.py` has a test for each that fails against the old code.

## Known gaps
 
The weekly points reset checks the `pointsreset` table against the current time on request rather than running on a schedule, so it only fires whenever the first request after Monday midnight happens to land. Email validation on registration checks the format with a regex, nothing confirms the address is real.
 
## What's next
 
- A real scheduled job for the weekly points reset instead of the check-on-request pattern
- Email verification on signup