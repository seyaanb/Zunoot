# Numbers for the CV, and how to measure each one

Every number on a CV should be one you measured yourself, can reproduce, and can explain: what it
includes, what it doesn't, and how you got it. Interviewers will ask. Fill in the "Your result" column
yourself; nothing here is pre-filled with simulation numbers.

| # | Number | How to measure | Source of truth | Your result |
|---|---|---|---|---|
| 1 | **Uptime %** (monthly) | Complete calendar month after the uptime monitor is set up. UptimeRobot → monitor `zunoot livez` → the month's uptime %. | UptimeRobot (3 months of history on free) | |
| 2 | **Availability SLI %** (request success) | Grafana dashboard → "Availability" stat, time range = the same month (or the last 14 days on Free) | Grafana / recording rules | |
| 3 | **Restore time (RTO)** | `docs/RESTORE_DRILL.md`: stopwatch from T0 ("decide to restore") to "staging serving restored data" | your drill log in RESTORE_DRILL.md | |
| 4 | Restore data step only | the `total` line printed by `restore.sh` | same | |
| 5 | **RPO** | Nightly backups → ≤ 24 h (≤ minutes within Neon's 6 h PITR window). It's a design value, not a measurement. | backup.yml schedule | ≤ 24 h |
| 6 | **Load-test throughput** | k6 `stress` profile on staging. Report the **highest session rate where p95 stayed < 1 s and errors < 0.5%**, as req/s (`http_reqs` rate in that stage) | k6 summary JSON | |
| 7 | **p95 before / after** | k6 `load` profile on staging, identical runs before and after the fix; `loadtest/compare.py` | `docs/PERFORMANCE.md` | |
| 8 | DB connections per page, before / after | Dashboard → *New DB connections per request* for `/library/` during each run (or `db_connects` in the access logs) | Grafana / logs | |
| 9 | Test count | `pytest -q` last line | CI | |
| 10 | Bugs found and fixed | `docs/BUGFIXES.md` (16, including 1 production-down and 1 cross-user data corruption) | repo | 16 |
| 11 | Alert time-to-notify | `SETUP_CHECKLIST.md` §4.8: time from breaking the scrape token to the notification arriving | your note | |

## How to measure each one properly

**1. Uptime %.** Use a full calendar month that starts *after* the monitor exists. Quote it with its
definition: "99.9x% uptime (5-minute external HTTP checks, <month>)". If the month included a planned
change (e.g. the Docker cut-over), say so. Don't quote a partial month.

**2. Availability SLI.** This is the request-based number: share of real user requests that didn't fail.
It differs from uptime: it ignores time with no traffic and catches failures uptime can't see (one broken
feature on a "healthy" site). Quote both if they tell different stories. That makes a good interview answer.

**3–4. Restore time.** Quote the end-to-end time, and say what it covers: "restored a verified, encrypted
nightly backup into a fresh database and had the app serving it in 9m40s". Do the drill twice; the
second run is usually faster, and the difference is itself worth mentioning (what you fixed in between).

**6. Throughput.** Use `PROFILE=stress` on staging. Find the stage where p95 crossed 1 s or errors
appeared; the stage before it is your capacity. Convert sessions/min to req/s from the summary. Say what
the hardware was ("on a single free-tier instance, 0.5 GB RAM"). Expect a modest number. The value is in
knowing it and knowing what limits it (probably the database round trips), not in making it big.

**7. p95 before/after.** Same profile, same seeded data size, same staging plan, ideally the same time
of day, back to back. Only one change between the runs. Quote the absolute values, not just the
percentage: "cut p95 on the library pages from X ms to Y ms (−Z%) by adding connection pooling, measured
with k6 at N sessions/min on staging".

**Don't quote:** the local simulation numbers in `docs/PERFORMANCE.md` (they depend on the proxy's chosen
latency), or "30-day" Grafana figures on the free tier without saying they cover 14 days.

## Suggested CV lines (fill in your numbers)

- Took a live Flask/PostgreSQL app (18 users) to production-grade operations: Dockerised with CI-gated
  deploys, Prometheus metrics and structured JSON logging, and Grafana dashboards.
- Defined availability (99.5%) and latency (p95 < 1 s) SLOs with multi-window burn-rate alerting, unit-tested
  with promtool; achieved **__%** uptime over **<month>**.
- Built nightly encrypted, restore-verified PostgreSQL backups; measured **__ min** end-to-end recovery in a
  timed restore drill.
- Load-tested with k6, traced the main bottleneck to per-query database connections using the app's own
  metrics, and cut p95 latency from **__ ms to __ ms** with connection pooling.
- Wrote a Postgres-backed test suite (__ tests) that found 16 bugs, including a production outage of the core
  feature and a cross-user data-corruption bug.
