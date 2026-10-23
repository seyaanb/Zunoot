"""Observability for Zunoot: metrics, structured logs and request IDs.

Wired up in app.py with a single call, init_app(app, db). See OPS_NOTES.md for
the design and the trade-offs.

Imports are kept inside init_app on purpose. gunicorn's master process imports
observability.logs (for its JSON log formatter) before forking workers, and
must not import prometheus_client as a side effect.
"""

import os


def _version():
    return os.environ.get("RENDER_GIT_COMMIT", os.environ.get("GIT_SHA", "dev"))[:12]


def init_app(app, db=None):
    from flask import request

    from . import context, logs
    from .db import instrument_sqlalchemy
    from .metrics import BUILD_INFO
    from .middleware import ObservabilityMiddleware

    logs.configure()
    BUILD_INFO.labels(_version()).set(1)

    app.wsgi_app = ObservabilityMiddleware(app.wsgi_app)

    # Record the matched URL rule as the route label. This must run before any
    # other before_request hook: the login check returns a redirect early, and
    # a hook that returns a response stops the hooks after it from running.
    def _tag_route():
        stats = context.get()
        if stats is not None and request.url_rule is not None:
            stats.route = request.url_rule.rule

    app.before_request_funcs.setdefault(None, []).insert(0, _tag_route)

    if db is not None:
        with app.app_context():
            instrument_sqlalchemy(db.engine)
