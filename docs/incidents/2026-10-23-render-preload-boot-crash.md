# 2026-10-23: first deploy of the SRE work crashed on boot

Blameless format (template: `docs/RUNBOOK.md`). Times are UTC.

## Summary

Merging PR #1 deployed a version that crashed while importing the app under gunicorn on Render. Render's
native Python runtime starts gunicorn with `--preload` by default, a setting the code didn't account for
and that no test reproduced. The owner restored service by changing the start command. PR #3 fixes the
cause and adds a CI job that runs the app the way Render does.

## Impact

- The new deploy never served traffic: every boot attempt failed on importing `app.py`.
- *To confirm from Render → Events:* whether Render kept the previous deploy serving (it does when a new
  deploy fails to come up), or whether users saw errors, and for how long. Record the answer here, and
  count any user-visible minutes against the availability budget.
- While the stopgap is live, production runs `--preload` with 2 workers. The workers can share the
  database connection the master opened at import (see "A second, latent problem"). There are no known
  failures from this, and PR #3 fixes it.

## Timeline

| Time (UTC) | Event |
|---|---|
| 19:35 | PR #1 merged; Render starts deploying `main` (native Python 3.14.3, start command `gunicorn app:app`) |
| ~19:36 | Boot fails: `FileNotFoundError: … '/tmp/zunoot-prometheus/gauge_livesum_39.db'`, raised at `observability/metrics.py` line 47 during app import |
| before 19:38 | Owner changes the start command to `mkdir -p /tmp/zunoot-prometheus && gunicorn app:app`; the app boots |
| 19:38 | Reported. Reproduced the same day on Python 3.14.3; root cause found; fixed and tested in PR #3 |

## Root cause

1. Render sets `GUNICORN_CMD_ARGS="--preload --access-logfile - --bind=0.0.0.0:10000"` on every native
   Python service ([Render docs](https://render.com/docs/environment-variables)). gunicorn applies
   `GUNICORN_CMD_ARGS` *after* `gunicorn.conf.py`, so it overrode the config file's
   `preload_app = False`.
2. With `--preload`, the gunicorn master imports `app.py` while starting up, *before* calling the
   `on_starting` hook.
3. `gunicorn.conf.py` set `PROMETHEUS_MULTIPROC_DIR=/tmp/zunoot-prometheus`, but the directory was only
   created in `on_starting`. Importing the app defines Prometheus metrics. In multi-process mode,
   defining a Gauge immediately opens `<dir>/gauge_livesum_<pid>.db`, and the directory didn't exist yet.

## A second, latent problem with the same cause

Under `--preload`, `app.py` runs `db.create_all()` in the master. That leaves one open, pooled Postgres
connection, and each forked worker inherits the same socket. Two worker processes sending queries over
one TLS connection can corrupt each other's traffic. Before PR #1, gunicorn ran a single worker, so only
one process ever used that inherited connection. PR #1's config runs two.
`tests/test_gunicorn_preload.py::test_forked_workers_get_their_own_database_connection` demonstrates it:
without a fix, a forked child talks to Postgres through the parent's backend connection.

## Why testing didn't catch it

- **The CI Docker job tested a different runtime.** It ran the Docker image with
  `gunicorn --config gunicorn.conf.py app:app`, on Python 3.13. Render's default Python environment
  variables don't exist inside that container, so there was no `--preload`. The job tested the planned
  Docker deployment, not the native runtime production actually runs today.
- **The local start-command checks tested the command, not the environment.** Before the merge, `gunicorn
  app:app`, `gunicorn app:app --bind …` and `python app.py` were each started on Python 3.11 and probed.
  None set `GUNICORN_CMD_ARGS`, because Render's default environment variables weren't checked. The
  pre-merge advice ("no new Render environment variable is needed") rested on those checks, and was wrong.
- **A leftover directory would have hidden it anyway.** `/tmp/zunoot-prometheus` already existed on the
  test machine from earlier gunicorn runs. Even a preloaded run would have passed. Only a fresh machine
  shows the bug.

## Fix (PR #3)

- `observability/metrics.py` creates the multi-process directory before defining any metric, whatever
  started the app.
- Stale metric files are cleared exactly once per gunicorn master, when `gunicorn.conf.py` loads. That
  happens before a `--preload` import. Workers never clear the directory, and neither does a config reload.
- A `post_fork` hook disposes the inherited SQLAlchemy pool in each worker (`dispose(close=False)`), so each
  worker opens its own database connections.
- New CI job `render-native` runs production's real conditions twice: Python 3.14.3, a
  requirements-only build, an empty `/tmp`, Render's default environment including
  `GUNICORN_CMD_ARGS`, and `gunicorn app:app`. One run uses Render's defaults, the other no preload. Each
  boots, probes `/livez`, `/healthz` and the landing page, checks the metrics count only that run's
  requests, then restarts with stale metric files left behind. Against the pre-fix code it fails with
  the same `FileNotFoundError` production hit.

## Action items

| Item | Status |
|---|---|
| Fix the boot crash and the inherited-connection problem | PR #3 |
| CI job that reproduces Render's native runtime and environment | PR #3 |
| Add `render-native (render-defaults)` and `render-native (no-preload)` to the required checks on `main` | Owner (SETUP_CHECKLIST §1.2) |
| Pin `PYTHON_VERSION` on Render to the version CI tests (3.14.3), so the two can't drift | Owner, optional |
| Return the start command to `gunicorn app:app` after PR #3 is deployed | Owner |
| Lesson recorded in OPS_NOTES.md: test the platform's *environment*, not just the start command | PR #3 |
