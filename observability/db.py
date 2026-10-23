"""Database instrumentation.

Two paths reach Postgres:
 1. backend/queries.py: raw psycopg2, one new connection per call.
    queries.database() calls connect() below, which times the connection and
    installs a cursor class that times every execute().
 2. Flask-Session's SQLAlchemy store (session load/save on each request with a
    cookie), instrumented with SQLAlchemy engine events.

Both add to the current request's RequestStats (queries, connections, DB time),
which the middleware turns into per-request histograms. Those per-request
counts are what make an N+1 query pattern visible on a dashboard.
"""

import sys
import time

import psycopg2
import psycopg2.extensions

from . import context
from .metrics import DB_CONNECT_LATENCY, DB_ERRORS, DB_QUERY_LATENCY


def _record(query, seconds, error=None):
    DB_QUERY_LATENCY.labels(query).observe(seconds)
    stats = context.get()
    if stats is not None:
        stats.db_queries += 1
        stats.db_seconds += seconds
    if error is not None:
        DB_ERRORS.labels(query, type(error).__name__).inc()
        if stats is not None:
            stats.db_errors += 1


class InstrumentedCursor(psycopg2.extensions.cursor):
    """psycopg2 cursor that times execute(), labelled by the calling function."""

    def execute(self, query, vars=None):
        # Frame 1 is the function that called cursor.execute(), e.g.
        # "get_children" or "push_deck". It is a bounded set of names, so it is
        # safe as a label. The SQL text is never used as a label.
        caller = sys._getframe(1).f_code.co_name
        started = time.perf_counter()
        try:
            result = super().execute(query, vars)
        except Exception as exc:
            _record(caller, time.perf_counter() - started, exc)
            raise
        _record(caller, time.perf_counter() - started)
        return result


def connect(dsn, **kwargs):
    """Drop-in replacement for psycopg2.connect() with timing and stats."""
    kwargs.setdefault("cursor_factory", InstrumentedCursor)
    started = time.perf_counter()
    try:
        return psycopg2.connect(dsn, **kwargs)
    finally:
        elapsed = time.perf_counter() - started
        DB_CONNECT_LATENCY.observe(elapsed)
        stats = context.get()
        if stats is not None:
            stats.db_connects += 1
            stats.db_seconds += elapsed


def instrument_sqlalchemy(engine, label="flask_session"):
    from sqlalchemy import event

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, ctx, executemany):
        conn.info.setdefault("zunoot_query_start", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, ctx, executemany):
        started = conn.info["zunoot_query_start"].pop()
        _record(label, time.perf_counter() - started)

    @event.listens_for(engine, "handle_error")
    def _error(exception_context):
        conn = exception_context.connection
        starts = conn.info.get("zunoot_query_start") if conn is not None else None
        started = starts.pop() if starts else time.perf_counter()
        _record(label, time.perf_counter() - started, exception_context.original_exception)
