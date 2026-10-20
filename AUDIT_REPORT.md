# Privacy and Security Hardening Audit Report

## 1. Executive Summary
This audit report documents privacy hardening measures implemented across AutoQA to ensure customer site data, testing patterns, and user identities never leak into logs, URLs, alerts, or third-party surfaces.

## 2. Hardening Measures Implemented

### A. Logging & Alerts
- **Logs:** Replaced all customer domains and raw URLs in application logs (`sites.py`, `jobs.py`, `public_checks.py`, `main.py`) with `site_id` references or generic error types.
- **Admin Bypasses:** Replaced `domain=` in `ADMIN_BYPASS` events with `site_id=`. User emails are masked.
- **Alerts:** Removed browser engine name and raw domains from Slack alerts (`alerts.py`).
- **Access Logs:**
  - Added `--no-access-log` to uvicorn in `Dockerfile.web` to avoid logging HTTP request lines containing query parameters or paths.
  - Configured Caddy access logs in `Caddyfile` with structured JSON, exclusion of static files, and no-referrer policies.
- **Per-Domain Quota Error Message:** Replaced specific error message naming the domain with generic message: `"Quick checks for this site are limited right now. Try again later or verify the site."`

### B. URL Privacy & Wizard Refactoring (Decision A)
- **Zero URL in Query Params:** Removed `url=` query parameter across all routes and redirects.
- **Authenticated Users:** The wizard uses `?site=<id>` only. Ownership is verified server-side (`404` returned if site does not belong to the user).
- **Unauthenticated Visitors:** The landing hero form stores the URL in a short-lived (15 min), signed, HttpOnly, SameSite=Lax cookie (`autoqa_pending_url`).
- **Account Claim:** Upon registration or login, the cookie is read, converted into a site record under the user's account, and deleted immediately.

### C. Artifact Privacy & Anonymization
- **UUID4 Names:** All screenshots and trace artifacts use `uuid.uuid4().hex` filenames in per-run folders (`artifacts/<run_id>/<uuid>.png`, `artifacts/<run_id>/<uuid>.zip`).
- **Path Traversal & Ownership:** Artifact retrieval (`/artifacts/{path}`) verifies ownership of the associated `run_id` before serving.
- **Retention & Account Deletion:** `delete_user_account` in `app/auth.py` completely purges all run directories and any referenced screenshot/trace files from disk.

### D. Security Headers & Crawling Controls
- **Headers:** All HTTP responses include:
  - `Referrer-Policy: no-referrer`
  - `X-Robots-Tag: noindex, nofollow`
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self';`
- **Robots.txt:** `/robots.txt` disallows all user agents (`User-agent: *\nDisallow: /\n`).
- **Privacy Policy:** `/privacy` provides an honest, clear disclosure of data storage and retention.

### E. Backups (Decision B)
- `scripts/backup_db.sh` supports public-key encryption using `age -r "${AGE_RECIPIENT}"`.
- The private key is never stored on the server.
- Backup files have `0600` permissions and 14-day automated rotation.
- Documented recovery procedure using `age -d -i <key>`.

### F. Accepted Decision (Decision C: Database Encryption)
- **Decision:** Skip application-level column/database encryption for customer domains and URLs.
- **Rationale:** Customer site data is strictly scoped by `user_id` with foreign key cascades and server-side authorization checks on all query paths. Account deletion completely purges all related database rows and files. Full-disk encryption (LUKS / encrypted volumes) protects data at rest without introducing query indexing bottlenecks.

## 3. Allowed Sources for Content-Security-Policy
| Directive | Allowed Source | Rationale |
|---|---|---|
| `default-src` | `'self'` | Deny external origins by default |
| `script-src` | `'self'` | Only serve internal application scripts (`/static/app.js`) |
| `style-src` | `'self' 'unsafe-inline'` | Internal stylesheet (`/static/style.css`) and inline styles in templates |
| `img-src` | `'self' data:` | Local screenshots (`/artifacts/*`) and data URI images/icons |
| `connect-src` | `'self'` | XHR/fetch calls to local endpoints (e.g. `/runs/{id}/status`) |
| `frame-ancestors` | `'none'` | Prevent clickjacking across all pages |
| `base-uri` | `'self'` | Prevent base tag injection |
| `form-action` | `'self'` | Ensure forms only submit to the AutoQA origin |
