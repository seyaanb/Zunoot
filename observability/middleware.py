"""WSGI middleware: request IDs, request metrics and one JSON access-log line
per request.

It wraps Flask from the outside, so it sees the response gunicorn actually
sends: the final status code and the full time, including Flask-Session
loading and saving the session. An after_request hook would miss failures that
happen after it runs. BUG-1 (docs/BUGFIXES.md) was exactly that: the error
happened while the session was being saved, after the view had returned 200.
"""

import logging
import time

from . import context
from .metrics import (
    DB_CONNECTS_PER_REQUEST, DB_QUERIES_PER_REQUEST, DB_TIME_PER_REQUEST,
    HTTP_IN_FLIGHT, HTTP_LATENCY, HTTP_REQUESTS,
)

access_log = logging.getLogger("zunoot.access")

# Probes are hit every few seconds; count them in metrics but don't log each one.
QUIET_ROUTES = {"/livez", "/metrics"}


class ObservabilityMiddleware:
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        stats = context.RequestStats(request_id=context.new_request_id(environ.get("HTTP_X_REQUEST_ID")))
        token = context.current.set(stats)
        environ["zunoot.stats"] = stats
        captured = {"status": 500}

        def _start_response(status, headers, exc_info=None):
            captured["status"] = int(status.split(" ", 1)[0])
            headers = [(k, v) for k, v in headers if k.lower() != "x-request-id"]
            headers.append(("X-Request-ID", stats.request_id))
            return start_response(status, headers, exc_info)

        started = time.perf_counter()
        HTTP_IN_FLIGHT.inc()
        try:
            return self.wsgi_app(environ, _start_response)
        finally:
            elapsed = time.perf_counter() - started
            HTTP_IN_FLIGHT.dec()
            self._record(environ, stats, captured["status"], elapsed)
            context.current.reset(token)

    @staticmethod
    def _record(environ, stats, status, elapsed):
        method = environ.get("REQUEST_METHOD", "GET")
        if method not in ("GET", "POST", "HEAD", "PUT", "DELETE", "PATCH", "OPTIONS"):
            method = "OTHER"  # keep the label set bounded
        route = stats.route
        failed = status >= 500 or stats.handled_errors > 0

        HTTP_REQUESTS.labels(method, route, str(status), "error" if failed else "ok").inc()
        HTTP_LATENCY.labels(method, route).observe(elapsed)
        DB_QUERIES_PER_REQUEST.labels(route).observe(stats.db_queries)
        DB_CONNECTS_PER_REQUEST.labels(route).observe(stats.db_connects)
        DB_TIME_PER_REQUEST.labels(route).observe(stats.db_seconds)

        if route in QUIET_ROUTES and not failed:
            return
        level = logging.ERROR if status >= 500 else logging.WARNING if failed else logging.INFO
        # The path only, never the query string: search keywords are user content.
        access_log.log(level, "request", extra={
            "method": method,
            "path": environ.get("PATH_INFO", ""),
            "route": route,
            "status": status,
            "outcome": "error" if failed else "ok",
            "duration_ms": round(elapsed * 1000, 1),
            "db_queries": stats.db_queries,
            "db_connects": stats.db_connects,
            "db_ms": round(stats.db_seconds * 1000, 1),
            "handled_errors": stats.handled_errors,
        })
