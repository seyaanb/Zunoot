# Zunoot runbook

One section per alert (anchors match the `runbook_url` in each alert), then the common procedures they refer
to. Written for a 2am reader: first decide whether users are affected, then stop the bleeding, then
investigate.

**Where things are**
- Dashboard: Grafana Cloud → Dashboards → *Zunoot — service overview*
- Logs: Render → zunoot → Logs. Every line is JSON. Filter by `"request_id":"<id>"` to follow one request;
  the ID is in the `X-Request-ID` response header.
- Deploys: Render → zunoot → Events. Rollback: Render → zunoot → Events → a previous deploy → **Rollback**.
- Database: Neon console → project → Monitoring. Point-in-time restore window: 6 hours (free tier).

---

## ZunootAvailabilityFastBurn

**Meaning:** more than 7.2% of user requests failed over the last hour *and* the last 5 minutes, with at
least 30 requests. At this rate the monthly error budget lasts about 2 days.

1. **Was there a deploy in the last hour?** (Dashboard → "Deployed version", or Render → Events.) If yes,
   **roll back first, investigate second.** Rolling back takes a minute, while debugging can take hours.
2. Dashboard → *Handled exceptions by route* and *Responses by status*: is it one route or all of them?
   - **All routes** → shared dependency. Check `/healthz` and the *DB errors* panel. Neon status page:
     https://neonstatus.com. If Neon compute is suspended because the free allowance ran out, see
     "Neon compute suspended" below.
   - **One route** → a code path. In Render logs, filter `"outcome":"error"` and that `route`, then read the
     `exc` field of the matching `"level":"error"` line with the same `request_id`.
3. Once mitigated, write a short postmortem (template below) if it cost > 20% of the budget.

## ZunootAvailabilitySlowBurn

**Meaning:** more than 3% of requests failed over 6 hours and still in the last 30 minutes: a smaller,
persistent problem. Same procedure as the fast burn, minus the urgency. Usually one feature that is broken
for everyone who uses it. Check *Handled exceptions by route* first.

## ZunootAvailabilityBudgetBurn

**Meaning (ticket, not page):** the 3-day error ratio is above 0.5%, so the month will miss 99.5% if nothing
changes. Look at the trend on *Error ratio* over 7 days. Fix the top erroring route during working hours. If
the budget is below 25%, apply the error budget policy in `docs/SLO.md`.

## ZunootLatencyFastBurn

**Meaning:** over 72% of requests took ≥ 1 s in the last hour and the last 5 minutes.

1. *Connect latency* panel high? → Neon is slow or cold (scale-to-zero wake-ups are a few hundred ms each,
   and the app opens many connections per page). Check neonstatus.com.
2. *Share of request time spent in the database* near 100%? → the database side. Check *Query p95 by
   function* for one query that suddenly got slower (e.g. a table grew and an index is missing).
3. *Requests in flight* climbing with flat DB time? → the app is saturated: gunicorn threads are all busy.
   Possible causes are a load spike, or a slow external call holding threads. Raise `GUNICORN_THREADS` or
   `WEB_CONCURRENCY` in Render env vars (it restarts the service) as a stopgap.
4. Recent deploy? → roll back.

## ZunootLatencySlowBurn

Same diagnosis as the fast burn over a 6-hour view. Commonly a single heavy route (*p95 latency by route*),
e.g. a user with a very large library hitting the N+1 library load.

## ZunootLatencyBudgetBurn

Ticket. Find the routes contributing the most slow requests and plan the fix. See `loadtest/README.md`
for the measurement loop.

## ZunootScrapeFailing

**Meaning:** Grafana Cloud hasn't been able to scrape `/metrics` for 5 minutes. Burn-rate alerts are blind
until this is fixed.

1. Open https://zunoot.onrender.com/livez in a browser.
   - **Doesn't load / 5xx** → the app is down. Render → zunoot → Logs and Events. Common causes: a failed
     deploy (Render keeps the old one running if the new one never passes `/livez`, so check whether this is
     a *runtime* crash), an out-of-memory restart loop, or free-tier hours exhausted (Render dashboard
     banner).
   - **Loads** → the app is fine and the scrape is broken. Check Grafana Cloud → Connections → Metrics
     Endpoint → the job's error. `401` means `METRICS_TOKEN` in Render no longer matches the scrape job's
     bearer token (someone rotated one but not the other).
2. The uptime monitor should agree with you. If it doesn't, one of the two is misconfigured.

## ZunootMetricsAbsent

Ticket. There is no `up` series at all: the Grafana Cloud scrape job was deleted, disabled or renamed (the
rules match `job=~".*zunoot.*"`). Recreate it per `SETUP_CHECKLIST.md` section 4.

---

## Procedures

### Roll back a deploy
Render → zunoot → **Events** → find the last good deploy → **Rollback**. Render rebuilds that commit and
switches traffic once `/livez` passes. Then revert the bad commit on `main` with `git revert`, so the next
auto-deploy doesn't reintroduce it.

### Neon compute suspended (free allowance used up)
Symptoms: every request fails, `/healthz` returns 503 with `OperationalError`, Neon console shows compute
suspended. There is no in-app fix. Either upgrade the Neon plan, or wait for the monthly reset. Prevention
is in `docs/SLO.md` → "Cost constraints". Check that nothing (a load test, a forgotten script) is querying
the database continuously.

### Find everything about one request
Take the `X-Request-ID` from the browser's network tab (or from a k6 failure), then filter Render logs by
that value. You get the access line (route, status, timings, DB query/connection counts) and any exception
logged during it.

### Restore the database
See `docs/RESTORE_DRILL.md`.

---

## Postmortem template

Blameless: describe what the system allowed to happen, not who did it.

```
# <date> <one-line title>
Impact:      who was affected, how, for how long; error budget consumed (% of 30-day budget)
Detection:   how we found out (alert / user report / luck) and how long after it started
Timeline:    UTC timestamps: start, detected, mitigated, resolved
Root cause:  the technical cause, and why our safeguards didn't stop it
What went well / what went badly
Action items: each with an owner and a date; prefer ones that prevent a whole class of problem
```
