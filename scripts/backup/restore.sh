#!/usr/bin/env bash
# Restore a Zunoot backup into a target database and verify it.
#
#   scripts/backup/restore.sh <backup> --target <DATABASE_URL> --identity <age-key-file> [options]
#
# <backup> is one of:
#   latest                       newest backup in S3_BUCKET (via latest.manifest.json)
#   daily/2026/10/zunoot-....dump.age    an object key in S3_BUCKET
#   ./path/zunoot-....dump.age   a local file (its .manifest.json must sit next to it)
#
# Options:
#   --yes                skip the interactive confirmation
#   --allow-production   required if the target looks like production (see below)
#
# Safety:
#  - refuses a target whose host matches ZUNOOT_PROD_HOST (set it to your Neon
#    production host) unless --allow-production is given AND confirmed
#  - refuses a non-empty target (restore into a fresh database or Neon branch)
#  - verifies the file's sha256 against the manifest before decrypting
#  - restores in one transaction: it either all lands or nothing does
#  - checks every table's row count against the manifest afterwards
#
# Prints a timing breakdown at the end. Its "total" line is the restore time
# (RTO) figure the restore drill records (docs/RESTORE_DRILL.md).

set -Eeuo pipefail

die() { echo "restore: ERROR: $*" >&2; exit 1; }
log() { echo "restore: $(date -u +%H:%M:%S) $*" >&2; }
now() { date +%s.%N; }
elapsed() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.1f", b - a }'; }

backup=""; target=""; identity=""; assume_yes=0; allow_prod=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) target="$2"; shift 2 ;;
    --identity) identity="$2"; shift 2 ;;
    --yes) assume_yes=1; shift ;;
    --allow-production) allow_prod=1; shift ;;
    -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
    -*) die "unknown option $1" ;;
    *) [[ -z "$backup" ]] || die "only one backup argument"; backup="$1"; shift ;;
  esac
done
[[ -n "$backup" ]] || die "which backup? (latest, an S3 key, or a local file)"
[[ -n "$target" ]] || die "--target <DATABASE_URL> is required"
[[ -n "$identity" && -r "$identity" ]] || die "--identity <age private key file> is required and must be readable"
for tool in pg_restore psql age sha256sum python3; do
  command -v "$tool" >/dev/null || die "missing tool: $tool"
done

target_host="$(python3 -c 'import sys,urllib.parse as u; print(u.urlparse(sys.argv[1]).hostname or "")' "$target")"
target_db="$(python3 -c 'import sys,urllib.parse as u; print(u.urlparse(sys.argv[1]).path.lstrip("/"))' "$target")"

# --- safety checks -----------------------------------------------------------
if [[ -n "${ZUNOOT_PROD_HOST:-}" && "$target_host" == "$ZUNOOT_PROD_HOST" ]]; then
  [[ "$allow_prod" == 1 ]] || die "target host $target_host is PRODUCTION. Restore into a new Neon branch or a local database instead. (Overriding needs --allow-production.)"
  echo "!!! You are about to restore over PRODUCTION ($target_host/$target_db)." >&2
  read -r -p "Type the database name to confirm: " typed
  [[ "$typed" == "$target_db" ]] || die "confirmation did not match; nothing changed"
fi
if [[ -z "${ZUNOOT_PROD_HOST:-}" ]]; then
  log "warning: ZUNOOT_PROD_HOST is not set, so the production-target guard is off"
fi

tables="$(psql "$target" -XAtqc "select count(*) from pg_tables where schemaname = 'public'")" \
  || die "can't connect to the target database"
[[ "$tables" == "0" ]] || die "target $target_host/$target_db is not empty ($tables tables). Use a fresh database or Neon branch."

if [[ "$assume_yes" != 1 ]]; then
  read -r -p "Restore '$backup' into $target_host/$target_db? [y/N] " ok
  [[ "$ok" == "y" || "$ok" == "Y" ]] || die "cancelled"
fi

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
t_start="$(now)"

# --- fetch ----------------------------------------------------------------------
s3() { aws ${S3_ENDPOINT_URL:+--endpoint-url "$S3_ENDPOINT_URL"} s3 "$@"; }
if [[ -f "$backup" ]]; then
  enc="$backup"
  manifest="${backup%.dump.age}.manifest.json"
  [[ -f "$manifest" ]] || die "manifest not found next to the backup: $manifest"
else
  : "${S3_BUCKET:?set S3_BUCKET (and S3_ENDPOINT_URL / AWS credentials) to restore from object storage}"
  command -v aws >/dev/null || die "missing tool: aws"
  if [[ "$backup" == "latest" ]]; then
    s3 cp --only-show-errors "s3://${S3_BUCKET}/latest.manifest.json" "$workdir/latest.json"
    backup="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["object_key"])' "$workdir/latest.json")"
    log "latest backup is $backup"
  fi
  enc="$workdir/$(basename "$backup")"
  manifest="$workdir/$(basename "${backup%.dump.age}").manifest.json"
  s3 cp --only-show-errors "s3://${S3_BUCKET}/${backup}" "$enc"
  s3 cp --only-show-errors "s3://${S3_BUCKET}/${backup%.dump.age}.manifest.json" "$manifest"
fi
t_fetch="$(now)"

# --- integrity + decrypt ----------------------------------------------------------
expected="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$manifest")"
actual="$(sha256sum "$enc" | cut -d' ' -f1)"
[[ "$expected" == "$actual" ]] || die "sha256 mismatch: file is corrupt or not the one the manifest describes"
log "checksum OK"
dump="$workdir/restore.dump"
age --decrypt --identity "$identity" --output "$dump" "$enc"
t_decrypt="$(now)"

# --- restore --------------------------------------------------------------------
log "restoring into $target_host/$target_db"
pg_restore --no-owner --no-privileges --exit-on-error --single-transaction \
  --dbname="$target" "$dump"
t_restore="$(now)"

# --- verify ---------------------------------------------------------------------
python3 - "$manifest" "$target" <<'PY'
import json, subprocess, sys
manifest, target = sys.argv[1], sys.argv[2]
expected = json.load(open(manifest))["row_counts"]
bad = []
for table, want in sorted(expected.items()):
    got = int(subprocess.check_output(
        ["psql", target, "-XAtqc", f'select count(*) from public."{table}"'], text=True).strip())
    print(f"  {table:<22} {got:>8} rows" + ("" if got == want else f"   EXPECTED {want}"), file=sys.stderr)
    if got != want:
        bad.append(table)
if bad:
    sys.exit(f"restore: ERROR: row counts differ from the manifest for: {', '.join(bad)}")
PY
# A few app-level sanity checks beyond row counts.
psql "$target" -XAtqc "select count(*) from students s where not exists (select 1 from purchases p where p.username = s.username)" \
  | { read -r n; [[ "$n" == "0" ]] || log "note: $n students own no shop items (unexpected for real accounts)"; }
psql "$target" -XAtqc "select 1 from flashcards f left join topics t using (topic_id) where t.topic_id is null limit 1" \
  | { read -r orphan || true; [[ -z "$orphan" ]] || die "orphaned flashcards found: referential integrity is broken"; }
t_verify="$(now)"

cat >&2 <<EOF

restore: SUCCESS  $(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(m["name"], "taken", m["created_at"])' "$manifest")
  fetch      $(elapsed "$t_start" "$t_fetch")s
  decrypt    $(elapsed "$t_fetch" "$t_decrypt")s
  restore    $(elapsed "$t_decrypt" "$t_restore")s
  verify     $(elapsed "$t_restore" "$t_verify")s
  total      $(elapsed "$t_start" "$t_verify")s
EOF
