"""Metrics, request IDs and structured logs."""

import base64
import json
import logging

import pytest
from prometheus_client import REGISTRY

from backend import queries as q
from observability import context
from observability.logs import JsonFormatter

TOKEN = "test-metrics-token"  # set in conftest.py
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


# --- /metrics access control ---------------------------------------------------

def test_metrics_requires_token(client):
    resp = client.get("/metrics")
    assert resp.status_code == 401
    assert "zunoot_" not in resp.get_data(as_text=True)


def test_metrics_rejects_wrong_token(client):
    assert client.get("/metrics", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_metrics_with_bearer_token(client):
    resp = client.get("/metrics", headers=AUTH)
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/plain")
    assert "zunoot_http_requests_total" in resp.get_data(as_text=True)


def test_metrics_with_basic_auth(client):
    creds = base64.b64encode(f"grafana:{TOKEN}".encode()).decode()
    assert client.get("/metrics", headers={"Authorization": f"Basic {creds}"}).status_code == 200


def test_metrics_disabled_without_configured_token(client, monkeypatch):
    monkeypatch.delenv("METRICS_TOKEN")
    assert client.get("/metrics", headers=AUTH).status_code == 404


def test_metrics_is_never_a_login_redirect(client):
    # Grafana Cloud rejects scrape targets that redirect.
    assert client.get("/metrics").status_code != 302


# --- request metrics ---------------------------------------------------------

def test_route_label_is_the_url_rule_not_the_path(logged_in):
    logged_in.post("/library/", data={"new-subject": "SecretSubjectName"})
    before = sample("zunoot_http_requests_total", method="GET", route="/library/<subject_name>",
                    status="200", outcome="ok")
    assert logged_in.get("/library/SecretSubjectName").status_code == 200
    after = sample("zunoot_http_requests_total", method="GET", route="/library/<subject_name>",
                   status="200", outcome="ok")
    assert after == before + 1
    body = logged_in.get("/metrics", headers=AUTH).get_data(as_text=True)
    assert "SecretSubjectName" not in body  # user content never becomes a label


def test_latency_histogram_and_db_counts_recorded(logged_in):
    labels = dict(method="GET", route="/library/")
    count_before = sample("zunoot_http_request_duration_seconds_count", **labels)
    queries_before = sample("zunoot_db_queries_per_request_sum", route="/library/")
    connects_before = sample("zunoot_db_connections_per_request_count", route="/library/")
    logged_in.get("/library/")
    assert sample("zunoot_http_request_duration_seconds_count", **labels) == count_before + 1
    assert sample("zunoot_db_queries_per_request_sum", route="/library/") > queries_before
    # recorded once per request (with the connection pool, usually as 0 new connections)
    assert sample("zunoot_db_connections_per_request_count", route="/library/") == connects_before + 1


def test_db_query_timing_is_labelled_by_query_function(logged_in):
    before = sample("zunoot_db_query_duration_seconds_count", query="get_children")
    logged_in.get("/library/")
    assert sample("zunoot_db_query_duration_seconds_count", query="get_children") > before
    assert sample("zunoot_db_query_duration_seconds_count", query="flask_session") > 0


def test_unmatched_routes_share_one_label(logged_in):
    # (anonymous requests to unknown paths are redirected to login before routing 404s)
    before = sample("zunoot_http_requests_total", method="GET", route="unmatched", status="404", outcome="ok")
    logged_in.get("/does-not-exist-1")
    logged_in.get("/does-not-exist-2")
    assert sample("zunoot_http_requests_total", method="GET", route="unmatched",
                  status="404", outcome="ok") == before + 2


def test_handled_exception_counts_as_failed_request(logged_in, monkeypatch):
    """Routes catch errors and redirect with a flash message. The request must still
    count as failed, otherwise the availability SLI would never see these."""
    def broken(*a, **k):
        raise RuntimeError("simulated DB failure")
    monkeypatch.setattr(q, "get_children", broken)

    labels = dict(method="GET", route="/library/", status="302", outcome="error")
    before = sample("zunoot_http_requests_total", **labels)
    errors_before = sample("zunoot_handled_errors_total", route="/library/")
    resp = logged_in.get("/library/")
    assert resp.status_code == 302
    assert sample("zunoot_http_requests_total", **labels) == before + 1
    assert sample("zunoot_handled_errors_total", route="/library/") == errors_before + 1


def test_failure_while_saving_session_is_a_500_in_metrics(app, logged_in, monkeypatch):
    """The BUG-1 shape: the view succeeds, then saving the session fails. Only a
    measurement taken outside Flask sees the real status code."""
    def explode(*a, **k):
        raise TypeError("Encoding objects of type X is unsupported")
    monkeypatch.setattr(app.session_interface, "save_session", explode)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        before = sample("zunoot_http_requests_total", method="GET", route="/library/", status="500", outcome="error")
        assert logged_in.get("/library/").status_code == 500
        assert sample("zunoot_http_requests_total", method="GET", route="/library/",
                      status="500", outcome="error") == before + 1
    finally:
        app.config["PROPAGATE_EXCEPTIONS"] = None


# --- request IDs and logs ------------------------------------------------------

def test_every_response_has_a_request_id(client):
    rid = client.get("/livez").headers["X-Request-ID"]
    assert len(rid) == 32


def test_incoming_request_id_is_reused_when_safe(client):
    assert client.get("/livez", headers={"X-Request-ID": "k6-run-42.vu-3"}).headers["X-Request-ID"] == "k6-run-42.vu-3"


@pytest.mark.parametrize("bad", ["has spaces", "x" * 65, "evil\"json", "path/../traversal", "<script>"])
def test_unsafe_request_ids_are_replaced(client, bad):
    rid = client.get("/livez", headers={"X-Request-ID": bad}).headers["X-Request-ID"]
    assert rid != bad and len(rid) == 32


def test_access_log_line_has_request_id_route_and_timings(client, caplog):
    with caplog.at_level(logging.INFO, logger="zunoot.access"):
        resp = client.get("/auth/", headers={"X-Request-ID": "trace-me"})
    record = next(r for r in caplog.records if r.name == "zunoot.access")
    line = json.loads(JsonFormatter().format(record))
    assert resp.headers["X-Request-ID"] == "trace-me"
    assert line["msg"] == "request"
    assert line["route"] == "/auth/"
    assert line["status"] == 200
    assert {"duration_ms", "db_queries", "db_connects", "db_ms", "ts", "level"} <= line.keys()


def test_probe_requests_are_not_access_logged(client, caplog):
    with caplog.at_level(logging.INFO, logger="zunoot.access"):
        client.get("/livez")
    assert not [r for r in caplog.records if r.name == "zunoot.access"]


def test_json_formatter_includes_request_id_and_traceback():
    token = context.current.set(context.RequestStats(request_id="abc123"))
    try:
        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.getLogger("zunoot.test").makeRecord(
                "zunoot.test", logging.ERROR, __file__, 1, "it failed", None, __import__("sys").exc_info())
        line = json.loads(JsonFormatter().format(record))
    finally:
        context.current.reset(token)
    assert line["request_id"] == "abc123"
    assert line["level"] == "error" and line["msg"] == "it failed"
    assert line["exc_type"] == "ValueError" and "boom" in line["exc"]


def test_lines_outside_a_request_have_placeholder_id():
    record = logging.getLogger("x").makeRecord("x", logging.INFO, __file__, 1, "startup", None, None)
    assert json.loads(JsonFormatter().format(record))["request_id"] == "-"


def test_configure_leaves_exactly_one_console_handler():
    """Under gunicorn the root logger already has a stdout handler (logconfig_dict);
    configure() must replace it, not add a second one (every line printed twice)."""
    import sys
    from observability import logs
    root = logging.getLogger()
    pre_existing = logging.StreamHandler(sys.stdout)
    root.addHandler(pre_existing)
    try:
        logs.configure()
        logs.configure()  # idempotent
        consoles = [h for h in root.handlers
                    if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout]
        assert len(consoles) == 1 and consoles[0].get_name() == "zunoot-json"
    finally:
        if pre_existing in root.handlers:
            root.removeHandler(pre_existing)
