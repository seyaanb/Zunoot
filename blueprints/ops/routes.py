"""Operational endpoints: liveness and readiness.

/livez   - "is this process able to serve HTTP?" No dependencies touched.
           Used by Render's health check. Render runs it every few seconds and
           restarts instances that fail it, so it must not depend on the
           database: restarting the web process cannot fix a database outage,
           and a DB-touching check every few seconds would stop Neon's free
           compute from ever scaling to zero.

/healthz - "can this instance actually serve users?" Runs SELECT 1 against
           Postgres with a short timeout. Used by the external uptime monitor
           (every 5 minutes) and by humans. Returns 503 if the DB is unreachable.
"""

import os
import time

import psycopg2
from flask import jsonify

from . import ops_bp

DB_CHECK_TIMEOUT_SECONDS = 3


def _database_url():
    url = os.environ.get("DATABASE_URL")
    if url:
        url = url.strip().strip('"').strip("'")
    return url


def _version():
    # Render injects the deployed commit SHA; fall back for local/dev.
    return os.environ.get("RENDER_GIT_COMMIT", os.environ.get("GIT_SHA", "dev"))[:12]


def check_database():
    """Return (ok, latency_ms, error_class). Never raises."""
    started = time.perf_counter()
    conn = None
    try:
        conn = psycopg2.connect(
            _database_url(),
            connect_timeout=DB_CHECK_TIMEOUT_SECONDS,
            options=f"-c statement_timeout={DB_CHECK_TIMEOUT_SECONDS * 1000}",
            application_name="zunoot-healthz",
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True, round((time.perf_counter() - started) * 1000, 1), None
    except Exception as exc:  # report the class only: messages can leak hostnames
        return False, round((time.perf_counter() - started) * 1000, 1), type(exc).__name__
    finally:
        if conn is not None:
            conn.close()


@ops_bp.route("/livez")
def livez():
    resp = jsonify(status="ok", version=_version())
    resp.headers["Cache-Control"] = "no-store"
    return resp


@ops_bp.route("/healthz")
def healthz():
    ok, latency_ms, error = check_database()
    body = {
        "status": "ok" if ok else "unavailable",
        "version": _version(),
        "checks": {"database": {"ok": ok, "latency_ms": latency_ms}},
    }
    if error:
        body["checks"]["database"]["error"] = error
    resp = jsonify(body)
    resp.status_code = 200 if ok else 503
    resp.headers["Cache-Control"] = "no-store"
    return resp
