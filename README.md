# CMSPlus

A platform for monitoring and testing any website/project (Drupal, WordPress, custom builds — it doesn't
matter) from one place: project and environment (Production/Staging/...) management, automated health/SSL/SEO/
Lighthouse checks, cache warming, UPC-based price auditing against an uploaded spreadsheet, cross-environment
visual comparison, rule-based Playwright scenarios, and scheduled cron jobs with email alerts. Every check works
purely over URLs; there's no dependency on a specific CMS or technology.

## Features

- **Login and authorization** — Session-based email/password login (see
  [Users and authorization](#users-and-authorization)). The Admin role sees and manages every project; the
  User role only sees the projects assigned to them.
- **Project & environment management** — Each project can have multiple environments (Production, Staging,
  Development...). One environment is flagged "primary" and summarized on the project cards.
- **Health check** — Sends an HTTP request and records the status code, response time, and response
  headers/body (`httpx`).
- **SSL check** — Reads the certificate's validity window, days remaining, and issuer/subject (`cryptography`).
- **SEO check** — Opens the page with Playwright and extracts signals such as title/meta description/canonical/
  h1/OG tags/structured data/image alt text, then computes a 0-100 score based on what's missing.
- **Lighthouse audit** — Runs the Node.js-based Lighthouse tool as a subprocess and records performance/
  accessibility/best-practices/SEO scores plus the worst-offending audits.
- **Cache warming** — Runs [gowarm](https://github.com/tarikflz/gowarm) (Go) as a subprocess: walks every URL in
  the environment's sitemap across the configured cookie/header combinations ("axes" — e.g. region×language) to
  warm the origin/CDN cache, then summarizes cache hit/miss state from the response headers (`CF-Cache-Status`,
  `X-Drupal-Cache`, etc.).
- **Price audit** — Upload a spreadsheet (UPC code, cash price, installment price) and the app crawls a
  product-listing page (including infinite-scroll pagination), visits every product's detail page, reads the UPC
  from the URL and the displayed cash/installment price, and compares them against the spreadsheet. Optionally
  iterates every color × capacity variant too, since each combination can carry its own UPC/price on some sites.
  Runs in a background thread with a live progress page (see
  [Price audit](#price-audit)) rather than blocking the request.
- **Cross-environment visual comparison** — Screenshots the same path on two environments (e.g. Staging vs.
  Production), diffs them pixel-by-pixel, boxes the differing regions in red, and reports a difference
  percentage (`Pillow` + `numpy`).
- **Scenarios** — Rule-based Playwright flows defined step by step per environment (see the table below).
  Fully deterministic, no AI involved — every step maps directly to a Playwright command. Stops at the first
  failing step, recording the error and a screenshot in the run history. Run history is paginated server-side
  (10 per page).
- **Cron jobs** — Any of health/ssl/seo/lighthouse/cache-warm/scenario checks can be scheduled per environment
  at a fixed interval (15m / 1h / 6h / daily / weekly) via `APScheduler`, which runs as long as the app process
  is alive — no separate worker needed. An optional email alert fires when a job's status flips (success →
  failure or back).

## Stack

- FastAPI + Jinja2 (server-rendered, Tailwind CDN)
- Starlette `SessionMiddleware` (signed cookie) + stdlib `hashlib.pbkdf2_hmac` for session/password handling
  (`itsdangerous`; no extra auth library)
- PostgreSQL + SQLAlchemy 2.0 (via Docker Compose; no Alembic — schema changes need a manual `ALTER TABLE`, see
  [Development notes](#development-notes))
- httpx (health check), cryptography (SSL check), Playwright (SEO scan + scenarios + price audit crawling +
  screenshots for visual comparison), pandas + openpyxl (SEO/Lighthouse reporting, price audit spreadsheet
  parsing)
- Node.js + Lighthouse (performance/accessibility/best-practices/SEO audit)
- Go + gowarm (sitemap-driven cache warming; config is generated with PyYAML)
- APScheduler (per-environment scheduled cron jobs)
- smtplib (stdlib) for cron job notification emails
- Pillow + numpy for cross-environment visual comparison (diff detection and highlighting)

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium   # needed for SEO scans + scenarios + price audit + visual comparison
cp .env.example .env

cd lighthouse && npm install && cd ..     # needed for Lighthouse reports (Node.js >= 18.16)

# needed for cache warming (Go >= 1.24) — builds the binary into cache_warmer/bin/gowarm
GOBIN="$(pwd)/cache_warmer/bin" go install github.com/tarikflz/gowarm/cmd@latest
mv cache_warmer/bin/cmd cache_warmer/bin/gowarm

docker compose up -d db

.venv/bin/uvicorn app.main:app --reload
```

The app runs at http://127.0.0.1:8000.

### Environment variables (`.env`)

| Variable | Description |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy connection string (`postgresql+psycopg2://...`). The default matches the `db` service in `docker-compose.yml`. |
| `SECRET_KEY` | Used to sign the session cookie; should be a long, random value (e.g. `python3 -c "import secrets; print(secrets.token_hex(32))"`). Falls back to an insecure default if left empty — always set this in production. |
| `SMTP_HOST` | SMTP server for cron job notification emails. If left empty, no email is sent — it's just logged, so nothing breaks during development. |
| `SMTP_PORT` | Defaults to `587`. |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | SMTP credentials (e.g. for Gmail, use an [app password](https://myaccount.google.com/apppasswords) instead of your normal password). |
| `SMTP_FROM_EMAIL` | Sender address; falls back to `SMTP_USERNAME`, then to `cmsplus@localhost`. |
| `SMTP_USE_TLS` | `true`/`false`. Defaults to `true`. |
| `BASE_URL` | The address notification email links should point to (e.g. `http://localhost:8000`). |

### Troubleshooting

- **"node bulunamadı (Node.js must be installed for Lighthouse)"** — Even if Node.js is installed, this error
  shows up if the process running the app doesn't have Node's directory (`/opt/homebrew/bin` on Homebrew) on its
  `PATH`. Starting the app from a normal terminal (with `~/.zprofile`/`~/.zshrc` set up correctly) is usually
  enough; if it's launched from an IDE/background job that doesn't inherit your shell's `PATH`, make sure that
  `PATH` includes Node's `bin` directory.
- **Playwright-related errors (scenarios/SEO/price audit/visual comparison not working)** — Make sure
  `playwright install chromium` has been run.
- **"gowarm binary bulunamadı" (gowarm binary not found)** — `cache_warmer/bin/gowarm` hasn't been built yet; run
  the `go install` step from Setup (the equivalent of the Node `PATH` issue above, except the binary is looked
  up at a fixed, repo-relative path, so `PATH` isn't a factor — it just needs to exist).

## Structure

```
app/
  main.py                FastAPI app and all routes (project/environment CRUD, checks, scenarios, cron jobs, comparisons)
  database.py             SQLAlchemy engine/session (DATABASE_URL, Base.metadata.create_all)
  auth.py                 Password hash/verify, session helpers (get_allowed_project_ids, require_admin), default-user seed
  models.py                User, Project, Environment, HealthCheck, SeoCheck, LighthouseCheck, CacheWarmCheck,
                            PriceAudit, CronJob, EnvironmentComparison/ComparisonPage, Scenario/ScenarioStep/
                            ScenarioRun/ScenarioStepResult
  health_check.py          Health check via httpx
  ssl_check.py              SSL certificate check
  seo_check.py             SEO extraction + score calculation via Playwright
  lighthouse_check.py      Node/Lighthouse subprocess wrapper
  cache_warm_check.py      Go/gowarm subprocess wrapper (config.yaml generation + summary JSON parsing)
  price_audit.py           Spreadsheet parsing + listing-page crawl/variant-iteration + comparison; runs in a
                            background thread (see Price audit)
  visual_compare.py        Screenshot via Playwright + diff detection via Pillow/numpy
  scenario_runner.py       Rule-based scenario/step execution engine via Playwright
  scheduler.py             APScheduler setup + cron job execution + email notification on status change
  email_notify.py          Sends notification emails via SMTP
  templates/               Jinja2 templates
  static/                  CSS/JS, uploaded screenshots (app/static/uploads/, not in git), samples/ (sample
                            spreadsheet for price audits, tracked in git)
lighthouse/
  run.mjs          Node script that runs Lighthouse and writes the JSON report to stdout
  package.json     lighthouse + chrome-launcher dependencies
cache_warmer/
  bin/gowarm       Binary built via `go install` (not in git, see Setup)
```

## Users and authorization

The entire app (aside from static files) requires login; unauthenticated requests are redirected to `/login`.
There are two roles:

- **Admin** — sees every project, creates/edits/deletes projects and environments, and adds/edits/deletes users
  from `/users`.
- **User** — only sees the projects assigned to them (this is filtered everywhere: the project list,
  health/SEO/Lighthouse/cache-warm/price-audit history, scenarios; a direct URL to an unassigned project 404s).
  Within their assigned projects they can use existing features (running checks/scenarios, cron jobs), but
  creating/editing/deleting projects or environments and managing users is Admin-only.

A default admin user is created automatically on first boot (see `app/auth.py` — `DEFAULT_USER_EMAIL`/
`DEFAULT_USER_PASSWORD`); it's not recreated if a user already exists. Passwords are salted and hashed with the
stdlib `hashlib.pbkdf2_hmac`. Project visibility is enforced at a single choke point — the helper functions in
`app/main.py` such as `_get_project_or_404`/`_get_environment_or_404` (backed by
`app.auth.get_allowed_project_ids`) — so when adding a new project-scoped route, make sure it goes through one of
these, or access control will silently be skipped.

## Data model

Each project (`Project`) has one or more environments (`Environment`). The URL and an optional CMS/version note
(`drupal_version` — aimed at Drupal projects but can be left blank; not required for any other kind of site) are
stored at the environment level; each environment's latest health/SSL/SEO/Lighthouse/cache-warm/price-audit
result is also cached directly on the `Environment` row for quick access (`last_check_ok`, `ssl_days_remaining`,
`last_seo_score`, `last_cache_warm_ok`, `last_price_audit_ok`, etc.), with the full history kept in separate
tables (`HealthCheck`, `SeoCheck`, `LighthouseCheck`, `CacheWarmCheck`, `PriceAudit`).

**Cache warming** is opt-in: "Cache Isıt" can't run until an environment's `cache_warm_sitemap_url` and
`cache_warm_axes_yaml` (gowarm's `axes:` YAML list — defines which cookie/header combinations to warm with) are
filled in via the environment edit form. The result (`CacheWarmCheck`) includes total/successful/failed request
counts, cache hit/miss/bypass/unknown counters, the hit ratio, and a list of failed requests.

**Price audit** is also opt-in and needs five fields on the environment (listing page path, a regex that picks
product links out of every `<a href>` on the listing page, click selectors for the cash/installment payment
toggle, and the selector to read the resulting price from) before a spreadsheet can be uploaded and audited; two
more (color/capacity variant-option selectors) are optional and only needed if a product's UPC/price changes per
color or storage-capacity selection. See [Price audit](#price-audit) for the full flow.

If a project has 2+ environments, "Compare Environments" on the project page creates an `EnvironmentComparison`:
the selected paths (`ComparisonPage`) are appended to both environments' URLs, screenshotted, diffed
pixel-by-pixel, and rendered as a difference percentage plus a marked-up diff image.

Each environment can also define rule-based **scenarios** (`Scenario`): an ordered sequence of steps
(`ScenarioStep`) executed in order via Playwright when you hit "Run"; each run (`ScenarioRun`) and every step's
result (`ScenarioStepResult`, with description/status/error/screenshot/duration) is recorded individually.

`CronJob` runs one of health/ssl/seo/lighthouse/cache-warm checks, or a specific `Scenario`, on a fixed schedule
for an environment; `notify_enabled` + `notify_emails` trigger an email on status change. Price audits are not
part of the cron system — see below.

### Scenario step types

| Step type | What it does | Fields used |
| --- | --- | --- |
| `navigate` | Appends `path` to the environment's URL and goes there | `path` |
| `click` | Clicks the selector | `selector` |
| `fill` | Types text into a field | `selector`, `value` |
| `select_option` | Selects an option in a `<select>` | `selector`, `value` |
| `wait` | Waits for the given duration | `wait_ms` |
| `assert_text` | Asserts the page contains the text | `value` |
| `assert_no_text` | Asserts the page does not contain the text | `value` |
| `assert_element` | Asserts an element matching the selector exists | `selector` |
| `assert_count` | Compares the element count with an operator (`>=`, `<=`, `==`, `!=`, `>`, `<`) | `selector`, `operator`, `count` |
| `screenshot` | Takes a screenshot | — |
| `save_value` | Saves the element's value (`.value` for input/textarea/select, text otherwise) into a variable | `selector`, `value` (variable name) |
| `compare_values` | Compares two saved variables with `==`/`!=`; uses a locale-independent numeric comparison that's tolerant of currency symbols/thousands separators/decimal formatting (`$1,499` and `1499.00` are considered equal) | `value`, `value2` (two variable names), `operator` |

Variables saved via `save_value`/`compare_values` only live in memory for the duration of a single run (one
`run_scenario` call) — they're not persisted. Typically used to save a price on one page and compare it against
a price captured on another.

## Price audit

Upload a spreadsheet with three columns — `UPC Code` (or `UPC`), `Peşin Fiyat` (cash price), and `Taksitli Fiyat`
(installment price), case-insensitively matched — and the app compares it against what's actually shown on the
site, matched by UPC. A sample file is available for download from the environment edit form and next to the
upload button on the environment page (`app/static/samples/price_audit_example.xlsx`).

The crawl:
1. Opens the configured listing page and scrolls it (handling infinite-scroll pagination) until no new product
   links appear for a few rounds in a row.
2. Filters every `<a href>` on the page through the configured regex to get the set of product detail URLs.
3. Visits each product page, reads the `upc=` query parameter the site appends to the URL client-side, clicks
   the cash/installment payment toggles in turn, and reads the resulting price from the same selector (the site
   this was built against shows different values in the same DOM element depending on which payment mode is
   selected).
4. If color/capacity variant selectors are configured, iterates every combination of those (each one can carry
   its own UPC and price) instead of just reading the page's default variant.
5. Matches everything by UPC against the spreadsheet: matched rows show both prices with a highlighted mismatch
   if either doesn't agree (compared with the same locale-independent logic as `compare_values`), plus separate
   "only on the site" / "only in the spreadsheet" lists, and a list of per-product/variant errors that didn't
   block the rest of the run.

This is a manual, one-off tool (not part of the cron scheduler) since the spreadsheet changes on every run.
Because crawling dozens of products — each with possibly several variants — is slow, it runs in a background
thread (`app/price_audit.py`: `start_price_audit` does fast up-front validation synchronously, then
`run_price_audit_background` does the crawl with its own DB session) instead of blocking the upload request; the
result page shows a live progress bar (`X / Y products`, current product, auto-refreshing) while `status ==
"running"`, then renders the full report once it flips to `"completed"`/`"failed"`. This is the one part of the
app that isn't fully synchronous — see [Development notes](#development-notes).

## Scheduled tasks (cron jobs)

From an environment's detail page, one of the health/ssl/seo/lighthouse/cache-warm checks — or a scenario
belonging to that environment — can be scheduled at an interval (15 minutes / 1 hour / 6 hours / daily /
weekly). `APScheduler` runs these jobs in the background as long as the app process is alive — no separate
worker/cron daemon is needed, but it also means the scheduler is rebuilt from scratch on every app restart (missed
runs aren't backfilled). If a job's latest status differs from its previous one (`ok` → failure or back) and
notifications are enabled, the configured email addresses get a status update.

## Development notes

- There's no Alembic (migration tool) in this project. `Base.metadata.create_all()` (`app/main.py`) only creates
  missing tables — it doesn't add columns to an existing one, so a new column on a model needs a manual
  `ALTER TABLE ... ADD COLUMN ...` against the database.
- There's no automated test suite; changes should be verified by running the app and exercising the relevant
  flow through the browser/`curl`.
- Price audits are the one background/threaded flow in an otherwise fully-synchronous app (every other check
  runs inline within its request). If you add another long-running feature, either follow the same
  thread-with-its-own-DB-session pattern or keep it synchronous like the rest — don't share a SQLAlchemy session
  across threads.
- `app/static/uploads/` (screenshots) and `backups/` (database backups) are excluded via `.gitignore`.
