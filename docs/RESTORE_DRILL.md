# Backups and the restore drill

## What exists

| | |
|---|---|
| **What** | Nightly `pg_dump` (custom format) of the production database |
| **When** | 03:17 UTC daily (`.github/workflows/backup.yml`), plus on demand |
| **Verified** | Every backup is restored into a throwaway Postgres inside the job, and its per-table row counts are recorded in a manifest. A dump that can't be restored fails the job. |
| **Encrypted** | `age`, to a public key. The private key is kept offline (password manager + printed copy). The bucket and the CI token alone can't read user data. |
| **Where** | S3-compatible bucket: `daily/YYYY/MM/…`, `monthly/YYYY/…` (1st of each month), `latest.manifest.json` |
| **Retention** | Bucket lifecycle rules: `daily/` 35 days, `monthly/` 400 days. Enforced by the storage provider, so a broken job can't delete backups, and the job's credentials don't need delete rights. |
| **Monitoring** | healthchecks.io dead man's switch: emails if no successful backup within 26 h. That includes GitHub silently disabling the schedule after 60 days without repo activity. GitHub also emails on a failed run. |
| **RPO** | ≤ 24 h from these backups. ≤ minutes for mistakes noticed within 6 h, via Neon's point-in-time restore. |
| **RTO** | **Measured by the drill below.** Target: under 30 minutes to a working app on restored data. |

Two different tools for two different failures:
- **"I ran a bad UPDATE ten minutes ago"** → Neon point-in-time restore (free tier keeps 6 hours of
  history). Faster and more precise. Neon console → Branches → Restore.
- **"The Neon project is gone / corrupted / the account is locked / the mistake is days old"** → these
  backups. They live with a different provider, under a different account, which is the point.

## Take an on-demand backup

GitHub → **Actions** → **Nightly backup** → **Run workflow** → branch `main` → **Run workflow**. Takes about
2 minutes. Do this before any risky manual operation, e.g. `db/repairs/001_guild_member_counts.sql`.

---

## The restore drill

Run this **once a quarter**, and **now**, to get the restore-time number for your CV. Nothing in this drill
touches production data: it restores into a new, empty database on a separate Neon branch, and
`restore.sh` refuses to run against the production host or any non-empty database.

### One-time prerequisites

1. Tools on your laptop:
   - macOS: `brew install age awscli libpq && brew link --force libpq` (gives `pg_restore`/`psql` 18)
   - Windows: use WSL (Ubuntu), then `sudo apt install age awscli` and the PostgreSQL 18 client from
     https://www.postgresql.org/download/linux/ubuntu/
   - Check: `pg_restore --version` must be **≥ production's Postgres major version** (Neon console →
     project → Settings shows it).
2. The **age private key** file (from SETUP_CHECKLIST.md §5.2), e.g. `~/zunoot-backup-key.txt`.
3. Read-only bucket credentials (SETUP_CHECKLIST.md §5.4, the "restore" token).
4. In a terminal (values from the checklist; this shell only, never committed):
   ```bash
   export S3_BUCKET=zunoot-backups
   export S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
   export AWS_ACCESS_KEY_ID=<restore token id>  AWS_SECRET_ACCESS_KEY=<restore token secret>
   export AWS_DEFAULT_REGION=auto
   export ZUNOOT_PROD_HOST=<production host, e.g. ep-xxxx.eu-central-1.aws.neon.tech>
   ```

### Procedure (time it)

Start a stopwatch at step 1. Write down the clock time at each ✱.

1. ✱ **T0 — decide to restore.**
2. **Create an empty target.** Neon console → your project → **Branches** → **New branch**: name
   `drill-<date>`, parent `main` → Create. Then on that branch: **Databases** → **New database** →
   name `restore_target`. Copy its **direct** (not pooled) connection string from **Connect**.
   *(A new branch costs nothing until used, and doesn't touch `main`'s data. The new database on it is empty.)*
3. ✱ **Run the restore:**
   ```bash
   scripts/backup/restore.sh latest \
     --target "postgresql://...restore_target?sslmode=require" \
     --identity ~/zunoot-backup-key.txt
   ```
   It shows which backup it picked, checks the checksum, decrypts, restores in one transaction, compares
   every table's row count with the manifest, and prints a timing breakdown. **Save that output.**
4. ✱ **Point staging at the restored data.** Render → `zunoot-staging` → Environment → set `DATABASE_URL`
   to the `restore_target` connection string (the **pooled** one is fine for the app) → Save (Render
   redeploys).
5. ✱ **App serving restored data:** `https://zunoot-staging.onrender.com/healthz` returns
   `"status":"ok"`, and you can log in to staging with **your own** account and see your library.
   **Stop the stopwatch.**
6. **Clean up:** set staging's `DATABASE_URL` back to the staging branch, then delete the `drill-<date>`
   branch in Neon. Delete the local decrypted files if you kept any (the script uses a temp dir that it
   removes itself).

### Record the result

Copy this into the table below (newest first) and commit it:

| Date | Backup restored (age) | restore.sh total | T0 → app serving | Rows (students / flashcards) | Problems found |
|---|---|---|---|---|---|
| *YYYY-MM-DD* | *zunoot-…Z (≈ N h old)* | *e.g. 14.2 s* | *e.g. 9 min 40 s* | *18 / 1,5xx* | *e.g. "pg_restore 16 too old, upgraded"* |

**For the CV, quote the end-to-end time (T0 → app serving)**, and say what it includes. "Restore-tested
nightly backups; measured end-to-end recovery of 9m40s in a quarterly drill" is honest and specific.
`restore.sh total` alone is only the data step.

### What a drill typically finds (and why it's worth doing)

Expect at least one of these the first time. Finding them during a drill rather than an outage is the
purpose:
- a client tool older than the server (`pg_restore: unsupported version in file header`)
- the private key isn't where you thought it was
- bucket credentials that can write but not read
- an extension or role in the dump that the target doesn't have (`--no-owner --no-privileges` covers the
  usual Neon roles)

If the drill fails, that's a successful drill. Fix the cause, note it in "Problems found", and run it again.
