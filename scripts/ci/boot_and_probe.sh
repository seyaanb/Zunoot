#!/usr/bin/env bash
# Start `gunicorn app:app` exactly as Render's start command does, then check
# the app really serves: /livez, /healthz, the landing page, no tracebacks,
# and metrics that count only this run's requests (stale files were cleared).
# Usage: scripts/ci/boot_and_probe.sh <label>     (used by ci.yml render-native)

set -Eeuo pipefail
label="${1:?label}"
log="gunicorn-${label}.log"
base="http://127.0.0.1:${PORT:-10000}"

# On failure, attach the end of gunicorn's output to the job as an annotation,
# so the cause is visible in the PR's checks view without opening raw logs.
annotate_log() {
  local tail_text
  tail_text="$(tail -n 40 "$log" 2>/dev/null | sed -e 's/%/%25/g' -e 's/\r//g' | awk '{printf "%s%%0A", $0}')"
  echo "::error title=gunicorn output ($label)::${tail_text}"
}
trap 'annotate_log' ERR

.venv/bin/gunicorn app:app >"$log" 2>&1 &
echo $! > gunicorn.pid

for _ in $(seq 1 30); do
  if curl -fsS "$base/livez" >/dev/null 2>&1; then break; fi
  if ! kill -0 "$(cat gunicorn.pid)" 2>/dev/null; then
    echo "::error::gunicorn exited during boot ($label)"; cat "$log"; annotate_log; exit 1
  fi
  sleep 1
done
curl -fsS "$base/livez"; echo
curl -fsS "$base/healthz" | grep -q '"status":"ok"'

for _ in $(seq 1 20); do
  test "$(curl -s -o /dev/null -w '%{http_code}' "$base/auth/")" = 200
done

# 20 landing-page requests in this run: a higher count means metric files
# from a previous run were merged in; a crash in a worker would lose some.
count="$(curl -fsS -H "Authorization: Bearer ${METRICS_TOKEN}" "$base/metrics" \
  | awk '/^zunoot_http_requests_total\{/ && /route="\/auth\/"/ && /status="200"/ {s += $2} END {print s+0}')"
test "$count" = 20 || { echo "::error::expected 20 /auth/ requests in metrics, got $count ($label)"; annotate_log; exit 1; }

kill -0 "$(cat gunicorn.pid)"
if grep -q Traceback "$log"; then
  echo "::error::traceback in gunicorn output ($label)"; cat "$log"; annotate_log; exit 1
fi
echo "OK ($label): booted, /livez /healthz / ok, metrics counted $count requests"
