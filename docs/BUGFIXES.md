# Bug fixes — October 2026

Found while building the test suite and observability for Zunoot. Each bug has a regression test in
`tests/test_bugfixes.py`, named `test_bugN_...`. Every regression test was checked to **fail against the
code before the fix** and pass after. The two exceptions are positive-control tests ("the owner can still
do X"), which pass on both.

| # | Severity | Area | Summary |
|---|----------|------|---------|
| 1 | **Critical** | Review | Starting any review returned HTTP 500 — the core feature was down |
| 2 | **Critical** | Data integrity | Ending a review overwrote *other users'* cards that had the same front text |
| 3 | High | Data integrity | Joining a guild incremented **every** guild's member count |
| 4 | High | Community | Uploading to the community library always failed; topic upload could 500 |
| 5 | High | Security (authz) | Five missing ownership/role checks (reorder, guild requests, guild delete, community delete, topic import) |
| 6 | High | Security (CSRF) | Account deletion and guild/community actions changed data on GET |
| 7 | Medium | Game economy | Submitting an empty flashcard form still awarded 10 coins (farmable) |
| 8 | Medium | Shop | Buying an item you already owned took the coins and then 500'd |
| 9 | Medium | Reliability | Weekly points reset leaked a DB connection on every guild page view |
| 10 | Medium | Reliability | Spaced review crashed for libraries with >~1,000 not-due cards |
| 11 | Medium | Privacy | A review queue survived logout into the next user's session |
| 12 | Low | Data integrity | Review ratings outside 0–5 were accepted and corrupted the easiness factor |
| 13 | Medium | Observability | Library routes caught and discarded every exception without logging it |
| 14 | Low | Frontend | `script.js` threw a TypeError on every page except Guilds |
| 15 | Low | Privacy | `print()` calls wrote leaderboard rows to the production logs |
| 16 | Medium | Data integrity | Renaming a topic / editing a card could change a *different* one with the same name |

---

## BUG-1 — Every review request returned HTTP 500

- **Symptom.** `POST /library/review` (both modes) and `GET /library/review` → 500. Users could build decks but not study them.
- **Root cause.** The route stored a `SessionQueue` object (containing `Flashcard` objects) in the Flask session. `requirements.txt` pins Flask-Session 0.8, which serialises sessions with **msgspec**; msgspec only encodes plain data, so saving the session raised `TypeError: Encoding objects of type SessionQueue is unsupported`. The error happens when the session is saved, *after* the view returns, so the route's own `try/except` never saw it. (The README describes the session as holding only card text — the code had drifted from that.)
- **Fix.** `SessionQueue.to_dict()` / `from_dict()` (in `backend/session_queue.py`). The session now holds card IDs plus SM-2 scheduling state (interval, repetition count, easiness, dates) and the queue pointers. Card text is read from the database when a card is shown, via `queries.get_flashcard_text()`, which is scoped to the logged-in user. The queue algorithm itself is unchanged.
- **Tests.** `test_bug1_review_queue_round_trips_through_plain_data`, `test_spaced_review_updates_sm2_state`, `test_unspaced_review_cycles_and_does_not_persist`.
- **Why nobody saw it.** No error was logged anywhere useful, and there was no metric for 5xx responses. That is exactly the gap the observability work in this PR closes (see BUG-13 and `OPS_NOTES.md`).

## BUG-2 — Ending a session overwrote other users' cards

- **Symptom.** After user A ended a spaced-repetition session, any card *anywhere in the database* with the same front text as one of A's cards (e.g. "What is the powerhouse of the cell?") took on A's scheduling state and A's back text.
- **Root cause.** `push_deck` ran `UPDATE flashcards ... WHERE front = %s`. Front text is not unique and not scoped to a user.
- **Fix.** `push_deck(deck, username)` updates by primary key (`flashcard_id`) and joins through `topics` → `subjects` so it only matches cards owned by the user. It writes only the SM-2 fields, never front/back, so a card edited mid-review keeps the edit. All rows are written in one transaction (previously one commit per card).
- **Test.** `test_bug2_push_deck_only_touches_the_owners_reviewed_card`.
- **Production impact.** While BUG-1 was live, no review session could reach "end session", so the exposure was most likely the period before the Flask-Session 0.8 upgrade. Overwritten scheduling data cannot be reconstructed: there is no history table, and Neon's point-in-time restore window is far shorter than the exposure. The damage is bounded to scheduling dates and backs of cards whose front text exactly matched another user's card.

## BUG-3 — Joining a guild incremented every guild's member count

- **Root cause.** `join_guild` ran `UPDATE guilds SET no_of_members = no_of_members + 1` with no `WHERE` clause.
- **Fix.** Added `WHERE guild_name = %s`.
- **Test.** `test_bug3_join_guild_only_increments_that_guild`.
- **Production data repair.** The stored counts are inflated, which also means guilds may have dropped out of the "available to join" list (it filters on `no_of_members < 50`). `db/repairs/001_guild_member_counts.sql` recomputes counts from actual membership. It previews the change and ends with `ROLLBACK`. **It has not been run.** Run it yourself after deploying, following the instructions in the file.

## BUG-4 — Community uploads always failed

- **Root cause.** `upload_subject` / `upload_topic` read the library from `session["library"]`, which was removed when the library tree moved out of the session in the earlier security pass. Every upload hit the `except` branch. In `upload_topic`, the `except` branch then referenced `topic_object`, which was never assigned, so the failure became a 500.
- **Fix.** The routes load the user's library from the database. The topic form now also posts its subject name, because topic names are only unique within a subject. Replacing an earlier upload (delete + insert) now happens in **one transaction**. Previously, a failure part-way through could leave a half-uploaded subject or lose the earlier upload. Failures are logged.
- **Tests.** `test_bug4_upload_subject_and_topic_to_community`, `test_bug4_upload_topic_failure_is_not_a_500`.

## BUG-5 — Missing authorisation checks

Every one of these only required being logged in as *any* user.

| | Endpoint | What an attacker could do | Fix |
|---|---|---|---|
| a | `POST /library/update-order/<type>` | Reorder anyone's subjects/topics/flashcards by ID | `UPDATE ... WHERE id = %s AND <owned by current user>`; unknown types return 400 |
| b | `POST /guild/accept-request`, `/reject-request` | Accept/reject requests for any guild, and **force-add any user to any guild** (no pending request needed) | Caller must be the guild's leader, and a pending request must exist. The member cap and the "requester not already in a guild" check run at accept time |
| c | `/guild/delete-guild` | Any member could delete their guild | Leader only |
| d | `/community/delete_subject`, `/delete_topic` | Delete anyone's community upload by ID | `DELETE ... AND uploader_username = current user` |
| e | `/community/import-topic/.../<subject_id>` | Import a topic into **another user's** subject; the duplicate check also looked for a *subject* with the topic's name | Subject must belong to the caller; duplicate check is now "topic of this name in this subject" |

Related hardening: users already in a guild can no longer create a second guild (which made them leader of two). Requests to non-existent guilds are refused instead of hitting a foreign-key error. Leaders can no longer "leave" their guild, which would orphan it; the UI already only offered them "Delete".

Tests: `test_bug5a_*` … `test_bug5e_*`.

## BUG-6 — State changes on GET (CSRF)

- **Root cause.** Flask-WTF's `CSRFProtect` only checks POST/PUT/PATCH/DELETE. These endpoints changed data on GET, so a link or `<img src>` on any website could trigger them for a logged-in visitor: `/auth/delete-account` (**delete the visitor's account**), `/guild/create-guild`, `/guild/join-guild/<name>`, `/guild/delete-guild`, `/guild/leave-guild`, `/community/delete_subject`, `/community/delete_topic`, `/community/import-subject/...`, `/community/import-topic/...`.
- **Fix.** All are now `methods=["POST"]`, and their forms send the CSRF token. The buttons look and behave the same. "Delete Account" and the topic-import dropdown stay links, which submit a hidden POST form. Deleting an account now also logs the user out.
- **Not changed.** `/auth/logout` stays GET. Logout-CSRF only signs someone out, and changing it would alter the nav link for no real security gain. This is the one deliberate exception, noted for review.
- **Tests.** `test_bug6_state_changes_reject_get` (9 endpoints), `test_bug6_delete_account_needs_csrf_token`.

## BUG-7 — Coin farming

`POST /library/<subject>/<topic>` awarded 10 coins (and 5 guild points) *before* validating the form, so posting an empty form in a loop minted coins. Rewards are now given only after a card is actually created. Test: `test_bug7_no_coins_for_invalid_flashcard_posts`.

## BUG-8 — Double purchase

The route deducted coins, then inserted the purchase on a separate connection. If the item was already owned, the insert hit the primary key → 500, with the coins already gone. Two concurrent purchases could also both pass the balance check. `queries.purchase_item()` now does check-owned → `UPDATE ... SET coins = coins - price WHERE coins >= price` → insert, in **one transaction**. Unknown item IDs on purchase/equip are handled instead of 500ing, and "equipped" is only flashed when something was equipped. Test: `test_bug8_purchase_is_atomic`.

## BUG-9 — Connection leak in the weekly points reset

`points_reset()` (called on every `/guild/guild` view) opened a connection, then opened a *second* one inside the `if`, and only closed the second. Every guild page view therefore leaked a Postgres connection until garbage collection. The rewrite uses one connection and claims the reset with a conditional `UPDATE pointsreset ... WHERE last_reset < monday_midnight`. If two requests race past Monday midnight, exactly one performs the reset. Test: `test_bug9_points_reset_runs_once_per_week`.

## BUG-10 — RecursionError on large libraries

`SessionQueue.getNextFlashcard` recursed once per skipped (not-yet-due) card. Python's default recursion limit is 1,000, so a spaced session over a library with ~1,000 not-due cards crashed. It is now a loop with identical behaviour. Tests: `test_bug10_*` (5,000 cards).

## BUG-11 — Review queue survived logout

The queue lived in the session and was not cleared by logout or login. On a shared browser, the next user would continue the previous user's queue. With BUG-1 fixed, that would have shown them the previous user's card text. The queue is now cleared on login, logout and account deletion, and card text is fetched with an ownership check, so even a stale queue can't leak another user's cards. Test: `test_bug11_review_queue_cleared_on_logout`.

## BUG-12 — Unvalidated review rating

`option` was passed straight to `int()` and into SM-2. A crafted rating like `500` produced nonsense easiness factors. Ratings outside 0–5 are now rejected (the user sees the normal "Something went wrong" message). Test: `test_rating_must_be_between_0_and_5`.

## BUG-13 — Exceptions swallowed without logging

Eleven `except Exception as e:` blocks in `blueprints/library/routes.py` flashed a message and discarded the exception. Combined with the app always answering with a redirect, a broken feature showed up as **302s, not 500s, and nothing in the logs**. Every handler now calls `current_app.logger.exception(...)`. In stage 2, those log records feed the `zunoot_handled_errors_total` metric, and that counter is part of the availability SLI (see `OPS_NOTES.md` → "Why status codes lie").

## BUG-14 — JavaScript error on every page

`static/script.js` wired the guild "Requests" tab on every page. Outside the guild page, `requestsHeading` is `null`, so this threw `TypeError: Cannot read properties of null` on every page load. Guarded with a null check.

## BUG-15 — Leaderboard data printed to logs

`add_points_db` printed a user's guild, and `get_intra_leaderboard` printed whole leaderboard rows (avatar, username, points) to stdout, which is the production log stream. Removed.

## BUG-16 — Edits applied to the wrong item

`/library/edit-topic` found the topic by **name across every subject**, and `/library/edit-flashcard` found the card by **front text across every topic**. With two subjects each containing "Chapter 1", renaming the second renamed the first. The edit forms now post the item's ID, and the routes match on ID within the user's library. Name matching remains only as a fallback for pages rendered before the deploy. Test: `test_bug16_edit_topic_and_flashcard_match_by_id`.

---

## Found, deliberately not changed here

- **N+1 queries with a new DB connection per query.** Every library page rebuilds the whole subject → topic → card tree with one query per subject and per topic, and `queries.database()` opens a fresh TLS connection to Neon for each one. This is the expected performance bottleneck for stage 5, so it is left as-is until it has been *measured* (before/after p95). See `loadtest/README.md`.
- **Community search treats `%` and `_` in the keyword as wildcards** (`LIKE`). Harmless and arguably a feature.
- **Weekly points reset still runs on request** rather than on a schedule (README "Known gaps").
- **Email addresses are not verified** (README "Known gaps").
