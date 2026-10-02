# AutoQA v2: Public Multi-User Platform (Project Context)

Put this file in the project root next to PLAN.md. The agent must read it before any change.

## Goal
Anyone can sign up, add a website they own, verify ownership, and run automated checks. They get a report with evidence. The v1 local tool keeps working for your own company; v2 is a separate mode for public users.

## Hard rules
- Do not break v1 (`python -m app.runner suite ...` for the company site must still work).
- Users may only test sites they have **verified they own**.
- The server must never be usable to reach internal networks (SSRF protection is mandatory).
- User site credentials are encrypted at rest, deleted after the run, and never logged.
- The web app only creates jobs. A separate **worker** process runs Playwright.
- Do NOT add features not listed here. Ask first.
- Only change the files named in each instruction.

## Login reality (important)
When a user logs into their own site, the session lives on THEIR domain. Our site cannot read it. So v2 supports:
- **Mode B, public pages:** no login. Default.
- **Mode A, test credentials:** user gives a test account; Playwright logs in. Fails on MFA/SSO/CAPTCHA. Detect these and report "login not automatable" instead of a test failure.
- **Mode C, remote browser login:** NOT in v2 (future).

## Fixed checks (no custom scripts for public users)
1. Page loads (HTTP < 400) for each crawled page
2. Console errors and uncaught JS errors
3. Failed network requests (4xx/5xx/failed)
4. Broken internal links (HTTP status)
5. Page load time per page
6. Screenshot per page (failed pages always)
7. Login success check (Mode A only)

Crawl limits: same domain only, max 25 pages, depth 2, 5 minutes per run, 1 browser engine (chromium) in v2.

## Stack
- Python, FastAPI, Jinja2 (server-rendered UI; keep the existing templates style)
- PostgreSQL (SQLModel/SQLAlchemy), Alembic migrations
- Redis + RQ (queue) with a separate worker process
- Playwright (official Playwright Python Docker image for worker)
- Passwords: argon2. Sessions: signed HTTP-only cookies. CSRF tokens on all forms.
- Credential encryption: Fernet (key from environment variable)
- Storage: local disk volume with 30-day cleanup (S3-compatible optional later)
- Deployment: one VPS (4 GB RAM+), Docker Compose, Caddy for HTTPS

## Data model (new/changed)
- users(id, email unique, password_hash, email_verified, created_at)
- sites(id, user_id, url, domain, verify_token, verified_at, created_at)
- runs: add user_id, site_id, mode (public|credentials), status (queued|running|completed|failed|blocked|expired), queued_at
- site_credentials(id, site_id, login_url, username_enc, password_enc, created_at, expires_at)  (deleted after run)
- pages(id, run_id, url, status_code, load_ms, screenshot_path, error)
- Existing tables (flow_results, step_results, console_logs, network_failures, link_checks) stay; public runs link results to `pages`/`runs`.
- usage(id, user_id, date, runs_count)

## Security requirements
1. **Ownership verification** before any run: DNS TXT `_autoqa.<domain>` = `autoqa-verify=<token>` OR file at `/.well-known/autoqa-<token>.txt` containing the token.
2. **SSRF protection:** only http/https; resolve the hostname; reject loopback, private, link-local, multicast, reserved, and cloud metadata IPs (127.0.0.0/8, 10/8, 172.16/12, 192.168/16, 169.254/16, ::1, fc00::/7, fe80::/10). Re-check at run time and for EVERY request/redirect inside Playwright (route handler). Worker container also blocks private ranges at network level.
3. **Limits:** 5 runs/day/user, 1 concurrent run per user, 3 concurrent globally, 5 min max per run, 25 pages max, max 2 sites per user (configurable).
4. **Isolation:** fresh browser context per run; worker runs as non-root in a container.
5. **Credentials:** encrypted, deleted after run completes or after 1 hour, never in logs, reports or screenshots (mask password fields; do not screenshot the login form after typing).
6. **Auth hygiene:** rate-limit login/register, generic error messages, email verification, account + data deletion.
7. **Legal:** terms page + checkbox "I am authorized to test this site".

## Statuses
Run: queued / running / completed / failed / blocked (SSRF or verification) / expired (credentials login impossible).
Page: ok / error.

## Folder additions
```
app/
  auth.py          # register, login, sessions, CSRF
  sites.py         # add site, verification
  safety.py        # URL validation, SSRF checks, Playwright request guard
  jobs.py          # RQ enqueue + limits
  worker.py        # RQ worker entry: runs public checks
  public_checks.py # crawler + fixed checks
  creds.py         # Fernet encrypt/decrypt, auto-delete
  templates/       # landing, auth, sites, wizard, progress, report
alembic/
docker/
  Dockerfile.web
  Dockerfile.worker
docker-compose.yml
Caddyfile
.env.example
```

## Not in v2
Remote browser login (Mode C), custom scripts for public users, video, accessibility, mobile devices, CI/CD hooks, payments, teams/organizations, Lighthouse.

## UI requirements
Landing page (URL box + what we test), register/login, My sites (verification status), wizard (URL -> verify -> optional test login -> run), live progress (polling every 3 s), report (score, failures first, screenshots), run history, clear empty/error states, mobile friendly.
