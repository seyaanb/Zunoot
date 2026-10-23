# Load testing

`zunoot.js` is a [k6](https://k6.io) script for Zunoot's main user flow: log in → library → subject →
topic → start a review → rate three cards → end the session, with occasional guild, shop, community and
search pages in between. Its thresholds are the SLOs (`docs/SLO.md`), so a run **passes if the SLOs would
hold at that load**.

| File | Purpose |
|---|---|
| `zunoot.js` | the k6 script (profiles: `smoke`, `load`, `stress`) |
| `seed.py` | creates / deletes load-test accounts with realistic libraries directly in a **non-production** database |
| `compare.py` | turns two k6 summaries into a before/after Markdown table |
| `latency_proxy.py` | adds Neon-like network latency in front of a *local* Postgres, so production bottlenecks reproduce on a laptop |
| `results/` | k6 JSON summaries (git-ignored) |

## Rules

- **Never against production by default.** The script refuses `zunoot.onrender.com` unless
  `ALLOW_PRODUCTION=yes`, and `seed.py` refuses the host in `ZUNOOT_PROD_HOST`. Load-testing production
  writes to the real database and competes with real students. Staging runs the same image, on a Neon
  branch of production's data.
- **Staging sleeps between runs.** It's on Render's free tier, and the instance-hour budget is shared
  with production (`docs/SLO.md` → cost constraints). Run the test, then leave it alone.
- **Arrival-rate executors.** The `load` and `stress` profiles fix the *session start rate*, not the
  number of users. If the app slows down, latency rises instead of the test quietly sending less load.
  This avoids "coordinated omission".

## Running against staging

```bash
# once
brew install k6            # or: https://grafana.com/docs/k6/latest/set-up/install-k6/
pip install -r requirements.txt

export ZUNOOT_PROD_HOST=<production Neon host>        # seed.py's production guard
export STAGING_DB=<staging Neon branch connection string>
RUN=$(date +%Y%m%d-%H%M)

# 1. wake staging and check it's healthy (first request after sleep takes ~1 min)
curl -fsS https://zunoot-staging.onrender.com/healthz

# 2. create 10 accounts x 160 cards
python loadtest/seed.py --database-url "$STAGING_DB" --run-id "$RUN" --users 10

# 3. smoke first (proves the flow works), then the real run
k6 run -e BASE_URL=https://zunoot-staging.onrender.com -e SEEDED=1 -e RUN_ID=$RUN -e PROFILE=smoke loadtest/zunoot.js
k6 run -e BASE_URL=https://zunoot-staging.onrender.com -e SEEDED=1 -e RUN_ID=$RUN -e PROFILE=load \
       -e SUMMARY_FILE=loadtest/results/summary-before.json loadtest/zunoot.js

# 4. clean up
python loadtest/seed.py --database-url "$STAGING_DB" --run-id "$RUN" --delete
```

While it runs, watch the Grafana dashboard. If you've pointed a scrape job at staging for the duration
(SETUP_CHECKLIST.md §4.6), the **Database** row shows *why* each page takes as long as it does.

The `stress` profile ramps from 5 to 120 sessions/minute to find where it breaks: where p95 crosses
1 s or errors appear. Report that as "handles N sessions/min (≈ M req/s) within SLO".

## Finding and fixing one bottleneck: the method

1. **Measure before changing anything.** Run `load` on staging → `summary-before.json`.
2. **Find where the time goes, using the app's own metrics, not guesswork.** On the dashboard, compare
   *p95 latency by route* with *DB queries per request*, *New DB connections per request*, *Connect
   latency* and *Share of request time spent in the database*.
3. **Form one hypothesis, change one thing,** and deploy it to staging only.
4. **Re-run the identical test** → `summary-after.json`, then:
   ```bash
   python loadtest/compare.py loadtest/results/summary-before.json loadtest/results/summary-after.json
   ```
5. Record both runs (date, commit, profile, results) in `docs/PERFORMANCE.md`. Only then merge to
   production.

### What the metrics already show (local measurement)

With Postgres on the same machine, a library page for a user with 4 subjects × 3 topics issued
**20 SQL statements over 17 new database connections**. Two causes stack up:

- **N+1 loading:** `Library.initialiseLibrary` runs one query for the subjects, one per subject for its
  topics, and one per topic for its cards. That's 1 + S + T queries, and every library, subject and topic
  page, plus every edit, reloads the whole tree.
- **No connection reuse:** `queries.database()` opens a brand-new connection for every query: TCP + TLS +
  authentication to Neon each time, then closes it.

So a library page's cost grows with the size of the user's library × the cost of a new Neon connection.
Locally a connection costs ~3 ms, so nobody notices. Against Neon it is tens of milliseconds, so expect the
library pages to dominate the p95. Staging will confirm or refute this, and the numbers decide which fix
comes first.

## Reproducing it locally

```bash
python loadtest/latency_proxy.py --connect-ms 40 --rtt-ms 10 &        # :15433 -> local Postgres :5432
DATABASE_URL=postgresql://localhost:15433/zunoot SECRET_KEY=x METRICS_TOKEN=tok \
  gunicorn -c gunicorn.conf.py app:app
```

Local numbers through the proxy are a **simulation**. They're good for comparing two versions of the
code, but not for a CV. Quote staging.
