# Setup checklist

Everything in this PR that needs a human with account access. Do the sections **in order**: later
sections depend on earlier ones. Tick boxes as you go.

Dashboard labels change over time. If a button isn't exactly where described, the surrounding page
will have it under a similar name. Each step says *what* you are setting, so you can find it.

**Cost:** everything below fits free tiers: GitHub Actions, Render Free, Neon Free, Grafana Cloud Free,
Cloudflare R2's free allowance, healthchecks.io, UptimeRobot. §2.9 explains the one decision where paying
$7/month would change the result.

**Touches production data?** Only three steps, and each is marked ⚠️: creating a read-only database role
(§5.5), the guild-count repair (§7), and anything with `ALLOW_PRODUCTION`. Nothing else reads or writes
production rows.

| Secret / setting | Where it lives | Section |
|---|---|---|
| `METRICS_TOKEN` | Render env (prod) + Grafana Cloud scrape job | 2.1, 4.2 |
| `DATABASE_URL`, `SECRET_KEY` | Render env (already set) | — |
| `GRAFANA_SA_TOKEN` (secret), `GRAFANA_URL`, `GRAFANA_PROM_DS_UID` (variables) | GitHub repo | 4.5 |
| `BACKUP_DATABASE_URL`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`, `HEALTHCHECKS_BACKUP_URL` (secrets) | GitHub environment `backups` | 5.7 |
| `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT_URL`, `BACKUP_S3_REGION`, `BACKUP_AGE_RECIPIENT` (variables) | GitHub environment `backups` | 5.7 |
| age **private** key | your password manager + a printed copy. **Never** GitHub, never the bucket | 5.2 |

---

## 1. GitHub

- [ ] **1.1 Merge the PR** after review. CI must be green first: it runs lint, tests, alert-rule tests, a
  backup/restore round trip, a production-image boot, and a k6 smoke test.
  *Merging deploys the bug fixes to production through Render's current (Python) setup. That's
  intended and safe: Render installs the new `requirements.txt` and starts the app as before.*
- [ ] **1.2 Protect `main`.** Settings → **Rules** → **Rulesets** → **New ruleset** → **New branch ruleset**:
  - Name `main`, Enforcement **Active**, Target branches → **Add target** → **Include default branch**
  - Tick **Require a pull request before merging**
  - Tick **Require status checks to pass** → **Add checks** → add `lint`, `lint-infra`, `alert-rules`,
    `test`, `backup-restore`, `docker` (they appear in the list once CI has run on the PR)
  - Tick **Block force pushes** → **Create**
  *(Solo-developer tip: leave "required approvals" at 0, or you can't merge your own PRs.)*
- [ ] **1.3 Create the `backups` environment.** Settings → **Environments** → **New environment** → name
  `backups` → **Configure environment** → **Deployment branches and tags** → **Selected branches and tags**
  → **Add deployment branch or tag rule** → `main`. Secrets for backups go here in §5.7, so a workflow on
  any other branch can't read the production database credentials.

## 2. Render: production service (`zunoot`)

First write down the current settings (Settings page: Build Command, Start Command, Python version), in case
you ever need to go back.

- [ ] **2.1 Generate a metrics token** (keep this terminal open, you need it again in §4):
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- [ ] **2.2 Add environment variables.** (Leave Render's own default `GUNICORN_CMD_ARGS` alone. It adds
  `--preload`, which the app supports, and CI's `render-native` job tests exactly that setup.) Render →
  **zunoot** → **Environment** → **Add Environment Variable**:
  - `METRICS_TOKEN` = the token from 2.1
  - `WEB_CONCURRENCY` = `2`
  - `GUNICORN_THREADS` = `4`

  → **Save, rebuild, and deploy**. *(These are only read by the Docker setup in 2.3, so this deploy behaves
  as before.)*
- [ ] **2.3 Switch the service to Docker.** **Settings** → **Build & Deploy** → **Source** → **Edit**:
  - **Runtime / Language**: `Docker`
  - **Dockerfile Path**: `./Dockerfile`
  - **Docker Build Context Directory**: `.`
  - **Docker Command**: leave **empty** (the image's `CMD` runs gunicorn with `gunicorn.conf.py`)
  - Branch: `main`

  → **Save** / **Deploy**. Watch **Events** and **Logs**: you should see JSON log lines, starting with
  `"msg": "Starting gunicorn …"`.
  *If the build or boot fails, Render keeps serving the previous deploy, because the new one never passes
  its health check. Fix forward, or set Runtime back to Python with your noted commands.*
- [ ] **2.4 Health check.** **Settings** → **Health Checks** → **Health Check Path** → `/livez` → Save.
  *(`/livez`, not `/healthz`: see OPS_NOTES.md, "Why Render checks /livez".)*
- [ ] **2.5 Deploy only after CI passes.** **Settings** → **Build & Deploy** → **Auto-Deploy** →
  **After CI Checks Pass** → Save.
- [ ] **2.6 Verify** (replace `$TOKEN`):
  ```bash
  curl -s https://zunoot.onrender.com/livez        # {"status":"ok","version":"<commit>"}
  curl -s https://zunoot.onrender.com/healthz      # "status":"ok", database ok, latency_ms
  curl -s -o /dev/null -w "%{http_code}\n" https://zunoot.onrender.com/metrics           # 401
  curl -s -H "Authorization: Bearer $TOKEN" https://zunoot.onrender.com/metrics | head  # zunoot_ metrics
  curl -sI https://zunoot.onrender.com/auth/ | grep -i x-request-id                      # a request ID
  ```
  Then log in to the app yourself and **start a review**. This was broken before (BUG-1).
- [ ] **2.7 Optional: manage the service with `render.yaml`.** Only once 2.2–2.5 match the file. Dashboard
  → select `zunoot` → **Generate Blueprint**, compare it with `render.yaml`, fix any differences in the file,
  then **New** → **Blueprint** → this repo. Render must report that it will *update* `zunoot`, not create
  `zunoot-xxxx`. If it says "create", cancel: the names or settings don't match yet.
- [ ] **2.8 Note the production database host** (Neon console → project → **Connect** → the host part, e.g.
  `ep-xxx-yyy.eu-central-1.aws.neon.tech`, *without* `-pooler`). The safety guards in the restore and
  seed scripts use it as `ZUNOOT_PROD_HOST`.
- [ ] **2.9 Decide: stay on Render Free or pay for Starter (~$7/month)?**
  - *Free:* the 1-minute metrics scrape keeps production awake, so users never hit a cold start. That uses
    ≈744 of the workspace's 750 free instance-hours a month, so **staging must stay suspended when not in
    use** (§3.4), or *every* free service, production included, is suspended for the rest of the month.
  - *Starter:* no spin-down, no hour cap, staging can run freely, and zero-downtime deploys are guaranteed.
  Either is defensible in an interview, as long as you can explain the trade-off. The SLOs in `docs/SLO.md`
  assume Free.

## 3. Staging (`zunoot-staging`)

- [ ] **3.1 Neon branch for staging.** Neon console → project → **Branches** → **New branch** → name `staging`,
  parent `main` → **Create**. **Connect** → choose branch `staging` → copy the **pooled** connection string.
  *(A branch is a copy-on-write copy of production's data, so it contains your real users' data. Treat
  staging credentials like production ones.)*
- [ ] **3.2 Render service.** Render → **New** → **Web Service** → this repo → Name `zunoot-staging`, Branch
  `main`, Runtime **Docker**, Instance type **Free** → Environment variables:
  - `DATABASE_URL` = the **staging** branch string from 3.1 (double-check it says `staging`, not `main`)
  - `SECRET_KEY` = a new value (`python3 -c "import secrets; print(secrets.token_hex(32))"`)
  - `METRICS_TOKEN` = a new value (different from production)
  - `WEB_CONCURRENCY` = `2`, `GUNICORN_THREADS` = `4`

  → **Create Web Service**. Then **Settings**: Health Check Path `/livez`; Auto-Deploy **After CI Checks Pass**.
- [ ] **3.3 Verify** `https://zunoot-staging.onrender.com/healthz`.
- [ ] **3.4 Suspend it.** **Settings** → **Suspend Web Service**. Resume it only for load tests and drills, then
  suspend it again. *(Suspended services use no instance-hours. On Starter (§2.9) you can skip this.)*

## 4. Grafana Cloud (metrics, dashboard, alerts)

- [ ] **4.1 Account.** https://grafana.com/auth/sign-up/create-user → free account → create a stack (pick the
  region closest to Render's). Note the stack URL, e.g. `https://yourname.grafana.net`.
- [ ] **4.2 Scrape production.** In your stack: **Connections** → **Add new connection** → **Metrics Endpoint**
  → **Add new scrape job**:
  - Scrape job name: `zunoot` *(the alert rules match jobs containing "zunoot")*
  - Scrape job URL: `https://zunoot.onrender.com/metrics`
  - Scrape interval: **Every minute**
  - Authentication: **Bearer** → paste `METRICS_TOKEN` from 2.1 (without the word "Bearer")
  - **Test connection** → should succeed → **Save scrape job** → **Install** (adds Grafana's own overview)
- [ ] **4.3 Import the dashboard.** **Dashboards** → **New** → **Import** → **Upload dashboard JSON file** →
  `ops/grafana/zunoot-overview.json` → Data source: the one named `grafanacloud-<stack>-prom` → **Import**.
  Panels fill in after a few minutes of scraping. The SLO row needs the recording rules from 4.5–4.6.
- [ ] **4.4 Find the Prometheus data source UID.** **Connections** → **Data sources** → `grafanacloud-<stack>-prom`
  → the URL ends in `/datasources/edit/<UID>`. Copy `<UID>`.
- [ ] **4.5 Service account for publishing alert rules.** **Administration** → **Users and access** →
  **Service accounts** → **Add service account** → name `github-alert-rules`, role **Editor** → **Create** →
  **Add service account token** → no expiry, or 1 year with a calendar reminder → **Generate** → copy it.
  In GitHub: Settings → **Secrets and variables** → **Actions**:
  - **Secrets** tab → New repository secret `GRAFANA_SA_TOKEN` = the token
  - **Variables** tab → `GRAFANA_URL` = your stack URL (no trailing slash), `GRAFANA_PROM_DS_UID` = UID from 4.4
- [ ] **4.6 Publish the rules.** GitHub → **Actions** → **Deploy alert rules** → **Run workflow** (`main`).
  Then in Grafana: **Alerting** → **Alert rules** → folder **zunoot**: 8 alert rules and 16 recording
  rules. (After this, every merge that changes `ops/prometheus/rules/` republishes them.)
- [ ] **4.7 Where alerts go.** **Alerting** → **Contact points** → edit the default (email) → your address →
  **Test** → you receive a test email → **Save**. For phone push: add a contact point for Discord, Telegram
  or Slack, then **Notification policies** → **New child policy**: matcher `severity = page` → that contact
  point.
- [ ] **4.8 Prove an alert reaches you.** Temporarily change `METRICS_TOKEN` in Render (§2.2) to something
  else. Within ~6 minutes `ZunootScrapeFailing` fires and you get notified. Set it back, and the alert
  resolves. Note how long notification took (it's a good number for interviews).
- [ ] **4.9 Know the free-tier limits.** Free Grafana Cloud keeps metrics for **14 days** and allows 10k
  active series (Zunoot uses ~2–3k). The "30-day" SLO panels therefore cover the last 14 days on Free:
  see `docs/SLO.md` → "Measurement limits".
- [ ] *(Only while load-testing staging)* add a second scrape job `zunoot-staging` →
  `https://zunoot-staging.onrender.com/metrics` with staging's token. **Delete or disable it afterwards**:
  a permanent scrape keeps staging awake (§2.9).

## 5. Backups

- [ ] **5.1 Bucket.** Cloudflare → **R2 Object Storage** → **Create bucket** → name `zunoot-backups`, location
  hint closest to you → **Create**. Note the **S3 API** endpoint shown on the bucket's settings page:
  `https://<account-id>.r2.cloudflarestorage.com`.
  *(R2: 10 GB free and no egress fees, so a restore costs nothing. Cloudflare asks for a payment method to
  enable R2. If you'd rather not add one, Backblaze B2 works the same way: create a bucket and an
  application key, and use its S3 endpoint.)*
- [ ] **5.2 Encryption key.** On your laptop (`brew install age`):
  ```bash
  age-keygen -o zunoot-backup-key.txt
  ```
  It prints `Public key: age1…`. That public key goes to GitHub (5.7). The **file** is the private key:
  store its contents in your password manager **and** print it. Then delete the file from your Downloads /
  desktop. Without it, no backup can ever be decrypted. That's the point, and also the risk.
- [ ] **5.3 Retention rules.** R2 → `zunoot-backups` → **Settings** → **Object lifecycle rules** → **Add rule**:
  - `expire-daily`: prefix `daily/` → delete objects after **35 days**
  - `expire-monthly`: prefix `monthly/` → delete objects after **400 days**
  - also enable "abort incomplete multipart uploads after 1 day" if offered
  *(Optional hardening: R2 **Bucket lock rules** with prefix `daily/`, 7 days. Then even a stolen write token
  can't delete the last week of backups.)*
- [ ] **5.4 Two bucket tokens.** R2 → **Manage API tokens** → **Create API token**:
  - `zunoot-backup-writer`: permission **Object Read & Write**, **Apply to specific buckets only** →
    `zunoot-backups` → Create → copy the **Access Key ID** and **Secret Access Key** (shown once)
  - `zunoot-restore-reader`: **Object Read only**, same bucket. This one stays on your laptop for the
    restore drill and never goes to GitHub.
- [ ] **5.5 ⚠️ Read-only database role for backups** (changes production *roles*, not data). Neon console →
  **SQL Editor** → branch `main`, database `neondb` (or yours) → run, with your own long random password:
  ```sql
  CREATE ROLE zunoot_backup WITH LOGIN PASSWORD '<long random password>';
  GRANT CONNECT ON DATABASE neondb TO zunoot_backup;
  GRANT USAGE ON SCHEMA public TO zunoot_backup;
  GRANT SELECT ON ALL TABLES IN SCHEMA public TO zunoot_backup;
  GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO zunoot_backup;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO zunoot_backup;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO zunoot_backup;
  ```
  Build its connection string from the **direct** (non-pooled) one in **Connect**: replace user and
  password with `zunoot_backup` and yours. The host must **not** contain `-pooler`.
  *Why a separate role: if GitHub's secret ever leaked, it could read the data but not change or delete it.*
- [ ] **5.6 Dead man's switch.** https://healthchecks.io → sign up → **Add Check** → name `zunoot-backup`,
  **Period** 1 day, **Grace** 2 hours → save → copy its ping URL (`https://hc-ping.com/<uuid>`). Its default
  integration emails you when a ping is late or reports failure.
- [ ] **5.7 GitHub secrets and variables.** Settings → **Environments** → `backups`:
  - **Environment secrets**: `BACKUP_DATABASE_URL` (5.5), `BACKUP_S3_ACCESS_KEY_ID` and
    `BACKUP_S3_SECRET_ACCESS_KEY` (5.4 writer), `HEALTHCHECKS_BACKUP_URL` (5.6)
  - **Environment variables**: `BACKUP_S3_BUCKET` = `zunoot-backups`, `BACKUP_S3_ENDPOINT_URL` = endpoint
    from 5.1, `BACKUP_S3_REGION` = `auto`, `BACKUP_AGE_RECIPIENT` = the `age1…` public key
- [ ] **5.8 First backup.** **Actions** → **Nightly backup** → **Run workflow** (`main`). Check: the run's
  summary shows row counts matching what you expect (≈18 students, 1,500+ flashcards); R2 shows
  `daily/…/zunoot-….dump.age` and `latest.manifest.json`; healthchecks.io shows the check as **up**.
- [ ] **5.9 Restore drill.** Follow `docs/RESTORE_DRILL.md` and record the time. That's your CV number.

## 6. Uptime monitoring

- [ ] **6.1 UptimeRobot** (https://uptimerobot.com, free) → **New monitor**:
  - Type **HTTP(s)**, name `zunoot livez`, URL `https://zunoot.onrender.com/livez`, interval **5 minutes**,
    alert contact: your email → Create
  - Second monitor: `zunoot healthz`, URL `https://zunoot.onrender.com/healthz`, interval **60 minutes**
  *Why not `/healthz` every 5 minutes: it queries the database, which would stop Neon's free compute
  from ever scaling to zero and use up the monthly compute allowance (`docs/SLO.md` → cost constraints).*
- [ ] **6.2 Optional public status page:** **Status pages** → **Create** → add both monitors → a URL you can
  put on your CV next to the uptime figure.
- [ ] **6.3 Note the start date.** Uptime % needs a full calendar month to quote (see `docs/CV_METRICS.md`).

## 7. ⚠️ Repair data damaged by BUG-3 (production data)

- [ ] Take an on-demand backup (§5.8 steps), then follow `db/repairs/001_guild_member_counts.sql`. Run it once
  as-is (it ends in `ROLLBACK`), check the preview, then change `ROLLBACK` to `COMMIT` and run it again.

## 8. Load test and the bottleneck

- [ ] Follow `loadtest/README.md` against **staging** (resume it first, suspend it afterwards).
- [ ] Record the baseline in `docs/PERFORMANCE.md`, then send me the numbers and the dashboard's Database
  row. Next step: deploy the candidate fix (branch `perf/db-connection-pool`) to staging and re-run the same
  test.

## 9. Housekeeping

- [ ] Calendar reminders: restore drill every quarter; rotate `METRICS_TOKEN` and the Grafana token yearly.
- [ ] GitHub disables scheduled workflows in a repo with **no activity for 60 days**. healthchecks.io (5.6)
  will email you if that happens. Re-enable it under **Actions** → **Nightly backup**.
