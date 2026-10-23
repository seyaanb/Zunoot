# Performance log

One entry per experiment, newest first. Each records **where** it was measured, **what changed**, and the
**before/after** from `loadtest/compare.py`. Only staging/production entries are quotable externally;
local entries (through `loadtest/latency_proxy.py`) are simulations, used to choose what to try on staging.

Method: `loadtest/README.md`. SLO: p95 < 1 s, errors < 0.5% (`docs/SLO.md`).

---

## Experiment 1: connection pooling (branch `perf/db-connection-pool`)

**Hypothesis.** Library, subject and topic pages are slow because `queries.database()` opens a new TLS
connection to Neon for every query, and these pages issue one query per subject and per topic (N+1). So
cost ≈ (1 + S + T) × (connect + round trip). A pool removes the connect part for every route at once.

**Evidence before changing anything.** From the app's own metrics/logs, for a 5-subject × 4-topic ×
8-card library: **30 SQL statements and 27 new connections per library page** (`db_queries` / `db_connects`
in the access log; *DB queries per request* and *New DB connections per request* on the dashboard).

### Local simulation: 2026-10-23

- Profile `load` (`HOLD=2m`), 10 seeded users × 160 cards, gunicorn 2 × 4, Postgres 16 behind
  `latency_proxy.py --connect-ms 40 --rtt-ms 10`
- Before: `sre/foundations` (stage 5 commit). After: the same plus the single commit on `perf/db-connection-pool`

| metric | before | after | change |
|---|---:|---:|---:|
| requests | 408 | 407 | -0% |
| req/s | 1.68 | 1.74 | +4% |
| p50 (ms) | 375 | 265 | -29% |
| p95 (ms) | 2,693 | 1,088 | -60% |
| p99 (ms) | 2,761 | 2,088 | -24% |
| failed % | 0.00 | 0.00 |  |

| page | p95 before (ms) | p95 after (ms) | change |
|---|---:|---:|---:|
| login (incl. redirect to library) | 2,608 | 1,058 | -59% |
| library | 2,706 | 1,063 | -61% |
| subject | 2,687 | 1,075 | -60% |
| topic | 2,683 | 1,130 | -58% |
| review_start | 2,775 | 1,094 | -61% |
| review_rate | 293 | 150 | -49% |
| review_end | 2,689 | 2,093 | -22% |
| guild | 673 | 290 | -57% |
| shop | 386 | 182 | -53% |
| community | 273 | 143 | -47% |
| search | 2,655 | 1,060 | -60% |

Per-request DB behaviour on library pages (from the access log): new connections **27 → 0**, queries
**30 → 30**.

**Reading it.**
- Pooling removed every connection handshake: −60% p95 across the board, no errors.
- Still just over the 1 s SLO in this (pessimistic, 10 ms RTT) simulation, because the **30 queries per
  page remain**. That's the N+1 tree load. In production the round trip to Neon is likely shorter if
  Render and Neon are in the same region; staging will tell.
- `review_end` barely moved: ending a spaced session runs one `UPDATE` per reviewed card, the same
  "one round trip per row" pattern on the write side.

**Next experiments (one at a time):** (2) load the library tree in a constant number of queries instead
of 1 + S + T; (3) batch the end-of-session writes.

### Staging: *to do*

Run per `loadtest/README.md`, then fill in:

| | before (`main`) | after (pool) |
|---|---:|---:|
| date / commit | | |
| req/s | | |
| p50 / p95 / p99 (ms) | | |
| failed % | | |
| library p95 (ms) | | |
| connect p95 (dashboard, ms) | | |
