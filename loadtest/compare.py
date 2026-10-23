"""Compare two k6 summaries (before/after a change) as a Markdown table.

    python loadtest/compare.py loadtest/results/summary-before.json loadtest/results/summary-after.json

Paste the output into the PR description and into docs/PERFORMANCE.md.
"""

import json
import sys

PAGES = ["login", "library", "subject", "topic", "review_start", "review_rate", "review_end",
         "guild", "shop", "community", "search"]


def load(path):
    m = json.load(open(path))["metrics"]

    def trend(key, stat):
        v = m.get(key, {}).get("values", {})
        return v.get(stat)

    reqs = m.get("http_reqs{phase:main}", m.get("http_reqs", {})).get("values", {})
    failed = m.get("http_req_failed{phase:main}", {}).get("values", {}).get("rate")
    out = {
        "requests": reqs.get("count"),
        "req/s": reqs.get("rate"),
        "p50 (ms)": trend("http_req_duration{phase:main}", "med"),
        "p95 (ms)": trend("http_req_duration{phase:main}", "p(95)"),
        "p99 (ms)": trend("http_req_duration{phase:main}", "p(99)"),
        "failed %": failed * 100 if failed is not None else None,
    }
    pages = {p: trend(f"http_req_duration{{name:{p},phase:main}}", "p(95)") for p in PAGES}
    return out, pages


def fmt(v, digits=0):
    return "–" if v is None else f"{v:,.{digits}f}"


def change(a, b):
    if a in (None, 0) or b is None:
        return ""
    pct = (b - a) / a * 100
    return f"{pct:+.0f}%"


def main(before_path, after_path):
    (b, bp), (a, ap) = load(before_path), load(after_path)
    print("| metric | before | after | change |\n|---|---:|---:|---:|")
    for k in b:
        digits = 2 if k in ("req/s", "failed %") else 0
        print(f"| {k} | {fmt(b[k], digits)} | {fmt(a[k], digits)} | {change(b[k], a[k])} |")
    print("\n| page | p95 before (ms) | p95 after (ms) | change |\n|---|---:|---:|---:|")
    for p in PAGES:
        if bp[p] is not None or ap[p] is not None:
            print(f"| {p} | {fmt(bp[p])} | {fmt(ap[p])} | {change(bp[p], ap[p])} |")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
