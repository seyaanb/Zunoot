"""Prometheus metric definitions and the /metrics exposition.

Naming follows Prometheus conventions: a `zunoot_` namespace, base units
(seconds), `_total` for counters.

Label cardinality is bounded on purpose. `route` is the URL *rule*
("/library/<subject_name>"), never the raw path, so user-chosen names never
become labels. `query` is the name of the function in backend/queries.py that
ran the SQL (about 70 values). In total this exports roughly 2-3k series, well
inside Grafana Cloud's free tier.

Multi-process: gunicorn runs several worker processes, each with its own
counters. With PROMETHEUS_MULTIPROC_DIR set (gunicorn.conf.py does this),
prometheus_client writes each process's values to mmap files there and
/metrics aggregates them, so a scrape sees the whole instance rather than
whichever worker happened to answer.
"""

import os

from .multiproc import ensure_dir

# Must run before the first metric below is defined: in multi-process mode,
# defining a Gauge opens a file in PROMETHEUS_MULTIPROC_DIR straight away.
ensure_dir()

from prometheus_client import (  # noqa: E402
    CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest,
)
from prometheus_client import multiprocess  # noqa: E402

# Buckets include the SLO thresholds (0.5 s internal target, 1 s SLO) so
# "fraction of requests under the threshold" is exact rather than interpolated.
REQUEST_BUCKETS = (0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.5, 5.0, 10.0)
DB_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)
COUNT_BUCKETS = (0, 1, 2, 3, 5, 10, 20, 50, 100, 200)

HTTP_REQUESTS = Counter(
    "zunoot_http_requests_total",
    "HTTP requests by route template, method, status code and outcome. "
    "outcome='error' means the request failed: a 5xx, OR the app logged an "
    "exception while handling it (most routes catch errors and redirect, so the "
    "status code alone would hide failures).",
    ["method", "route", "status", "outcome"],
)
HTTP_LATENCY = Histogram(
    "zunoot_http_request_duration_seconds",
    "Server-side request latency, measured around the whole WSGI app "
    "(includes session load/save).",
    ["method", "route"],
    buckets=REQUEST_BUCKETS,
)
HTTP_IN_FLIGHT = Gauge(
    "zunoot_http_requests_in_flight",
    "Requests currently being handled.",
    multiprocess_mode="livesum",
)
HANDLED_ERRORS = Counter(
    "zunoot_handled_errors_total",
    "Exceptions the app caught and logged (logger.exception) instead of raising.",
    ["route"],
)

DB_QUERY_LATENCY = Histogram(
    "zunoot_db_query_duration_seconds",
    "Time to execute one SQL statement, by the backend/queries.py function that issued it "
    "('flask_session' for session storage).",
    ["query"],
    buckets=DB_BUCKETS,
)
DB_ERRORS = Counter(
    "zunoot_db_errors_total",
    "SQL statements that raised, by query and exception class.",
    ["query", "error"],
)
DB_CONNECT_LATENCY = Histogram(
    "zunoot_db_connect_duration_seconds",
    "Time to open a new Postgres connection (TCP + TLS + auth).",
    buckets=DB_BUCKETS,
)
DB_QUERIES_PER_REQUEST = Histogram(
    "zunoot_db_queries_per_request",
    "SQL statements issued while handling one request.",
    ["route"],
    buckets=COUNT_BUCKETS,
)
DB_CONNECTS_PER_REQUEST = Histogram(
    "zunoot_db_connections_per_request",
    "New Postgres connections opened while handling one request.",
    ["route"],
    buckets=COUNT_BUCKETS,
)
DB_TIME_PER_REQUEST = Histogram(
    "zunoot_db_time_per_request_seconds",
    "Total time spent connecting to and querying Postgres during one request.",
    ["route"],
    buckets=REQUEST_BUCKETS,
)

BUILD_INFO = Gauge(
    "zunoot_build_info",
    "Always 1; the version label is the deployed commit.",
    ["version"],
    multiprocess_mode="max",
)


def registry():
    """The registry to expose: aggregated across workers when multi-process."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        reg = CollectorRegistry()
        multiprocess.MultiProcessCollector(reg)
        return reg
    from prometheus_client import REGISTRY
    return REGISTRY


def exposition():
    return generate_latest(registry()), CONTENT_TYPE_LATEST
