# Zunoot service level objectives

**Status:** proposed, October 2026. Review after four weeks of real measurements (see "Revisiting" below).
**Implementation:** `ops/prometheus/rules/zunoot-slo.yml` (recording rules + alerts), unit tests in
`ops/prometheus/tests/slo_test.yml`, dashboard row "SLOs" in `ops/grafana/zunoot-overview.json`.

## The service, honestly described

Zunoot is a single Flask instance on Render's free tier, talking to a free-tier Neon Postgres over the
public internet. It has about 18 real users and no redundancy anywhere. Users are students reviewing flashcards. Nobody
loses money or safety if it is down for an hour, but a user who opens it to revise before an exam and finds
it broken may not come back. The SLOs should be **achievable on this architecture** and **meaningful to a
student**. An SLO the platform can't physically meet would just be noise.

## SLIs

All SLIs are measured **server-side** from the app's own metrics, over **user requests**. User requests
exclude static files, the service worker, `/livez`, `/healthz` and `/metrics`. Probes and asset fetches
would otherwise dilute the ratios with traffic no student generated.

| SLI | Good event | Valid event | Source |
|---|---|---|---|
| **Availability** | a user request that did **not** fail | every user request | `zunoot_http_requests_total{outcome}` |
| **Latency** | a user request completed in **< 1 s** | every user request | `zunoot_http_request_duration_seconds_bucket{le="1.0"}` |
| **Uptime (synthetic)** | a probe of `/livez` succeeded | every probe, every 5 min | external uptime monitor |

**What "failed" means.** Most Zunoot routes catch exceptions, flash "Something went wrong", and **redirect**
(302). If availability were "non-5xx responses", a completely broken feature would score 100%: that is
exactly how BUG-1 (every review crashing) went unnoticed. So a request fails if it returned 5xx **or** the
app logged an exception while handling it (`logger.exception` → `outcome="error"`). The status code is taken
from outside Flask (WSGI middleware), so errors raised while saving the session are counted too.

**Why server-side and synthetic both.** Server-side SLIs only count requests that reached the app. If Render
is down, or the instance is cold, those requests never appear, and the server-side SLI looks *better* during
an outage. The synthetic `/livez` probe covers "is it reachable at all?". This repo deliberately uses
server-side request SLIs for the **error budget and burn-rate alerts**, and the probe's uptime for the
**headline uptime figure**.

## SLOs

| SLO | Target | Window | Error budget |
|---|---|---|---|
| Availability | **99.5%** of user requests succeed | rolling 30 days | 0.5% of requests |
| Latency | **95%** of user requests complete in < 1 s (i.e. **p95 < 1 s**) | rolling 30 days | 5% of requests |
| Uptime (synthetic) | **99.5%** of `/livez` probes succeed | calendar month | ≈ 3 h 36 min/month |

### Why 99.5% and not 99.9%

- **The platform sets the ceiling.** Render's free tier can restart the instance at any time, has a cold start
  of about a minute when it wakes, and there is exactly one instance. Neon's free compute suspends when idle,
  and if its monthly compute allowance ran out it would be suspended until the next month. 99.9% allows
  43 minutes of failure a month. A couple of unlucky platform restarts during busy periods would burn that,
  and nothing in my control could have prevented it.
- **The users don't need more.** For a revision tool, a few minutes of errors a week is an annoyance, not
  a crisis. Each extra nine costs roughly 10× the effort. Here that effort would go into a paid plan, a
  second instance, and a database with a hot standby.
- **It's still demanding.** 99.5% of requests means no more than 1 in 200 requests failing over a month.
  Before this work, the review feature failed 100% of the time and nobody knew.

### Why p95 < 1 s

- Zunoot is server-rendered: every click is a full page load. About **one second** is the usual guideline
  for keeping a user's flow of thought uninterrupted (Nielsen's response-time limits). Beyond it, the app
  feels sluggish.
- **p95, not average.** Averages hide the slow tail. The tail is the student with the biggest library, who is
  also the most engaged user.
- **Not p99.** At about 18 users, p99 over an hour is decided by one or two requests, so it would be too noisy
  to alert on.
- 1 s is a histogram bucket boundary (`le="1.0"`), so the SLI is an exact count, not an interpolation.
- **Internal target: p95 < 500 ms.** This is what the bottleneck fix in stage 5 aims for. Keeping the
  *SLO* at 1 s leaves headroom, so a slow day on Neon doesn't page anyone.

### Expected starting point

Measured locally (Postgres on the same machine), the library pages take **~20 SQL queries over ~17 new
database connections** for a small library, because the library tree is loaded one query per subject and
per topic, and every query opens a new connection. Against Neon over TLS, each new connection costs
tens of milliseconds. **The latency SLO may be failing in production on day one.** That is a finding, not
a reason to loosen the SLO. The stage 5 load test measures it, and the fix is judged against it.

## Alerting: multi-window, multi-burn-rate

From the [Google SRE Workbook, ch. 5](https://sre.google/workbook/alerting-on-slos/). *Burn rate* is how fast
the error budget is being spent relative to plan: a burn rate of 1 uses exactly the whole budget in 30 days.

| Alert | Severity | Long window | Short window | Burn rate | Availability threshold | Latency threshold | Meaning |
|---|---|---|---|---|---|---|---|
| `…FastBurn` | page | 1 h | 5 m | 14.4 | error ratio > 7.2% | slow ratio > 72% | 2% of the month's budget gone in an hour |
| `…SlowBurn` | page | 6 h | 30 m | 6 | > 3% | > 30% | 5% of the budget gone in six hours |
| `…BudgetBurn` | ticket | 3 d | 6 h | 1 | > 0.5% | > 5% | on course to miss the SLO this month |

Why this shape:
- **The long window** makes the alert significant: a 30-second blip can't page.
- **The short window** makes the alert *stop* soon after the problem stops, instead of firing for the rest
  of the hour while the 1-hour average slowly recovers. `promtool` test 4 proves this.
- **Two page tiers** catch both "everything is on fire" (fast) and "quietly broken all afternoon" (slow).
- **The ticket tier** catches the slow leak that never pages but would still miss the SLO.

### Low traffic (the hard part at 18 users)

Burn-rate alerts assume plenty of requests. At Zunoot's scale an hour might hold five requests, and one
failure would be a 20% error ratio, a 40× burn rate, and a page. That's a false alarm. Options from
the Workbook: generate synthetic traffic, combine services, or require a minimum number of events. This
repo **requires a minimum event count** for pages: at least 30 requests in the 1 h window, and 60 in the 6 h
window. `promtool` test 3 proves the page stays quiet at 3 requests/hour with a 33% error ratio, and the
mutation check confirms that test fails if the guard is removed.

What that costs: at very low traffic, real failures won't *page*. They still feed the 3-day ticket alert, the
dashboard and the logs. Total outages are caught separately:

### When there's nothing to measure

If the app is completely down, it serves no requests, so every burn-rate alert stays quiet. That's the
classic blind spot of request-based SLIs. It's covered by:
- `ZunootScrapeFailing`: Grafana Cloud hasn't been able to scrape `/metrics` for 5 minutes → page.
- `ZunootMetricsAbsent`: the scrape job itself has vanished → ticket.
- The external uptime monitor, which emails independently of Grafana. If the whole observability
  pipeline fails, the uptime monitor still reports it.

## Cost constraints that shaped the monitoring

Monitoring that costs more than the service is bad engineering. On free tiers it can also *cause* outages.

- **Neon free tier: 100 compute-hours/month**, then compute is **suspended until next month**. Neon only
  scales to zero after 5 minutes of no queries. A database health check every 5 minutes would keep it
  awake 24/7 (≈186 compute-hours) and take production down mid-month. So the 5-minute uptime probe hits
  **`/livez` (no database)**. `/healthz` (with the database) is probed **hourly**. Database failures during
  real use still show up immediately in the availability SLI, because every real request uses the database.
- **Render free tier: 750 instance-hours/month per workspace**, after which *all* free services are
  suspended. The 1-minute metrics scrape counts as traffic, so production never sleeps. That means no cold
  starts for users, but it uses ≈744 of the 750 hours in a 31-day month. **Staging must be left to sleep**:
  no scraping, no uptime monitor, and only woken for load tests. The alternative is Render's paid
  Starter plan (~$7/month), which removes both the spin-down and the hour cap. That's a decision for
  the owner; see SETUP_CHECKLIST.md.

## Error budget policy

Light, because it's a one-person project. It is still written down, because writing it down is the point.

1. **Budget healthy (> 50% left):** ship freely; experiments OK.
2. **Budget low (< 25% left):** only ship fixes and reliability work; no risky migrations.
3. **Budget exhausted:** feature freeze until the 30-day window recovers. Write a short postmortem
   (template in `docs/RUNBOOK.md`) for anything that cost more than 20% of the budget in one incident.
4. **Platform-caused budget burn** (Render/Neon incidents) still counts. Users don't care whose fault it is.
   If platform burn alone threatens the SLO, that is the signal to revisit the free-tier decision.

## Revisiting

After four weeks of production data:
- If the measured availability is far *above* 99.5% (e.g. 99.95%), keep the SLO: an unused budget is
  permission to ship faster, not a reason to tighten.
- If the latency SLI sits *below* 95% even after the stage 5 fix, look at the slowest routes before
  changing the threshold.
- Recheck the low-traffic guards against the real hourly request counts (dashboard → "Requests").
