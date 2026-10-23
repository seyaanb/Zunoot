"""Gunicorn configuration (production and docker-compose).

Concurrency model: a small number of processes, each with a few threads
(gthread). The app spends most of each request waiting on Postgres (Neon is a
network hop away), so threads give concurrency cheaply; processes give
isolation and use more than one core when the plan has one. Defaults suit
Render's 512 MB instances and can be tuned without a rebuild via
WEB_CONCURRENCY / GUNICORN_THREADS.
"""

import os
import sys

from observability import multiproc

# Prometheus multi-process mode: each process writes its metric values to
# files in this directory, and /metrics merges them. This file is executed by
# the gunicorn master before it imports the app, even with --preload, so this
# is the one place that runs exactly once per server start.
os.environ.setdefault(multiproc.ENV_VAR, multiproc.DEFAULT_DIR)
multiproc.reset_once_per_master()

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

# No preload by default. But note: Render's native Python runtime sets
# GUNICORN_CMD_ARGS="--preload --access-logfile - --bind=0.0.0.0:10000", and
# GUNICORN_CMD_ARGS overrides this file. So the app must also work preloaded:
# see post_fork below, and observability/multiproc.py.
preload_app = False

# Access logging is done by the app itself as structured JSON (one line per
# request, with request ID and timings), so gunicorn's own access log is off.
# gunicorn's own lines (boot, worker timeouts) use the same JSON formatter.
accesslog = None
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
logconfig_dict = __import__("observability.logs", fromlist=["GUNICORN_LOGCONFIG"]).GUNICORN_LOGCONFIG


def on_starting(server):
    """The directory was emptied when this file loaded (before any --preload
    import). Only make sure it still exists; deleting files here would remove
    the ones a preloaded app has already written."""
    multiproc.ensure_dir()


def post_fork(server, worker):
    """With --preload, the master imported app.py, which opened a pooled
    database connection (db.create_all()). Every worker inherits that same
    socket; two processes talking over one TLS connection corrupt each other's
    traffic. Drop the inherited pool in each worker without closing the
    parent's sockets (SQLAlchemy's documented approach for forking), so each
    worker opens its own connections."""
    app_module = sys.modules.get("app")
    if app_module is not None and hasattr(app_module, "db"):
        with app_module.app.app_context():
            app_module.db.engine.dispose(close=False)


def child_exit(server, worker):
    """Tell prometheus_client a worker is gone, so its live gauges stop
    counting. Its counters are kept; they are still part of the totals."""
    from prometheus_client import multiprocess
    multiprocess.mark_process_dead(worker.pid)
