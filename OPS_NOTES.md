# Operations notes: design, trade-offs and interview prep

For each piece of Zunoot's operational setup: **what it does**, **why it's built this way**, **what it
trades away**, and **questions an SRE interviewer is likely to ask**, with answers. The answers are short
on purpose: say them in your own words, then go deeper if asked.

**Before an interview,** be able to draw the whole thing from memory (§0), and know your measured numbers
(`docs/CV_METRICS.md`). If someone asks how you built it, be straightforward about which parts you
designed, which you implemented, and where you used tools or AI assistance. What interviewers probe is
whether you understand every decision, and this document is the way to make sure you do.

---

## 0. The system in one picture

```
 students ──HTTPS──▶ Render (free, 1 instance)
                      └─ Docker: tini ▶ gunicorn (2 procs × 4 threads) ▶ Flask app
                           ├─ WSGI middleware: request ID, metrics, JSON access log
                           ├─ /livez  (Render health check, no DB)
                           ├─ /healthz (DB SELECT 1; uptime monitor hourly)
                           └─ /metrics (bearer token) ◀──scrape 60s── Grafana Cloud
                                                                       ├─ dashboard
                                                                       ├─ SLO recording rules
                                                                       └─ burn-rate alerts ─▶ email/phone
                      │
                      └── psycopg2 ──TLS──▶ Neon Postgres (free; scales to zero; 6h PITR)
                                              ▲
 GitHub Actions ─── nightly 03:17 ───────────┘ pg_dump ▶ test-restore ▶ age-encrypt ▶ R2 bucket
   ├─ CI on every PR: lint, tests (real Postgres), promtool tests, backup round trip, image boot, k6 smoke
   └─ Render deploys main only after CI passes
 UptimeRobot ── /livez every 5 min (independent of Grafana)
 healthchecks.io ── dead man's switch for the backup job
```

**30-second pitch:** "Zunoot is a spaced-repetition app with about 18 real users. I took it from 'deployed'
to 'operated'. I wrote a test suite against real Postgres, which found 16 bugs, including one that had
broken the core review feature in production without anyone noticing. Then I added container builds with
CI-gated deploys, Prometheus metrics and structured logs, SLOs with multi-window burn-rate alerts,
restore-tested encrypted backups with a timed restore drill, and a load test that found and quantified
the main latency bottleneck."

---

## 1. The test suite and the bugs it found

**What:** `pytest` against a **real Postgres** (not SQLite, not mocks), 70+ tests: smoke tests,
regression tests for 13 of the 16 bugs (`tests/test_bugfixes.py`), observability tests. The suite refuses to run against
any database that isn't local and named `*_test`, because it drops the schema.

**Why real Postgres:** the app uses raw SQL through psycopg2. Mocks would only test that I called the mock.
SQLite differs in types, `RETURNING`, locking and error classes, and several bugs (BUG-2, BUG-3) were
*SQL* bugs.

**The headline bug (BUG-1):** every review request returned 500. The route put a Python object in the
session; Flask-Session 0.8 serialises with msgspec, which can't encode arbitrary objects. The error
happened while *saving* the session, after the view returned, so the route's `try/except` never saw it.
And most routes catch errors and redirect, so nothing obvious showed up anywhere.

**Interview questions**

- *How do you know your regression tests actually test the bug?* I ran all 32 against the pre-fix code,
  and 31 failed. The one that passed is a positive control (the owner can still reorder their own items),
  which is meant to pass on both. In an earlier check, one test had passed on the old code for the wrong reason: the
  old route rejected the method I used, so the authorisation check never ran. I rewrote it to try both GET
  and POST. A test that can't fail is worse than no test, because it gives false confidence.
- *Why didn't monitoring catch BUG-1?* There wasn't any. But the deeper lesson is that even status-code
  monitoring would have missed most of the app's failures, because handlers convert exceptions into a
  redirect with a flash message. That's why my availability SLI counts logged exceptions as failures (§5).
- *What's the riskiest change you made, and how did you de-risk it?* Changing state-changing GET endpoints
  to POST (CSRF fix). Old cached pages would send GETs and get 405s. Mitigations: the PWA's service worker
  doesn't cache HTML pages (I checked), every form was updated with a CSRF token, and tests assert both
  "GET is rejected" and "POST with token works".
- *How did you handle data already corrupted by the bugs?* BUG-3 inflated guild member counts. I wrote a
  repair script that previews the change and defaults to `ROLLBACK`, to be run by hand after a fresh
  backup. BUG-2's damage can't be reconstructed: there's no history, and Neon's point-in-time window is 6
  hours. I documented that rather than pretend otherwise.

---

## 2. The Docker image

**What:** multi-stage build on `python:3.13-slim`. The builder stage creates a virtualenv; the runtime
stage copies only that venv and the app. Runs as UID 10001, app files owned by root (read-only to the app),
`tini` as PID 1, gunicorn with a config file. hadolint runs in CI.

**Why these choices**
- **Slim, not Alpine:** psycopg2-binary and greenlet ship manylinux (glibc) wheels. On Alpine's musl they'd
  compile from source: slower builds, larger build stage, and subtle libc differences.
- **Non-root, read-only code:** a remote-code-execution bug can't rewrite the app or install persistence.
  A numeric UID lets platforms verify `runAsNonRoot`.
- **tini:** the process that receives SIGTERM must forward it and reap zombies. Without an init, PID 1
  gets kernel-default signal handling, so on deploy the container could be killed mid-request instead of
  draining. gunicorn's `graceful_timeout = 25` then lets in-flight requests finish.
- **Preload is off in `gunicorn.conf.py`, but the app must survive it anyway.** Render's native Python
  runtime sets `GUNICORN_CMD_ARGS="--preload …"`, which overrides the config file. Under preload, the
  master imports the app, opening a pooled DB connection, before forking. Two workers sharing that one
  socket would corrupt the protocol stream. So a `post_fork` hook disposes the inherited pool in each
  worker, and the Prometheus multi-process directory is created before any metric is defined. Not knowing
  about that default crashed the first deploy: see `docs/incidents/2026-10-23-render-preload-boot-crash.md`.

**Trade-offs:** base images pinned by tag, not digest (simpler, but not bit-for-bit reproducible;
Dependabot with digest pinning is the next step). apt packages not version-pinned (Debian drops old
versions, so pins break rebuilds); justified in `.hadolint.yaml`.

**Interview questions**
- *How does a deploy avoid dropping requests?* Render starts the new container, waits until `/livez` passes,
  switches traffic, then sends SIGTERM to the old one. tini forwards it to gunicorn, which stops accepting
  new connections and finishes in-flight ones within `graceful_timeout`.
- *Tell me about a deploy that went wrong.* The first deploy of this work crashed on boot. Render's
  Python runtime adds `--preload` through a default environment variable, so the app was imported before
  the hook that created the metrics directory. CI had tested the Docker image, and I'd checked the start
  command locally, but nothing had tested the platform's actual *environment*. Fixes: make the code
  independent of start-up order, dispose the inherited DB pool after fork (a second bug the same setting
  exposed), and add a CI job that reproduces Render's runtime exactly. Lesson: the deploy target is part
  of the system under test. Write-up: `docs/incidents/2026-10-23-render-preload-boot-crash.md`.
- *Why gthread workers, and why 2 × 4?* The app is I/O-bound (waiting on Neon), so threads give cheap
  concurrency within a process. Two processes isolate a crash or a stuck request and use a second core if
  the plan has one. 512 MB fits two Flask processes comfortably. They're env vars, so they can be tuned
  without a rebuild.
- *What does `timeout = 30` protect against?* A worker stuck on a hung socket. gunicorn kills and replaces
  it, so a single stuck request can't take a whole worker down permanently.

---

## 3. CI/CD and deploy gating

**What:** one CI workflow on every PR and on every push to `main`. It runs ruff (crash-class rules
everywhere, the full rule set on new code), hadolint, actionlint, shellcheck, pytest against Postgres,
promtool unit tests for the alert rules, a backup → encrypted restore round trip, a job that builds the
production image, boots it, probes it and runs a k6 smoke flow against it, and a check that the dashboard
JSON matches its generator. Render's **Auto-Deploy: After CI Checks Pass** deploys `main` only when every
check on that commit is green.

**Why:** the deploy pipeline *is* the safety mechanism for a solo developer, because nobody reviews my PRs.
Testing the actual image (not just the code) catches "works on my machine": a missing system library, the
wrong `CMD`, or running as root.

**Trade-offs**
- **Lint ratchet:** enforcing every rule on legacy code would mean a giant, risky formatting diff. New code
  meets the full standard, old code only "won't crash", and files move into the strict set as they're
  touched.
- **No canary or staged rollout:** one instance on the free tier. Mitigation: health-check gating and a
  one-click rollback (`docs/RUNBOOK.md`).
- CI on `main` isn't cancelled when superseded, because Render waits for that exact commit's result.

**Interview questions**
- *What happens if a bad commit passes CI?* Render deploys it. The SLO burn-rate alerts or the uptime
  monitor tell me. I roll back in Render (a previous deploy, one click), then `git revert` on `main` so the
  next deploy doesn't bring it back. Rollback before debugging.
- *How would this change with a team?* Required reviews, a staging deploy that runs the k6 smoke test as a
  gate before production, feature flags for risky changes, and canary releases once there's more than one
  instance.
- *Why does the image boot test matter if unit tests pass?* Unit tests import the code in the CI runner's
  environment. The boot test proves the *artifact* works: dependencies installed, the right user, the right
  entrypoint, config read from env, and the app reaching a real database.

---

## 4. Health checks: `/livez` vs `/healthz`

**What:** `/livez` returns 200 if the process can serve HTTP and touches nothing else. `/healthz` also runs
`SELECT 1` against Postgres with a 3-second timeout and returns 503 if that fails. It reports the error
*class* only, never the message, which could leak hostnames. Both bypass the login redirect.

**Why Render checks `/livez` and not `/healthz`:** Render uses the health check for two things: gating
deploys, and **restarting instances that fail it**. If the database has a blip, restarting the web app
fixes nothing, drops in-flight requests, and adds a cold start. That's the Kubernetes lesson that liveness
probes must not check dependencies. Also, Render probes every few seconds: a DB query that often would
stop Neon's free compute from ever scaling to zero and burn the monthly compute allowance. The "does the
DB config work?" question at deploy time is still covered: `app.py` touches the database at import, so a
broken `DATABASE_URL` means the workers never boot and `/livez` never passes.

**Interview questions**
- *Liveness vs readiness?* Liveness: "should this process be killed and restarted?". Only check things
  restarting would fix. Readiness: "should this instance receive traffic right now?". It can include
  dependencies. `/healthz` is closer to readiness, and it's what the uptime monitor and humans use.
- *Could a health check cause an outage?* Yes: a dependency check on a restart-triggering probe turns a
  dependency blip into a restart storm across every instance at once. Here, a frequent DB check could
  also exhaust Neon's free compute and suspend the database for the rest of the month.

---

## 5. Metrics

**What:** Prometheus metrics on `/metrics`, scraped by Grafana Cloud every 60 s with a bearer token:
- `zunoot_http_requests_total{method, route, status, outcome}`
- `zunoot_http_request_duration_seconds` histogram by route
- DB: per-query latency labelled by the `queries.py` function, connect latency, errors, and *per request*:
  queries, new connections and DB time
- `zunoot_handled_errors_total`, in-flight requests, build info (deploy annotations on the dashboard)

**Key design decisions**
- **`route` is the URL rule** (`/library/<subject_name>`), never the path. Raw paths contain user-chosen
  subject names: unbounded label cardinality (a classic way to take down a Prometheus) and a privacy leak.
  There's a test for exactly this.
- **Measured in WSGI middleware, outside Flask.** An `after_request` hook runs *before* Flask-Session saves
  the session. BUG-1 failed during that save, so a hook would have recorded a 200. The middleware sees
  the status gunicorn actually sends. A test simulates exactly this.
- **"Status codes lie": the `outcome` label.** Most routes catch exceptions and redirect (302). So a request
  counts as failed if it was a 5xx **or** the app called `logger.exception()` while handling it. The log
  handler increments a counter tied to the current request.
- **Histogram buckets include the SLO thresholds** (0.5 s, 1 s), so "fraction under 1 s" is an exact
  count, not an interpolation.
- **Multi-process mode:** each gunicorn worker has its own memory. `prometheus_client` writes per-process
  values to files in `PROMETHEUS_MULTIPROC_DIR`, and `/metrics` merges them. Without it, each scrape would
  see whichever worker answered, and counters would jump around. gunicorn hooks clear the directory on
  boot and mark dead workers.
- **Protected, not public:** metrics reveal traffic patterns and internal structure. Bearer token with a
  constant-time comparison. If no token is configured, the endpoint returns 404 rather than being open.

**Trade-offs:** pull model (needs a public HTTPS endpoint; Grafana's managed scraper won't scrape private
URLs) vs push (more moving parts). ~2–3k series is far below the 10k free limit. Labelling DB queries by
calling function uses `sys._getframe`, which is cheap but CPython-specific.

**Interview questions**
- *What are the four golden signals here?* Latency (histogram), traffic (request rate), errors
  (`outcome="error"` ratio), saturation (in-flight requests, DB time share, connections per request).
- *Why a histogram rather than a summary?* Histograms aggregate across processes and instances (sum
  buckets, then compute the quantile). Summary quantiles can't be averaged meaningfully. They also allow
  exact threshold SLIs.
- *What's high cardinality and how did you avoid it?* Each unique label combination is a separate time
  series. User IDs, raw paths or SQL text as labels would explode it. I used route templates, a bounded set
  of function names, and status codes.
- *How would you find which route got slow after a deploy?* Dashboard: p95 by route, with the deploy
  annotation. Then *DB queries per request* and *share of request time in DB* for that route tell me
  whether it's the code or the database.

---

## 6. Structured logs and request IDs

**What:** every line, from the app, Flask, gunicorn or libraries, is one JSON object on stdout with
`ts`, `level`, `logger`, `msg` and `request_id`. One access line per request records the route, status,
outcome, duration and DB queries/connections/time. A valid incoming `X-Request-ID` is reused, otherwise
one is generated, and it's returned in the response header. Probe requests are counted in metrics but not
logged.

**Why:** grep-able, filterable logs, and a way to go from "this request was slow" (k6 output, a user's
browser network tab, an alert) to every log line for that request. Request-scoped state lives in a
ContextVar, so code with no idea it's inside a request still logs the right ID.

**Bugs found in my own work:** the first version wrote every line twice under gunicorn (gunicorn's log
config and mine both attached a handler). The load test exposed it; there's now a regression test.
The query string is deliberately not logged, because search keywords are user content.

**Interview questions**
- *Why not log the username?* It's personal data, and it isn't needed to debug. The request ID links
  everything for a single request. If I needed per-user debugging I'd log a keyed hash, not the name.
- *How would you get these logs into Grafana?* Render log streams (syslog) to Grafana Loki or another log
  backend. Not done here, because Render's log viewer is enough at this scale.
- *Why validate the incoming request ID?* It's copied into every log line and a response header. Unvalidated,
  it's a log-injection and header-injection vector.

---

## 7. Dashboard

**What:** one Grafana dashboard: overview stats; SLO row (SLIs, budget remaining, burn rates);
traffic & errors; latency (percentiles, p95 by route, heatmap); database (queries/connections/time per
request, connect latency, slowest queries); instance health; deploy annotations.

**Why generated:** `ops/grafana/build_dashboard.py` writes the JSON. PromQL lives in one readable place,
diffs are reviewable, and CI fails if the JSON drifts from the generator. Every query was validated
against a real Prometheus scraping the app.

**Found while validating:** error-ratio panels showed "No data" on a perfect day: `sum()` of an empty
selector returns nothing, not 0. Fixed with `or vector(0)`, and the same fix went into the SLO rules.

---

## 8. SLOs and error budgets

See `docs/SLO.md` for the full reasoning. In short:

| SLO | Target (30 days) |
|---|---|
| Availability | 99.5% of user requests succeed (no 5xx, no logged exception) |
| Latency | 95% of user requests < 1 s (p95 < 1 s) |
| Uptime (synthetic) | 99.5% of `/livez` probes succeed |

**Interview questions**
- *SLI vs SLO vs SLA?* SLI: a measurement (the ratio of good events to valid events). SLO: the target for
  that measurement over a window. SLA: a contract with consequences, usually looser than the SLO. Zunoot
  has no SLA.
- *Why 99.5% and not 99.9%?* Single free-tier instance, platform restarts and cold starts I don't control,
  and student users for whom a few minutes of errors a week is tolerable. 99.9% would be 43 min/month:
  achievable only by paying for redundancy. An SLO you can't meet just trains you to ignore it.
- *What's an error budget for?* It turns reliability into a decision rule. Budget left: ship faster.
  Budget gone: freeze features and fix reliability. Mine is written down in `docs/SLO.md`.
- *Why is the SLI request-based rather than time-based?* It weights by user impact: an outage at 3 a.m.
  with no users costs less than one during an evening study session. The synthetic uptime SLO covers the
  time-based view.
- *What does your SLI miss?* Requests that never reach the app (Render down, DNS), network latency to the
  user, and front-end errors. Hence the external uptime probe, and an honest statement of the limits.
- *How long is your SLO window really?* 30 days by definition, but Grafana Cloud Free keeps metrics 14 days,
  so the dashboard's "30-day" figures are a 14-day estimate. Monthly uptime comes from UptimeRobot.

---

## 9. Burn-rate alerting

**What:** the SRE Workbook's multi-window, multi-burn-rate alerts: page at 14.4× over 1 h (+5 m) and 6×
over 6 h (+30 m), ticket at 1× over 3 d (+6 h). Thresholds: availability 7.2% / 3% / 0.5% errors; latency
72% / 30% / 5% slow. Plus `ZunootScrapeFailing` and `ZunootMetricsAbsent`. The rules are in the repo,
unit-tested with promtool, and published to Grafana on merge.

**Why burn rates, not "error rate > 5%":** a fixed threshold either pages on harmless blips or misses slow
leaks. Burn rate ties the alert to the budget: 14.4× for an hour means 2% of the month's budget is gone,
which is worth waking up for. The long window gives significance; the short window makes the alert stop
quickly once the problem stops.

**The low-traffic problem (be ready for this one):** at 18 users, an hour may have five requests, and one
failure is 20% errors, a 40× burn and a page. I require ≥30 requests in the 1 h window and ≥60 in the 6 h
window for pages. A promtool test proves the page stays quiet at 3 requests/hour with 33% errors.
Mutation testing proves the test fails if the guard is removed. Cost: very-low-traffic failures only
raise a ticket. Alternatives considered: synthetic traffic (costs Neon compute), or longer windows (slower
detection).

**The total-outage blind spot:** no requests means no errors, so burn-rate alerts are silent exactly when
everything is down. `ZunootScrapeFailing` (no scrape for 5 m) and the independent uptime monitor cover it.
The uptime monitor is from a different vendor, so if Grafana itself is the problem I still hear about it.

**Interview questions**
- *Where does 14.4 come from?* Spending 2% of a 30-day budget in 1 hour: 0.02 × 720 h / 1 h = 14.4.
- *How do you test alerts?* promtool unit tests with synthetic series (they fire, they stay quiet, and they
  reset). Mutation-check the tests. Then an end-to-end test: break the scrape token on purpose and time
  how long until my phone gets the notification.
- *Page vs ticket?* Page: user-visible harm now, needs a human within minutes. Ticket: will become a
  problem if ignored for days. Every page has a runbook entry (`docs/RUNBOOK.md`).

---

## 10. Backups and restore

**What:** nightly GitHub Action at 03:17 UTC. It runs `pg_dump` (custom format) as a read-only role,
**restores it into a throwaway Postgres inside the job**, records per-table row counts in a manifest,
encrypts with `age` to a public key, and uploads to R2 (`daily/`, `monthly/` on the 1st,
`latest.manifest.json`). Retention is set by bucket lifecycle rules (35 days / 400 days). A healthchecks.io
dead man's switch emails if a night is missed. `restore.sh` restores and verifies, and refuses the
production host, non-empty targets, checksum mismatches and wrong keys. CI runs a backup → restore round
trip on every PR.

**Why each piece**
- **Test restore every night:** a backup is only proven by restoring it. Corruption, version mismatch or a
  silently empty dump fails that night's job, not the day you need it.
- **Encryption with a public key:** GitHub holds only the *public* key. A leaked bucket or CI secret can't
  expose password hashes and emails. The private key is offline. The flip side: losing it makes every
  backup useless, so it's stored in two places.
- **Lifecycle retention, not script deletes:** the job's credentials can't delete, so a compromised token
  or buggy script can't wipe history. Optional bucket locks harden this further.
- **GitHub Actions over Render cron:** Render cron jobs aren't free. Actions are free, and keep logs and
  secrets in one place. Trade-off: schedules can be delayed, and GitHub disables them after 60 days of repo
  inactivity. Hence the dead man's switch.
- **A different provider from the database:** backups in Neon would die with the Neon account. These
  survive a lost account, a deleted project or a provider incident.
- **Neon PITR still matters:** for "I ran a bad UPDATE ten minutes ago", point-in-time restore (6 h on free)
  is faster and more precise. Two tools for two failure modes.

**Interview questions**
- *What are your RPO and RTO?* RPO ≤ 24 h from nightly dumps, or minutes for mistakes caught within 6 h
  (PITR). RTO: measured in the drill, end to end from "decide to restore" to "app serving restored data".
  Quote your number from `docs/RESTORE_DRILL.md`.
- *How do you know the backups work?* Every night's job restores the dump and checks it. Every PR runs a
  round trip. Each quarter I do a full drill to a fresh database with the app pointed at it, and time it.
- *Logical vs physical backups?* `pg_dump` is logical: portable across Postgres versions and providers, and
  small at this size, but slower to restore at scale and only a point-in-time snapshot. Physical backups
  plus WAL archiving (what Neon's PITR effectively gives) allow any point in time and suit large databases.
  At 1,500 cards, logical is right. At hundreds of GB, I'd switch.
- *What could still lose data?* A bug that writes wrong data for more than 6 hours, then gets noticed
  days later: restoring yesterday's dump loses everything since. Also losing the age private key.

---

## 11. Load testing and the bottleneck

**What:** a k6 script for the real user flow (login → library → subject → topic → review session → end),
with `smoke`, `load` and `stress` profiles, SLO-matching thresholds, per-page p95, and a request ID on
every request. A seeder creates realistic accounts directly in staging. A latency proxy reproduces Neon's
connection cost locally. A comparison script gives the before/after table.

**Why arrival-rate executors:** with closed-model executors (fixed VUs, each waiting for its previous
request), a slow server receives *less* load, and the measured latency looks better than reality
("coordinated omission"). An arrival-rate executor keeps starting sessions on schedule.

**The bottleneck (found from the metrics before running a single load test):** a library page loads the
user's whole tree with **one query per subject and per topic** (N+1), and `queries.database()` opens a **new
TLS connection to Neon for every query**. Locally: 20 queries over 17 new connections for a small library.
Under simulated Neon latency the load test failed the latency SLO (numbers in `docs/PERFORMANCE.md`).

**The candidate fix (separate branch `perf/db-connection-pool`):** a small connection pool. It's per
process and bounded, waits rather than failing when exhausted, rolls back every connection when it's
returned, discards broken connections, reaps idle ones after 2 minutes (so Neon can still scale to zero),
is fork-safe, and has a kill switch (`DB_POOL=0`). No query function changed: `close()` returns the
connection to the pool.

**Interview questions**
- *Why pooling first rather than fixing the N+1?* One change at a time, measured. Pooling removes the
  most expensive part (handshakes) for *every* route with one small, reversible change. The N+1 is still
  there, but each query is now one round trip instead of a handshake plus a round trip. Batching the tree
  load into one query is the next, separate experiment, with its own before/after.
- *What can go wrong with a connection pool?* Stale connections the server has dropped (discarded, plus
  the idle reaper). Transactions leaking between requests (rollback on return). Exhaustion under load
  (bounded wait, then a clear error). Fork bugs (created lazily per process). Too many connections to the
  database: workers × pool size = 16, well under Neon's limit, and Neon's own pooled endpoint can absorb
  more.
- *Why not use Neon's pooled endpoint (PgBouncer) instead?* It pools connections *on Neon's side*, which
  protects the database from too many connections. But each new client connection still pays TCP + TLS +
  auth to reach it. The app-side pool removes that client handshake. They're complementary.
- *How did you make sure the load test itself was right?* A smoke profile first. Checks that assert the
  content, not just a 200 (the login page is also a 200: that's how I caught k6 silently logging users out
  between iterations). And a negative run (an empty library) to prove the thresholds can fail.
- *Why not load-test production?* It writes to the real database and competes with real users for a tiny
  instance. Staging runs the same image on a Neon branch of production data. The script refuses production
  unless explicitly overridden.

---

## 12. Security posture (questions SREs ask too)

- **Secrets:** environment variables in Render and GitHub. Backup secrets are in a GitHub *environment*
  restricted to `main`. Nothing secret is in the repo; `.env` is git-ignored. Separate tokens for staging
  and production.
- **Least privilege:** the backup role is read-only. The bucket write token can't delete. The restore token
  is read-only and lives only on my laptop. Metrics need a token.
- **Fixed in this work:** CSRF on GET endpoints (including account deletion), five authorisation holes, and
  leaderboard data printed to logs (`docs/BUGFIXES.md`).
- *If the GitHub repo secrets leaked, what's exposed?* Read-only database access (bad: emails and password
  hashes, which are scrypt/pbkdf2-hashed), the ability to write junk backups (but not delete old ones), and
  the Grafana token. Response: rotate everything, which `SETUP_CHECKLIST.md` lists in one table.

---

## 13. Cost-aware design (a good story at any company)

Free tiers have cliffs, not slopes. Two would have caused outages if the monitoring were naive:
- **Neon:** 100 compute-hours/month, then the compute is suspended for the rest of the month. A DB health
  check every 5 minutes keeps it awake 24/7 (≈186 h). So frequent probes hit `/livez`; `/healthz` is hourly.
- **Render:** 750 instance-hours/month per workspace, then *all* free services are suspended. The metrics
  scrape keeps production awake (≈744 h). So staging stays suspended between load tests.

*Interview framing:* "monitoring isn't free. I checked what each probe actually cost before choosing its
frequency."

---

## 14. Known limitations and what I'd do next

- Single instance, no redundancy. The next nine of availability needs paid plans, and a second region
  doesn't make sense for 18 users.
- The N+1 tree load is still there after pooling. The next experiment batches it into one query.
- No log aggregation beyond Render's viewer. Next: Render log stream → Grafana Loki.
- Schema migrations aren't versioned. `db/schema.sql` is reconstructed for tests. Next: Alembic or plain
  numbered SQL migrations, applied in a pre-deploy step.
- Dependabot for Python dependencies, base images (with digest pinning) and GitHub Actions.
- Synthetic browser check of the full study flow (Grafana Synthetic Monitoring's free allowance) to catch
  front-end breakage that server metrics can't see.

---

## 15. Quick-fire concepts

- **RED** (rate, errors, duration) for request-driven services; **USE** (utilisation, saturation, errors)
  for resources. My dashboard is RED for HTTP, plus USE-style DB panels.
- **Toil:** manual, repetitive, automatable work that scales with load. The backup verification and alert-rule
  deployment are automated precisely so they don't become toil.
- **MTTD / MTTR:** time to detect and time to recover. Burn-rate alerts reduce MTTD. Runbooks, rollback-first
  and restore drills reduce MTTR.
- **Blameless postmortem:** focus on what the system allowed, not who erred. Template in `docs/RUNBOOK.md`.
- **Graceful degradation:** e.g. if the leaderboard query fails, still render the library. Zunoot's
  try/redirect pattern is a crude version of this; now at least every failure is logged and counted.
