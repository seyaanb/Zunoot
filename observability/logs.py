"""Structured JSON logging with a request ID on every line.

Every log record, whether from the app, Flask, gunicorn or a library, goes
through one handler on the root logger and is written to stdout as a single
JSON object. Render captures stdout. The request ID comes from the
per-request context, so any line logged while handling a request carries it,
including lines from code that knows nothing about requests. Lines logged
outside a request (startup, gunicorn master) have request_id "-".

The handler also feeds the zunoot_handled_errors_total metric. A record at
ERROR or above that carries a traceback (logger.exception) means the app
caught a failure, so the request is counted as failed for the availability SLI
even if the user was redirected with a friendly message.
"""

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone

from . import context

_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record):
        stats = context.get()
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": stats.request_id if stats else "-",
        }
        # Fields passed with logger.info("...", extra={...}) become top-level keys.
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_") and key not in entry:
                entry[key] = value
        if record.exc_info:
            entry["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            entry["exc"] = "".join(traceback.format_exception(*record.exc_info)).rstrip()
        return json.dumps(entry, default=str)


class HandledErrorCounter(logging.Filter):
    """Counts logged exceptions against the current request (never drops records)."""

    def filter(self, record):
        if record.levelno >= logging.ERROR and record.exc_info:
            stats = context.get()
            if stats is not None:
                stats.handled_errors += 1
                from .metrics import HANDLED_ERRORS
                HANDLED_ERRORS.labels(stats.route).inc()
        return True


def configure(level=None):
    """Route all logging to one JSON handler on stdout. Safe to call repeatedly."""
    level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(HandledErrorCounter())
    handler.set_name("zunoot-json")

    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if h.get_name() != "zunoot-json"]
    root.addHandler(handler)
    root.setLevel(level)

    # gunicorn and Flask attach their own handlers; send their records to the
    # root handler instead so every line has the same shape.
    for name in ("gunicorn.error", "gunicorn.access", "flask.app", "app"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True


# gunicorn's logconfig_dict (gunicorn.conf.py) references this so the master
# process's own lines are JSON too.
GUNICORN_LOGCONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "observability.logs.JsonFormatter"}},
    "handlers": {
        "stdout": {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stdout"},
    },
    "root": {"level": "INFO", "handlers": ["stdout"]},
    "loggers": {
        "gunicorn.error": {"level": "INFO", "handlers": [], "propagate": True},
        "gunicorn.access": {"level": "WARNING", "handlers": [], "propagate": True},
    },
}
