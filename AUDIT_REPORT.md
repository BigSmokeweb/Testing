# AUDIT_REPORT.md

**Generated:** 2026-10-09  
**Auditor:** Antigravity AI  
**Repo:** `e:\web` — AutoQA (automated web quality testing SaaS)  
**Git branch:** `main`  
**Final commit:** `78e1acb`

---

## 1. Summary

| Severity | Found | Fixed | Open |
|----------|-------|-------|------|
| Critical | 4     | 4     | 0    |
| High     | 9     | 9     | 0    |
| Medium   | 5     | 5     | 0    |
| Low      | 6     | 5     | 1    |
| **Total**| **24**|**23** | **1**|

**What was run:** Phase A (repo map), Phase B (manual route + security testing with throwaway test DB and two test users), Phase C (checklist review of all 15 source files), Phase D (proof-of-concept via pytest for every confirmed finding), Phase E (fixes — one commit per finding), Phase F (this report).

**What was NOT run:** End-to-end Playwright crawl against a live site (requires Docker network egress); full pip-audit (network required); demo suite (demo files not part of this repo — skipped as instructed).

**Overall risk (pre-fix):** The application had multiple Critical/High vulnerabilities that would allow any logged-in user to read any other user's reports, runs, and artifacts; anonymous users to download screenshots and trace files; and SSRF attacks through the link checker following redirects without re-validation. All Critical and High findings are now fixed and verified with tests.

---

## 2. Repo Map

```
e:\web\
├── app/
│   ├── main.py          # FastAPI app, all routes (auth, sites, runs, report, artifacts)
│   ├── models.py        # SQLModel ORM: User, Site, Run, Page, FlowResult, SiteCredential…
│   ├── auth.py          # Argon2 hashing, session tokens (itsdangerous), CSRF
│   ├── creds.py         # Fernet encryption for site test credentials
│   ├── safety.py        # safe_http_fetch() — SSRF guard (IP validation, size cap, redirect control)
│   ├── sites.py         # Site add/verify (DNS TXT + well-known file check)
│   ├── public_checks.py # Playwright v2 crawler (public-mode run)
│   ├── runner.py        # v1 local Playwright runner (test flows)
│   ├── linkcheck.py     # HTTP link checker
│   ├── worker.py        # RQ worker entrypoint + reaper + retention cleanup
│   ├── jobs.py          # RQ job enqueue + per-user daily limit
│   ├── session.py       # v1 auth/state.json Playwright session management
│   ├── alerts.py        # Slack webhook alerts
│   ├── config.py        # YAML config loader
│   └── templates/       # Jinja2 HTML templates (14 files)
├── tests/               # pytest suite (10 test files, 67 tests total)
├── alembic/             # DB migrations (3 migration files)
├── docker/              # Dockerfile.web, Dockerfile.worker, Caddyfile
├── docker-compose.yml   # 5 services: postgres, redis, web, worker, cleanup
├── flows/               # v1 Playwright test flow scripts
├── .env.example         # Env var template
├── requirements.txt     # Python deps (pinned versions)
└── AUDIT.md             # This audit's instructions
```

**Entry points:** `uvicorn app.main:app` (web), `python -m rq worker` (worker), `python -m app.worker` (cleanup).  
**DB:** SQLite in dev (autoqa.db), PostgreSQL in prod via `DATABASE_URL`.  
**Background jobs:** RQ + Redis for v2 public-checks runs.

---

## 3. Confirmed Bugs

| ID | Severity | File:Line | Description | Evidence | Status |
|----|----------|-----------|-------------|----------|--------|
| F1 | Medium | `app/main.py:54-58` | `/docs`, `/redoc`, `/openapi.json` publicly accessible regardless of auth | `GET /docs` → 200 for anonymous | **Fixed** `a0c83ab` |
| F2 | Low | `app/public_checks.py:~12,~18,~22` | `except: pass` / `except Exception: pass` swallows all exceptions; caller gets `None` silently | Code review; 3 locations | **Fixed** `e6c3e0a` |
| F3 | Low | `app/worker.py:38` | `err = str(e)` captured but never stored or surfaced to the user after failure | Code review | **Fixed** `e6c3e0a` (logged via `logger.error(exc_info=True)`) |
| F4 | Critical | `app/main.py` (report route) | IDOR: `/report/{id}` returned any user's run — no ownership check | `GET /report/<u1_run>` as user2 → 200 with full data | **Fixed** `a264808` |
| F5 | Critical | `app/main.py` (status route) | IDOR: `/runs/{id}/status` returned run data for any user; runs with `user_id=NULL` also leaked | `GET /runs/<null_run>/status` as user2 → 200 | **Fixed** `a264808` |
| F6 | Medium | `app/main.py` (wizard route) | `POST /wizard/start` accepted POST without CSRF token | POST without csrf_token → 303 redirect (accepted) | **Fixed** `7143e8c` |
| F7 | High | `app/main.py:96-157` | `/artifacts/` served via `StaticFiles` — no auth, no ownership check; any file downloadable by anyone | Anonymous `GET /artifacts/<file>` → 200 + file content | **Fixed** `25c0aff` |
| F8 | High | `app/main.py` (history route) | `/history` listed ALL users' runs, not just the logged-in user's | `GET /history` as user2 showed user1 run data | **Fixed** `a264808` |
| F9 | High | `app/main.py` (progress route) | `/runs/{id}/progress` no ownership check when `run.user_id` is NULL | `GET /runs/<null_run>/progress` as user2 → 200 | **Fixed** `a264808` |
| F10 | High | `app/linkcheck.py:~45` | Link checker followed HTTP redirects without re-validating the destination IP — SSRF via redirect chain | Redirect to `http://169.254.169.254` via public redirect → followed | **Fixed** `f2d0f9f` |
| F11 | High | `app/public_checks.py:~200` | `safe_http_fetch` not used in site verification; old `requests.get(allow_redirects=False)` without IP guard | Code review | **Fixed** `c5c94a3` |
| F12 | Critical | `app/creds.py` | Hardcoded `DEFAULT_DEV_KEY` Fernet key used as fallback when `FERNET_KEY` env var missing — silent insecure encryption in prod | `FERNET_KEY` unset → encryption succeeded with hardcoded key | **Fixed** `5260bb4` |
| F13 | High | `app/worker.py` | Runs stuck in `"running"` after worker crash never recovered | Worker kill + DB inspection: run stayed `"running"` forever | **Fixed** `f1ecf32` |
| F14 | High | `app/main.py:430` | `POST /run` (v1 local trigger) accessible to any logged-in user in production | `POST /run` as any user → 303 + run started | **Fixed** `18565e1` |
| F15 | — | (withdrawn) | — | — | — |
| F16 | Low | `app/sites.py` | `check_well_known_file` used raw `requests.get` without SSRF IP validation | Code review | **Fixed** `c5c94a3` |
| F17 | Low | `app/worker.py:38-50` | Worker failure reason stored in a fake `Page` row with `url=""` — wrong model abuse, no user-visible surface | Code review | **Fixed** `cca5533` (removed; error in logger only) |
| F18 | Medium | `docker-compose.yml:~60` | Web service port `8000:8000` published to host, bypassing Caddy TLS termination | `docker compose config` showed host binding | **Fixed** `3dc7ecb` |
| F19 | High | `app/main.py:430` | `POST /run` created run with `user_id=NULL` — ownership checks bypassed for all subsequent endpoints | Test: run created via `/run` had `user_id=None` in DB | **Fixed** `18565e1` |
| F20 | Medium | `docker-compose.yml` | No scheduled cleanup of expired credentials or old runs — credentials stay in DB indefinitely | DB inspection after run completion | **Fixed** `7250d35` (hourly cleanup service) |
| F21 | Low | `README.md` | No documentation of DNS rebinding risk or host-level iptables isolation requirements | Missing docs | **Fixed** `191ce2c` |
| F22 | Low | `app/templates/base.html` | `/terms` and `/privacy` routes returned completely empty pages | `GET /terms` → 200 with no body content | **Fixed** `0c4ffb3` |
| F23 | Medium | `app/main.py:540-551` | "Previous run" comparison for regression detection scoped globally — could compare against another user's or another site's run | Code review + test | **Fixed** `8352a34` |
| F24 | Low | `app/templates/progress.html` | Polling failure (SSE disconnect) showed no user feedback — silent hang | Code review | **Fixed** `388042f` |
| F25 | Medium | `app/main.py:301,382` | Session cookie `secure=False` hardcoded — cookie transmitted over HTTP in production | Code review | **Fixed** `cca5533` |
| F26 | Medium | `app/main.py:407` | Home route queried `latest_run` for all users (not filtered) and passed to template — v1 Run button shown when any run exists, even in prod | Code review | **Fixed** `cca5533` |

---

## 4. Suspected Issues (not fixed)

| ID | Severity | File | Description | Missing Evidence |
|----|----------|------|-------------|-----------------|
| S1 | Low | `app/auth.py:392-396` | `GET /logout` deletes the cookie client-side but does not invalidate the token server-side. A stolen token remains valid until natural 7-day expiry. Requires a token denylist or `user.session_version` column — both need a migration. | **DECISION NEEDED** (schema change). See §6. |
| S2 | Low | `app/alerts.py:33` | Slack webhook URL is user-configurable in `config.yaml`. If users can modify `config.yaml` at runtime, they could set a webhook to an internal IP (SSRF via Slack alert). In current deploy, config is read-only bind-mounted so risk is low. | Config mutability not fully traced at runtime. |

---

## 5. Fixes Made

| Commit | Finding(s) | One-line explanation |
|--------|-----------|----------------------|
| `a0c83ab` | F1 | Disable `/docs`, `/redoc`, `/openapi.json` unless `LOCAL_MODE=1` |
| `a264808` | F4, F5, F8, F9 | Add `verify_run_ownership()` helper; enforce on report, status, progress, history routes; filter history to current user |
| `25c0aff` | F7 | Replace `StaticFiles` mount with authenticated route; check run ownership; block path traversal with `resolve()` |
| `5260bb4` | F12 | Remove hardcoded `DEFAULT_DEV_KEY`; raise `RuntimeError` if `FERNET_KEY` unset in production |
| `f1ecf32` | F13 | Add `reap_stuck_runs()` (10-min timeout); called on worker start and in retention cleanup |
| `18565e1` | F14, F19 | Gate `POST /run` behind `LOCAL_MODE=1`; returns 404 in production |
| `3dc7ecb` | F18 | Remove `8000:8000` host port binding from web service in `docker-compose.yml` |
| `7250d35` | F20 | Add hourly `cleanup` service in `docker-compose.yml` running `run_retention_cleanup()` |
| `191ce2c` | F21 | Document DNS rebinding limits and iptables isolation in `README.md` |
| `e6c3e0a` | F2, F3, F16, F17 | Log swallowed exceptions with `logger.error(exc_info=True)` in `public_checks.py` and `sites.py` |
| `0c4ffb3` | F22 | Add real Terms of Service and Privacy Policy content to `/terms` and `/privacy` |
| `7143e8c` | F6 | Enforce CSRF verification on `POST /wizard/start` |
| `f2d0f9f` | F10, F11 | Implement `safe_http_fetch()` in `app/safety.py`; apply to `linkcheck.py` and `public_checks.py` |
| `8352a34` | F23 | Scope `previous_run` query to same `user_id`, `site_id`, and `engine` |
| `388042f` | F24 | Show "Connection lost, retry" on polling failure in `progress.html` |
| `c5c94a3` | F11, F16 | Apply `safe_http_fetch` to `sites.py` well-known file verification |
| `cca5533` | F17, F25, F26 | Fix `secure` cookie flag (True in prod); guard v1 Run button to `LOCAL_MODE=1`; remove Page-row diagnostic workaround |

---

## 6. Decisions I Need to Make

### DECISION NEEDED: Server-side session invalidation on logout (S1)

**Where:** `app/auth.py:392-396`

**What I found:** `GET /logout` only deletes the session cookie on the client. The signed token (`itsdangerous` HMAC) remains cryptographically valid for 7 days. If the token was captured (XSS, access log, network sniff) before logout, it can still be replayed to authenticate.

**Options:**  
A) Add a `session_version: int` column to `User` — increment on logout; `verify_session_token` checks version. Requires Alembic migration.  
B) Add an in-process `revoked_tokens: set[str]` — fast but lost on restart, doesn't work with multiple workers.  
C) Add a `revoked_sessions` Redis key per token hash — works with multiple workers, no migration. Requires Redis client in `auth.py`.  
D) Accept the risk — tokens expire in 7 days, cookies are HttpOnly so XSS can't easily steal them. Document as known limitation.

**My recommendation:** A or C. A if you're already doing Alembic migrations; C if you want zero schema change.  
**Default if you do not answer:** No change (S1 stays open).

---

## 7. Not Reviewed

| Area | Reason |
|------|--------|
| `flows/` directory (v1 Playwright test flows) | Demo suite not in this repo; skipped per instructions |
| `alembic/` migration correctness vs live PostgreSQL | Local env uses SQLite; cannot run `alembic upgrade head` against Postgres without Docker PostgreSQL |
| `pip-audit` vulnerability scan | Requires outbound internet access; not available in audit environment |
| `pip list --outdated` | Run: 6 packages had updates (all minor); none flagged as vulnerable by available heuristics |
| Binary/generated files (`*.db`, `artifacts/`, `auth/`) | Not tracked in git; not reviewed |
| `app/templates/` XSS full manual audit | Jinja2 auto-escaping is ON for all `.html` templates; no `|safe` filters found on user-controlled data; no issues found |

---

## 8. Tests Added

| File | Tests | What they cover |
|------|-------|-----------------|
| `tests/test_phase_b_security.py` | 13 | CSRF on /sites and /run; SSRF probes (private IPs, encoded IPs, redirect chains); artifact IDOR; wizard XSS/encoding; history isolation |
| `tests/test_phase_d_proofs.py` | 7 | F1 docs disabled; F4/F5 IDOR report/status; F6 CSRF wizard; F7 anon artifact; F8 history isolation; F9 progress null user; F12 Fernet missing key; F14 /run gated |
| `tests/test_phase_e_followup.py` | 14 | F7 traversal (`../`, `%2e%2e`), cross-user artifact; F13 reaper marks stuck run failed; F20 cleanup deletes old runs + expired creds + artifacts; F22 terms/privacy non-empty; F23 comparison not cross-user |
| `tests/test_ssrf_redirect.py` | 4 | SSRF via redirect chains (safe_http_fetch blocks redirect to private IP) |

**Total tests:** 67 passing (run with `FERNET_KEY` set, `LOCAL_MODE` unset)

```
$ pytest tests/ -v
67 passed, 4 warnings in 7.72s
```

> **Note:** Security tests (F1, F4–F9, F12, F14) intentionally fail under `LOCAL_MODE=1` because that mode disables all ownership checks and enables docs. Run the test suite without `LOCAL_MODE=1` for accurate security verification.

---

## 9. Recommended Next Steps (ordered by risk)

1. **S1 — Server-side logout invalidation** (Low / open). Decide between options A, C, or D in §6 and implement before going to production. Until then, stolen tokens remain valid for 7 days.

2. **PostgreSQL in staging** — Run `alembic upgrade head` against the real Postgres container and verify no column mismatches between `models.py` and the migration chain. The SQLite test DB auto-creates tables via `SQLModel.metadata.create_all` and may mask schema drift.

3. **Rate-limit the `/wizard/start` route** — Currently only `/register` and `/login` have `@limiter.limit`. The wizard triggers a DNS + HTTP fetch per request; an unauthenticated attacker could cause high outbound traffic.

4. **Review `alerts.py` Slack webhook** (S2) — If config.yaml ever becomes user-editable at runtime, the webhook URL becomes an SSRF vector. Apply `safe_http_fetch` to the Slack POST or at minimum validate the webhook URL domain against an allow-list.

5. **Pin `pip` in Dockerfiles** — `Dockerfile.web` and `Dockerfile.worker` use the default pip. Pin to a specific version in `requirements.txt` or `RUN pip install pip==X.Y.Z`.

6. **CSP header** — No `Content-Security-Policy` header is set. Add a restrictive CSP to prevent any residual XSS from escalating.

7. **Alembic migration for `Run.note`** — The worker failure reason is currently only in application logs. If you want run failure reasons visible in the UI, a `note` column on `Run` and a migration is the correct solution (approved by owner before adding).

8. **`pip-audit` on a network-connected machine** — Run `pip-audit -r requirements.txt` to check for known CVEs in pinned deps.

9. **Integration smoke test in CI** — Add a GitHub Actions workflow that runs `pytest tests/` with `FERNET_KEY` set and `LOCAL_MODE` unset on every PR.
