#!/usr/bin/env bash
# Nightly logical backup of the Zunoot database.
#
#   1. pg_dump (custom format) from SOURCE_DATABASE_URL, read-only
#   2. restore the dump into an EMPTY scratch database (VERIFY_DATABASE_URL)
#      and record per-table row counts: a backup that has never been restored
#      is a hope, not a backup
#   3. encrypt with age to AGE_RECIPIENT (public key; the private key is kept
#      offline, so a leaked bucket or CI token can't expose user data)
#   4. upload the encrypted dump plus a JSON manifest to S3-compatible storage
#      (or only write them to OUTPUT_DIR if S3_BUCKET is unset)
#
# Retention is NOT handled here: bucket lifecycle rules expire daily/ objects
# after 35 days and monthly/ objects after 400 days, so this job's credentials
# never need delete permission. See docs/RESTORE_DRILL.md.
#
# Required env:
#   SOURCE_DATABASE_URL  database to back up (use a read-only role)
#   VERIFY_DATABASE_URL  EMPTY scratch database for the test restore
#   AGE_RECIPIENT        age public key (age1...)
# Optional env:
#   S3_BUCKET, S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
#   AWS_DEFAULT_REGION (R2: "auto")
#   OUTPUT_DIR  (default ./backup-out)
#   MONTHLY     "1" to also keep a monthly copy (the workflow sets it on the 1st)

set -Eeuo pipefail

die() { echo "backup: ERROR: $*" >&2; exit 1; }
log() { echo "backup: $(date -u +%H:%M:%S) $*" >&2; }
now() { date +%s.%N; }
elapsed() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.1f", b - a }'; }

: "${SOURCE_DATABASE_URL:?set SOURCE_DATABASE_URL}"
: "${VERIFY_DATABASE_URL:?set VERIFY_DATABASE_URL (an empty scratch database)}"
: "${AGE_RECIPIENT:?set AGE_RECIPIENT (age public key)}"
OUTPUT_DIR="${OUTPUT_DIR:-./backup-out}"

for tool in pg_dump pg_restore psql age sha256sum; do
  command -v "$tool" >/dev/null || die "missing tool: $tool"
done
if [[ -n "${S3_BUCKET:-}" ]]; then command -v aws >/dev/null || die "missing tool: aws"; fi

[[ "$SOURCE_DATABASE_URL" != "$VERIFY_DATABASE_URL" ]] || die "VERIFY_DATABASE_URL must not be the source database"
# Neon's pooled endpoint (PgBouncer, transaction mode) doesn't support everything
# pg_dump does; use the direct connection string.
if [[ "$SOURCE_DATABASE_URL" == *"-pooler."* ]]; then
  log "warning: SOURCE_DATABASE_URL is a Neon *pooled* endpoint; use the direct (non -pooler) host for pg_dump"
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
year="${stamp:0:4}"; month="${stamp:4:2}"
name="zunoot-${stamp}"
mkdir -p "$OUTPUT_DIR"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
dump="$workdir/${name}.dump"

# The scratch database must be empty, so the test restore proves the dump is
# self-contained and the row counts come only from the dump.
existing="$(psql "$VERIFY_DATABASE_URL" -XAtqc "select count(*) from pg_tables where schemaname = 'public'")"
[[ "$existing" == "0" ]] || die "VERIFY_DATABASE_URL is not empty ($existing tables in public)"

# 1. dump ---------------------------------------------------------------------
log "dumping source database"
t0="$(now)"
server_version="$(psql "$SOURCE_DATABASE_URL" -XAtqc 'show server_version')"
pg_dump --format=custom --compress=9 --no-owner --no-privileges \
  --file="$dump" "$SOURCE_DATABASE_URL"
t1="$(now)"
dump_bytes="$(stat -c %s "$dump")"
log "dump: ${dump_bytes} bytes in $(elapsed "$t0" "$t1")s (server ${server_version}, $(pg_dump --version))"

# 2. verify by restoring --------------------------------------------------------
log "test-restoring into the scratch database"
pg_restore --no-owner --no-privileges --exit-on-error --single-transaction \
  --dbname="$VERIFY_DATABASE_URL" "$dump"
t2="$(now)"

# Exact row counts per table, from the RESTORED copy: these are what the dump
# really contains, and restore.sh checks a future restore against them.
counts_json="$(psql "$VERIFY_DATABASE_URL" -XAtq <<'SQL'
select coalesce(json_object_agg(table_name, n order by table_name), '{}'::json)
from (
  select c.relname as table_name,
         (xpath('/row/n/text()',
                query_to_xml(format('select count(*) as n from %I.%I', n.nspname, c.relname), false, true, '')))[1]::text::bigint as n
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
  where c.relkind = 'r' and n.nspname = 'public'
) t
SQL
)"
students="$(psql "$VERIFY_DATABASE_URL" -XAtqc 'select count(*) from students' 2>/dev/null || echo 0)"
[[ "$students" -gt 0 ]] || die "sanity check failed: restored copy has no students"
log "verified: restore OK in $(elapsed "$t1" "$t2")s, $students students"

# 3. encrypt ------------------------------------------------------------------
enc="$OUTPUT_DIR/${name}.dump.age"
age --encrypt --recipient "$AGE_RECIPIENT" --output "$enc" "$dump"
sha="$(sha256sum "$enc" | cut -d' ' -f1)"
enc_bytes="$(stat -c %s "$enc")"

daily_key="daily/${year}/${month}/${name}.dump.age"
manifest="$OUTPUT_DIR/${name}.manifest.json"
cat > "$manifest" <<JSON
{
  "name": "${name}",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "object_key": "${daily_key}",
  "sha256": "${sha}",
  "encrypted_bytes": ${enc_bytes},
  "dump_bytes": ${dump_bytes},
  "format": "pg_dump custom, age-encrypted",
  "source_server_version": "${server_version}",
  "pg_dump_version": "$(pg_dump --version | sed -E 's/^pg_dump \(PostgreSQL\) ([0-9.]+).*/\1/')",
  "dump_seconds": $(elapsed "$t0" "$t1"),
  "verify_restore_seconds": $(elapsed "$t1" "$t2"),
  "git_sha": "${GITHUB_SHA:-local}",
  "row_counts": ${counts_json}
}
JSON
log "encrypted: ${enc_bytes} bytes, sha256 ${sha:0:16}..."

# 4. upload -------------------------------------------------------------------
if [[ -n "${S3_BUCKET:-}" ]]; then
  s3() { aws ${S3_ENDPOINT_URL:+--endpoint-url "$S3_ENDPOINT_URL"} s3 "$@"; }
  s3 cp --only-show-errors "$enc" "s3://${S3_BUCKET}/${daily_key}"
  s3 cp --only-show-errors "$manifest" "s3://${S3_BUCKET}/${daily_key%.dump.age}.manifest.json"
  # Pointer to the newest backup, for `restore.sh latest`.
  s3 cp --only-show-errors "$manifest" "s3://${S3_BUCKET}/latest.manifest.json"
  if [[ "${MONTHLY:-0}" == "1" ]]; then
    monthly_key="monthly/${year}/${name}.dump.age"
    s3 cp --only-show-errors "$enc" "s3://${S3_BUCKET}/${monthly_key}"
    s3 cp --only-show-errors "$manifest" "s3://${S3_BUCKET}/${monthly_key%.dump.age}.manifest.json"
    log "monthly copy: ${monthly_key}"
  fi
  log "uploaded s3://${S3_BUCKET}/${daily_key}"
else
  log "S3_BUCKET not set: kept locally in ${OUTPUT_DIR}"
fi

log "done in $(elapsed "$t0" "$(now)")s"
echo "$manifest"
