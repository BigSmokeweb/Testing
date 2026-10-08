# AUDIT_REPORT.md

**Generated:** 2026-10-09  
**Auditor:** Antigravity AI  
**Repo:** `e:\web` — AutoQA (automated web quality testing SaaS)  
**Git branch:** `main`

---

## 1. Summary

| Severity | Found | Fixed | Open / Accepted |
|----------|-------|-------|-----------------|
| Critical | 4     | 4     | 0               |
| High     | 9     | 9     | 0               |
| Medium   | 6     | 6     | 0               |
| Low      | 9     | 7     | 2 (Accepted)    |
| **Total**| **28**|**26** | **2**           |

**Phases executed:**
- **Phase A**: Full repo discovery and architecture map.
- **Phase B**: Manual security exploration and gap closure (SSRF, CSRF, IDOR, path traversal, escaping).
- **Phase C**: Comprehensive code checklist audit (C1 to C6).
- **Phase D**: Proof-of-concept test reproduction for all findings.
- **Phase E**: Target fixes, schema migrations, and hardening.
- **Phase E follow-up & finalization**: Unit test suite expansion, Docker stack live validation, session versioning, and cleanup daemon validation.

---

## 2. Findings Matrix

| ID | Severity | File / Component | Description | Status |
|---|---|---|---|---|
| F1 | Medium | `app/main.py` | `/docs`, `/redoc`, `/openapi.json` exposed publicly without auth | **Fixed** (gated by `LOCAL_MODE=1`) |
| F2 | Low | `app/public_checks.py` | Swallowed exceptions in link checks and crawlers | **Fixed** (explicit error logging with stack trace) |
| F3 | Low | `app/worker.py` | Worker error message captured but discarded | **Fixed** (persisted to `run.note`, logged) |
| F4 | Critical | `app/main.py` | IDOR on `GET /report/{id}` | **Fixed** (`verify_run_ownership()` helper) |
| F5 | Critical | `app/main.py` | IDOR on `GET /runs/{id}/status` | **Fixed** (strictly scoped to owner or rejected) |
| F6 | Medium | `app/main.py` | Missing CSRF validation on `POST /wizard/start` | **Fixed** (CSRF verified) |
| F7 | High | `app/main.py` | Public `/artifacts` mount & traversal vulnerability | **Fixed** (authenticated route + path normalization check) |
| F8 | High | `app/main.py` | `/history` leaked runs across all tenants | **Fixed** (filtered by `user_id == current_user.id`) |
| F9 | High | `app/main.py` | `/runs/{id}/progress` unauthenticated when `run.user_id` NULL | **Fixed** (ownership helper enforced) |
| F10 | High | `app/linkcheck.py` | Link checker followed redirects without destination IP verification | **Fixed** (`safe_http_fetch()` per-hop validation) |
| F11 | High | `app/public_checks.py` | Crawlers and verifiers lacked strict IP filter on redirect | **Fixed** (`safe_http_fetch()` per-hop validation) |
| F12 | Critical | `app/creds.py` | Hardcoded default Fernet key fallback in production | **Fixed** (startup crashes with `RuntimeError` if missing) |
| F13 | High | `app/worker.py` | Worker crash leaves runs stuck in `running` status | **Fixed** (10-minute auto-reaper marks `failed`) |
| F14 | High | `app/main.py` | `POST /run` (v1 engine) callable by regular tenants | **Fixed** (404 unless `LOCAL_MODE=1`) |
| F15 | Low | `app/alerts.py` | Slack webhook URL could point to internal endpoints | **Accepted Risk** (config is read-only file mounted) |
| F16 | Low | `app/sites.py` | Well-known file fetch lacked streaming/IP constraints | **Fixed** (`safe_http_fetch()` with size limits) |
| F17 | Low | `app/worker.py` | Worker error reason lost or routed into dummy models | **Fixed** (`Run.note` column added via Alembic) |
| F18 | Medium | `docker-compose.yml` | Port `8000:8000` bound to `0.0.0.0` bypassing reverse proxy | **Fixed** (internal network only; reverse-proxied via Caddy) |
| F19 | High | `app/main.py` | v1 runner created runs with `user_id = NULL` | **Fixed** (disabled in prod; ownership helper blocks NULL in prod) |
| F20 | Medium | `docker-compose.yml` | Expired credentials and old artifacts accumulated indefinitely | **Fixed** (dedicated hourly `cleanup` service container) |
| F21 | Low | `README.md` | DNS rebinding protection limitation | **Accepted Risk** (documented; isolated via host iptables) |
| F22 | Low | `app/templates/base.html` | `/terms` and `/privacy` lacked content | **Fixed** (real policy and terms text added) |
| F23 | Medium | `app/main.py` | Run comparison compared against runs from other tenants | **Fixed** (scoped to same `user_id`, `site_id`, `engine`) |
| F24 | Low | `app/templates/progress.html` | Progress UI hung on disconnected stream | **Fixed** (retry status banner and connection loss handling) |
| F25 | Medium | `app/main.py` | `secure=False` hardcoded on session cookie | **Fixed** (`secure=True` when not in local mode) |
| F26 | Medium | `app/main.py` | Landing page queried unisolated `latest_run` | **Fixed** (scoped behind local mode check) |
| S1 | High | `app/auth.py`, `app/main.py` | Logout did not invalidate tokens server-side | **Fixed** (added `session_version` column + token check) |
| F27 | Low | `app/main.py` | `GET /logout` allowed CSRF logout | **Fixed** (POST-only logout with CSRF; GET shows confirm page) |
| F28 | Low | `.gitignore` | Local DB backup and sqlite files could be accidentally tracked | **Fixed** (updated `.gitignore` for `*.bak`, `*.db.*`, `*.sqlite*`, `*.log`) |

---

## 3. Database Migration

- **Migration File**: `alembic/versions/a1b2c3d4e5f6_add_session_version_and_run_note.py`
- **Down Revisions**: `('d041bbaef980', 'f9024451f825')`
- **Changes**:
  - Added `session_version: int` (default 1, not null) to `users` table.
  - Added `note: Text` (nullable) to `runs` table.
- **Tested**: Verified on SQLite (upgrade + downgrade) and applied to production PostgreSQL in Docker stack (`alembic upgrade head`).

---

## 4. Accepted Risks

1. **F21 — DNS Rebinding**:
   - `safe_http_fetch()` resolves hostname once and verifies that IP is public. A malicious DNS server returning a short TTL and swapping to private IP (127.0.0.1 or 169.254.169.254) between resolve and connect is mitigated at the network layer on Linux hosts via `scripts/block_worker_internal.sh` (`iptables -I DOCKER-USER`).
2. **F15 — Slack Webhook SSRF**:
   - Slack webhook is read from static `config.yaml` or environment. Tenants cannot edit `config.yaml` at runtime.

---

## 5. Live Docker Stack Verification

- **User Registration & Run**: Registered `dockertest2@example.com`, authenticated, added site `https://example.com`, verified site ownership, and enqueued run. Run ID `4` completed successfully by worker container.
- **Worker Egress Probes**:
  - `curl -m 5 http://127.0.0.1` -> Failed (`curl: (7) Failed to connect`)
  - `curl -m 5 http://169.254.169.254` -> Failed (`curl: (7) Failed to connect`)
  - `curl -m 5 http://192.168.1.1` -> Failed (`curl: (28) Connection timed out`)
- **Host Firewall Script (`scripts/block_worker_internal.sh`)**:
  - Target environment: Linux VPS host (`iptables` on `DOCKER-USER` chain). Not applicable on Windows dev host directly; confirmed script is syntactically sound and part of VPS deployment runbook.
- **Cleanup Service**:
  - Verified container `web-cleanup-1` runs hourly retention loop.
  - Log confirmed: `Starting retention cleanup... Retention cleanup completed. Purged 0 old runs.`

---

## 6. Manual To-Dos for Project Owner

1. **Review Legal Text**:
   - Check `/terms` and `/privacy` copy in `base.html` or replace with your legal counsel's approved terms.
2. **Set Production Environment Secrets**:
   - Generate strong values for `.env`:
     - `SECRET_KEY`: `openssl rand -hex 32`
     - `FERNET_KEY`: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
     - `POSTGRES_PASSWORD`: Strong random secret
3. **Database Backups**:
   - Set up daily automated `pg_dump` backups for the `postgres_data` volume.
4. **Pre-Launch VPS Checklist**:
   - Execute `bash scripts/block_worker_internal.sh` on Linux VPS host to lock down worker egress to private LAN.
   - Verify DNS points `DOMAIN` to VPS IP and ports 80/443 are open in cloud security group.
   - Ensure `LOCAL_MODE=0` in `.env`.

## 7. Verification still required on the real Linux server

The following items cannot be fully verified on a Windows development host and must be validated upon deployment to the Linux VPS host:
1. **Host-level worker network isolation**:
   - Run `sudo bash scripts/block_worker_internal.sh`.
   - Verify active iptables filtering on the docker chain: `iptables -S DOCKER-USER`.
2. **Worker egress probing on VPS**:
   - From inside the worker container (`docker compose exec worker sh`), run:
     - `curl -m 5 http://<private-lan-ip>` (must be blocked / time out)
     - `curl -m 5 http://169.254.169.254` (must be blocked / time out)
     - `curl -m 5 http://<docker-gateway-ip>` (must be blocked / time out)
3. **Internal network connectivity**:
   - Confirm worker continues to successfully reach Redis (`redis:6379`), PostgreSQL (`postgres:5432`), and legitimate external target sites.
4. **Caddy reverse proxy and port isolation**:
   - Confirm Caddy serves automatic HTTPS on ports 80/443 with valid TLS certificates.
   - Confirm backend FastAPI port `8000` is completely inaccessible from outside the VPS.

---

## 8. Areas Not Reviewed

- `flows/` directory (v1 Playwright demo flows; out of scope for v2 SaaS).
- Full live crawl across authenticated targets with CAPTCHA/SSO (handled by fallback session expiration detection).

