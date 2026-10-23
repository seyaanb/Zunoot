"""Gunicorn configuration (production and docker-compose).

Concurrency model: a small number of processes, each with a few threads
(gthread). The app spends most of each request waiting on Postgres (Neon is a
network hop away), so threads give concurrency cheaply; processes give
isolation and use more than one core when the plan has one. Defaults suit
Render's 512 MB instances and can be tuned without a rebuild via
WEB_CONCURRENCY / GUNICORN_THREADS.
"""

import os
import shutil

# Prometheus multi-process mode: each worker writes its metric values to files
# in this directory, and /metrics merges them. Set here, in the master, before
# any worker starts or imports prometheus_client.
os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", "/tmp/zunoot-prometheus")

bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))

# A request that takes longer than this is stuck (e.g. a hung DB socket); kill
# the worker rather than let it hold a thread forever.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
# On deploy, Render sends SIGTERM; let in-flight requests finish.
graceful_timeout = 25
keepalive = 5

# Render terminates TLS at its proxy, so trust its X-Forwarded-* headers.
forwarded_allow_ips = "*"

# No preload: app.py opens DB connections at import, and connections must not be
# shared across forked workers.
preload_app = False

# Access logging is done by the app itself as structured JSON (one line per
# request, with request ID and timings), so gunicorn's own access log is off.
# gunicorn's own lines (boot, worker timeouts) use the same JSON formatter.
accesslog = None
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
logconfig_dict = __import__("observability.logs", fromlist=["GUNICORN_LOGCONFIG"]).GUNICORN_LOGCONFIG


def on_starting(server):
    """Start each boot with an empty metrics directory (stale files from a
    previous run would be merged into the new process's counters)."""
    path = os.environ["PROMETHEUS_MULTIPROC_DIR"]
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)


def child_exit(server, worker):
    """Tell prometheus_client a worker is gone, so its live gauges stop
    counting. Its counters are kept; they are still part of the totals."""
    from prometheus_client import multiprocess
    multiprocess.mark_process_dead(worker.pid)
