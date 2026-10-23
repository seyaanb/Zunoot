"""Per-request state shared by the metrics middleware, DB instrumentation and
the log formatter.

A ContextVar (not flask.g) is used because some of the work we want to measure
happens outside Flask's app context: the WSGI middleware wraps Flask, and
Flask-Session saves the session after the request's after_request hooks have
run. gunicorn's gthread workers handle one request per thread, and
ContextVars are per-thread, so requests never see each other's state.
"""

import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass
class RequestStats:
    request_id: str
    route: str = "unmatched"
    db_queries: int = 0
    db_connects: int = 0
    db_seconds: float = 0.0
    db_errors: int = 0
    handled_errors: int = 0


current: ContextVar[RequestStats | None] = ContextVar("zunoot_request_stats", default=None)


def new_request_id(incoming=None):
    """Reuse a caller-supplied X-Request-ID if it is safe to log, else mint one.

    Honouring an upstream ID lets one ID follow a request across services (or
    from a k6 run into the logs). It is validated because it is copied into
    every log line and a response header.
    """
    if incoming and _REQUEST_ID_RE.match(incoming):
        return incoming
    return uuid.uuid4().hex


def get():
    return current.get()
