"""Generates ops/grafana/zunoot-overview.json (the Grafana dashboard).

The dashboard is generated rather than hand-edited: each panel is a few lines
here, the PromQL sits in one place, and diffs in review are readable. Run:

    python ops/grafana/build_dashboard.py

then commit the regenerated JSON. CI checks the two are in sync. Import the
JSON into Grafana (Dashboards -> New -> Import), see SETUP_CHECKLIST.md.
"""

import json
import pathlib

OUT = pathlib.Path(__file__).with_name("zunoot-overview.json")

DS = {"type": "prometheus", "uid": "${datasource}"}
# Probe, scrape and static-asset traffic is not user traffic: excluded from
# user-facing panels and from the SLIs (same regex as ops/prometheus/rules).
USER = 'job=~"$job", route!~"/static/.*|/metrics|/livez|/healthz|/service-worker.js"'
ALL = 'job=~"$job"'
RI = "$__rate_interval"

_panels = []
_y = 0
_id = 0


def _next_id():
    global _id
    _id += 1
    return _id


def row(title):
    global _y
    _panels.append({"type": "row", "title": title, "id": _next_id(), "collapsed": False,
                    "gridPos": {"h": 1, "w": 24, "x": 0, "y": _y}, "panels": []})
    _y += 1


def panel(kind, title, targets, x, w, h=8, unit=None, description="", options=None,
          field_config=None, new_row=False):
    global _y
    p = {
        "type": kind,
        "title": title,
        "id": _next_id(),
        "datasource": DS,
        "description": description,
        "gridPos": {"h": h, "w": w, "x": x, "y": _y},
        "targets": [
            {"refId": chr(65 + i), "datasource": DS, "expr": expr, "legendFormat": legend,
             **({"instant": True, "range": False} if kind in ("stat", "gauge") else {})}
            for i, (expr, legend) in enumerate(targets)
        ],
        "fieldConfig": {"defaults": {**({"unit": unit} if unit else {}), **(field_config or {})}, "overrides": []},
        "options": options or {},
    }
    _panels.append(p)
    if x + w >= 24:
        _y += h
    return p


def ts(title, targets, x, w, unit=None, description="", stack=False, h=8):
    custom = {"lineWidth": 1, "fillOpacity": 10 if not stack else 60, "showPoints": "never",
              "stacking": {"mode": "normal" if stack else "none"}}
    return panel("timeseries", title, targets, x, w, h=h, unit=unit, description=description,
                 field_config={"custom": custom},
                 options={"legend": {"displayMode": "list", "placement": "bottom"},
                          "tooltip": {"mode": "multi", "sort": "desc"}})


def stat(title, expr, x, w, unit, description="", thresholds=None, decimals=None):
    fc = {"thresholds": {"mode": "absolute", "steps": thresholds or [{"color": "text", "value": None}]},
          "color": {"mode": "thresholds"}}
    if decimals is not None:
        fc["decimals"] = decimals
    return panel("stat", title, [(expr, "")], x, w, h=4, unit=unit, description=description,
                 field_config=fc, options={"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value",
                                           "graphMode": "none", "textMode": "value"})


# ---------------------------------------------------------------------------
row("Overview (selected time range)")
# `or vector(0)`: with zero errors the error sum is an empty vector, not 0, and
# the whole expression would render as "No data" on a perfect day.
stat("Availability", f'1 - ((sum(increase(zunoot_http_requests_total{{{USER}, outcome="error"}}[$__range])) '
     f'or vector(0)) / sum(increase(zunoot_http_requests_total{{{USER}}}[$__range])))',
     0, 4, "percentunit", decimals=3,
     description="Share of user requests that did not fail (no 5xx and no logged exception) over the "
                 "dashboard's time range. Does NOT include time the service was completely down: use the "
                 "uptime monitor for that.",
     thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 0.99},
                 {"color": "green", "value": 0.995}])
stat("p95 latency", f'histogram_quantile(0.95, sum by (le) '
     f'(increase(zunoot_http_request_duration_seconds_bucket{{{USER}}}[$__range])))',
     4, 4, "s", thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 0.5},
                            {"color": "red", "value": 1}])
stat("Requests under 1 s", f'sum(increase(zunoot_http_request_duration_seconds_bucket{{{USER}, le="1.0"}}[$__range])) '
     f'/ sum(increase(zunoot_http_request_duration_seconds_count{{{USER}}}[$__range]))',
     8, 4, "percentunit", decimals=2, description="Latency SLI: share of user requests served in under 1 s.",
     thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 0.95}])
stat("Requests", f'sum(increase(zunoot_http_requests_total{{{USER}}}[$__range]))', 12, 4, "short", decimals=0)
stat("Scrape target up", f'min(up{{{ALL}}})', 16, 4, "none",
     description="1 = Grafana Cloud could scrape /metrics on its last attempt.",
     thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}])
panel("stat", "Deployed version", [(f'max by (version) (zunoot_build_info{{{ALL}}})', "{{version}}")], 20, 4, h=4,
      options={"reduceOptions": {"calcs": ["lastNotNull"]}, "textMode": "name", "colorMode": "none",
               "graphMode": "none"})

row("Traffic and errors")
ts("Requests per second by route", [(f'sum by (route) (rate(zunoot_http_requests_total{{{USER}}}[{RI}]))',
                                     "{{route}}")], 0, 12, "reqps")
ts("Error ratio", [(f'(sum(rate(zunoot_http_requests_total{{{USER}, outcome="error"}}[{RI}])) or vector(0)) '
                    f'/ sum(rate(zunoot_http_requests_total{{{USER}}}[{RI}]))', "error ratio")],
   12, 12, "percentunit",
   description="Failed / all user requests. Failed = 5xx OR the app logged an exception while "
               "handling it (many routes catch errors and redirect, so status codes alone hide failures).")
ts("Responses by status", [(f'sum by (status) (rate(zunoot_http_requests_total{{{USER}}}[{RI}]))', "{{status}}")],
   0, 12, "reqps", stack=True)
ts("Handled exceptions by route", [(f'sum by (route) (rate(zunoot_handled_errors_total{{{ALL}}}[{RI}]))',
                                    "{{route}}")], 12, 12, "short",
   description="Exceptions caught and logged by route handlers. Each one is also a failed request.")

row("Latency")
ts("Latency percentiles (user requests)", [
    (f'histogram_quantile({q}, sum by (le) (rate(zunoot_http_request_duration_seconds_bucket{{{USER}}}[{RI}])))',
     f"p{int(q * 100)}") for q in (0.5, 0.95, 0.99)], 0, 12, "s")
ts("p95 latency by route (top 10)", [
    (f'topk(10, histogram_quantile(0.95, sum by (le, route) '
     f'(rate(zunoot_http_request_duration_seconds_bucket{{{USER}}}[{RI}]))))', "{{route}}")], 12, 12, "s")
panel("heatmap", "Latency distribution", [
    (f'sum by (le) (increase(zunoot_http_request_duration_seconds_bucket{{{USER}}}[{RI}]))', "{{le}}")],
    0, 24, h=8, options={"calculate": False, "yAxis": {"unit": "s"}, "cellGap": 1,
                         "color": {"scheme": "Oranges", "mode": "scheme"}})
_panels[-1]["targets"][0]["format"] = "heatmap"

row("Database")
ts("DB queries per request (avg) by route", [
    (f'sum by (route) (rate(zunoot_db_queries_per_request_sum{{{USER}}}[{RI}])) '
     f'/ sum by (route) (rate(zunoot_db_queries_per_request_count{{{USER}}}[{RI}]))', "{{route}}")],
   0, 12, "short",
   description="If this grows with the size of the user's library, the route has an N+1 query pattern.")
ts("New DB connections per request (avg) by route", [
    (f'sum by (route) (rate(zunoot_db_connections_per_request_sum{{{USER}}}[{RI}])) '
     f'/ sum by (route) (rate(zunoot_db_connections_per_request_count{{{USER}}}[{RI}]))', "{{route}}")],
   12, 12, "short",
   description="Each new connection to Neon is a TCP + TLS + auth handshake. With a connection pool this is ~0.")
ts("Share of request time spent in the database", [
    (f'sum by (route) (rate(zunoot_db_time_per_request_seconds_sum{{{USER}}}[{RI}])) '
     f'/ sum by (route) (rate(zunoot_http_request_duration_seconds_sum{{{USER}}}[{RI}]))', "{{route}}")],
   0, 12, "percentunit")
ts("Connect latency (TCP+TLS+auth)", [
    (f'histogram_quantile({q}, sum by (le) (rate(zunoot_db_connect_duration_seconds_bucket{{{ALL}}}[{RI}])))',
     f"p{int(q * 100)}") for q in (0.5, 0.95)], 12, 12, "s")
ts("Query p95 by function (top 10)", [
    (f'topk(10, histogram_quantile(0.95, sum by (le, query) '
     f'(rate(zunoot_db_query_duration_seconds_bucket{{{ALL}}}[{RI}]))))', "{{query}}")], 0, 12, "s")
ts("DB errors by function", [(f'sum by (query, error) (rate(zunoot_db_errors_total{{{ALL}}}[{RI}]))',
                              "{{query}} {{error}}")], 12, 12, "short")

row("Instance")
ts("Requests in flight", [(f'sum(zunoot_http_requests_in_flight{{{ALL}}})', "in flight")], 0, 12, "short")
ts("Scrape health", [(f'up{{{ALL}}}', "up {{instance}}"),
                     (f'scrape_duration_seconds{{{ALL}}}', "scrape duration {{instance}}")], 12, 12, "short")

DASHBOARD = {
    "title": "Zunoot — service overview",
    "uid": "zunoot-overview",
    "description": "Golden signals, latency, database and instance health for zunoot.onrender.com. "
                   "Generated by ops/grafana/build_dashboard.py.",
    "tags": ["zunoot", "slo"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "editable": True,
    "graphTooltip": 1,
    "refresh": "1m",
    "time": {"from": "now-24h", "to": "now"},
    "templating": {"list": [
        {"name": "datasource", "label": "Data source", "type": "datasource", "query": "prometheus",
         "current": {}, "hide": 0},
        {"name": "job", "label": "Job", "type": "query", "datasource": DS,
         "query": {"query": "label_values(zunoot_build_info, job)", "refId": "job"},
         "definition": "label_values(zunoot_build_info, job)", "refresh": 2, "includeAll": True,
         "multi": True, "allValue": ".+", "current": {"text": "All", "value": "$__all"}, "hide": 0},
    ]},
    "annotations": {"list": [
        {"name": "Deploys", "datasource": DS, "enable": True, "iconColor": "blue",
         "expr": f'changes(max by (version) (zunoot_build_info{{{ALL}}})[2m:]) > 0',
         "titleFormat": "Deploy", "textFormat": "version {{version}}"},
    ]},
    "panels": _panels,
}


def build():
    return json.dumps(DASHBOARD, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.write_text(build())
    print(f"wrote {OUT} ({len(_panels)} panels)")
