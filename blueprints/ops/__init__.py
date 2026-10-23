from flask import Blueprint

ops_bp = Blueprint("ops", __name__)

# Endpoints that must work without a login session. They are exempted from the
# app-wide login redirect in blueprints/auth/routes.py, and they must never
# redirect: uptime monitors and Prometheus scrapers treat a 302 to /auth/login
# as a pass (uptime) or reject it outright (Grafana Cloud).
PUBLIC_ENDPOINTS = ("ops.livez", "ops.healthz", "ops.metrics")

from . import routes  # noqa: E402,F401
