# AutoQA v2: Step-by-Step Build Guide (Antigravity)

Do the steps in order. Test every step yourself before the next. Commit after every working step.
Assumption: your existing AutoQA project (FastAPI + Jinja2 + Playwright) is the base. If your Antigravity site uses a different stack, tell the agent in Step 1 and adjust.

---

## STEP 0: Prepare (you) ~15 min

1. Make sure v1 still works and is committed. Then create a branch: `git checkout -b v2-public`.
2. Put `PLAN2.md` in the project root (next to `PLAN.md`).
3. Install Docker Desktop (needed later) and install extra packages:

```
pip install argon2-cffi cryptography redis rq alembic psycopg2-binary email-validator slowapi itsdangerous dnspython
pip freeze > requirements.txt
```

4. Paste once to the agent:

```
Read PLAN.md and PLAN2.md fully. v2 is a public multi-user mode; v1 (local company testing) must keep working. Follow the plans strictly, work on one step at a time, only change the files I name, and do not add features that are not in the plans. After each step, tell me exactly how to run and test it. Never ask me for real credentials.
```

---

## STEP 1: Database upgrade + user accounts ~60 min

```
Switch the database from SQLite to PostgreSQL using a DATABASE_URL environment variable (default to local SQLite so v1 still works). Add Alembic migrations. Add the users table from PLAN2.md. Write app/auth.py: register (email + password, argon2 hash, email-validator), login, logout, signed HTTP-only cookie sessions, CSRF tokens on every POST form, rate limiting on login/register (slowapi), generic error messages ("invalid email or password"). Add templates: register.html, login.html, and a navbar showing login state. Protect /history and /report/{id} so they require login (v1 company dashboard stays reachable only when env LOCAL_MODE=1). Only change app/models.py, app/auth.py, app/main.py, templates, requirements.txt, alembic/.
```

**Test:**
1. Register, log out, log in, wrong password gives a generic error.
2. Open `/history` while logged out and you get redirected to login.
3. Try 10 wrong logins quickly and you get rate limited.
4. Check the DB: the password column holds an argon2 hash, not text.

---

## STEP 2: Sites + domain ownership verification ~60 min

```
Add the sites table. Write app/sites.py and templates: "My sites" page where a logged-in user adds a site URL (normalise to scheme + domain, max 2 sites per user). Generate a random verify_token per site. Show two verification methods from PLAN2.md (DNS TXT record at _autoqa.<domain> = autoqa-verify=<token>, or file at /.well-known/autoqa-<token>.txt containing the token). Add a "Verify now" button that checks DNS (dnspython) then the file (requests, 5 s timeout, no redirects to other domains), and sets verified_at on success. Users can only see and verify their own sites. Only change sites.py, models.py, main.py, templates.
```

**Test:**
1. Add a domain you own and try Verify now: it must fail before you add the record.
2. Add the TXT record or file, then Verify now: it must succeed.
3. Log in as a second user: you must not see the first user's sites.

---

## STEP 3: URL safety / SSRF protection ~45 min

```
Write app/safety.py with: validate_url(url) that allows only http/https, rejects credentials in the URL, resolves the hostname (all A/AAAA records) and rejects any loopback, private, link-local, multicast, reserved or cloud-metadata IP (use the ipaddress module), and returns a reason string on rejection. Add install_request_guard(context) that uses context.route to re-validate EVERY request URL (including redirects) at run time and abort blocked ones, recording them. Apply validate_url when adding a site and before any run. Add unit tests in tests/test_safety.py covering: localhost, 127.0.0.1, 10.0.0.5, 192.168.1.1, 169.254.169.254, [::1], a hostname resolving to a private IP (mock DNS), a normal public URL, and URLs with user:pass@. Only change safety.py, sites.py, tests/.
```

**Test:** `pytest tests/test_safety.py` passes. Then try adding `http://localhost:8000` and `http://169.254.169.254` as a site: both must be rejected.

---

## STEP 4: Queue + worker + limits ~60 min

```
Add Redis + RQ. Write app/jobs.py: enqueue_run(user_id, site_id, mode) that first enforces limits from PLAN2.md (site must be verified, validate_url passes, 5 runs/day/user using the usage table, 1 concurrent run per user, 3 concurrent globally) and creates a run with status "queued". Write app/worker.py: an RQ worker entry that picks a job, sets status running, calls a placeholder run_public_checks(run_id) (just sleeps 3 s and marks completed for now), enforces a 5-minute hard timeout, and sets failed on exception. Add a "Run test" button on a site page that enqueues, and a /runs/{id}/status JSON endpoint. Only change jobs.py, worker.py, main.py, models.py, templates.
```

**Test:** run Redis (`docker run -p 6379:6379 redis`), start `rq worker` (or your worker entry) and the web app. Click Run test: status goes queued, running, completed. Click it 6 times in a day: the 6th is refused. Click twice quickly: second is refused (concurrent limit).

---

## STEP 5: Public checks engine ~90 min

```
Write app/public_checks.py with run_public_checks(run_id): launch chromium (headless) with a fresh context, install_request_guard, attach the existing monitors. Crawl the verified site starting at its URL: same domain only, max 25 pages, depth 2, 5-minute budget. For each page record: HTTP status, load time (navigation timing), console errors, failed requests, a screenshot saved under artifacts/<run_id>/ (always for errored pages), into a new pages table. Collect internal links and check each with an HTTP status request (broken link table already exists). Never click buttons or submit forms. Compute a score (percentage of pages OK). Connect it to worker.py replacing the placeholder. Only change public_checks.py, worker.py, models.py.
```

**Test:** verify a site you own that has one broken link and one console error. Run it and confirm the report data contains both. Then try a site with 100+ pages and confirm it stops at 25 pages / 5 minutes.

---

## STEP 6: Test-credentials login (Mode A) ~75 min

```
Write app/creds.py: Fernet encryption using FERNET_KEY from the environment, functions to store (encrypted username/password with expires_at = now + 1 hour) and delete credentials, plus a cleanup function. Extend the wizard form with an optional "Test login" section (login URL, username, password, with a note: use a dedicated test account, MFA/SSO/CAPTCHA are not supported). In public_checks.py add attempt_login(page, creds): find the username/password fields and submit using sensible heuristics (input[type=password], nearest text/email input, submit button), then decide success if the URL leaves the login page or the password field disappears. Detect and report separately: CAPTCHA elements, MFA prompts (one-time code fields), or SSO redirects to other domains, and mark the run "expired" with a clear message instead of failing the tests. Never log credentials, mask the password field, and do not take screenshots after typing credentials. Delete credentials when the run ends (use try/finally). Only change creds.py, public_checks.py, templates, models.py.
```

**Test:** use a practice site such as saucedemo.com. (Note: it's a public practice site you don't own; for testing only, temporarily allow it in your dev environment via an env flag `SKIP_OWNERSHIP_FOR_DEV=1`, and never enable that flag in production.) Confirm: login works, the credentials row is gone after the run, and grep the logs for the password (must find nothing).

---

## STEP 7: Retention + abuse protection ~30 min

```
Add a cleanup job (runs hourly via RQ scheduler or a simple loop in the worker) that deletes artifacts and runs older than 30 days and any expired credentials. Add account deletion (user can delete their account and all sites, runs, screenshots). Add global per-IP rate limiting on the register and run endpoints. Log security events (blocked URL, failed login, limit hit) to a separate log file without sensitive data. Only change worker.py, auth.py, main.py, creds.py.
```

**Test:** change retention to 1 minute temporarily and confirm old data is deleted. Delete a test account and confirm all its files are gone.

---

## STEP 8: UI enhancement ~120 min

Do these as separate prompts so you can review each.

**8a Landing page**
```
Redesign the landing page: a hero with one URL input and a button "Test my website", a short "What we test" list (page loads, console errors, broken links, failed requests, load time, optional login check), a short "How it works" in 3 steps, and a footer with Terms and Privacy links. Clean modern style in the existing CSS file, mobile friendly, no external CDN. If the visitor is not logged in, submitting the URL sends them to register/login and then continues the wizard with that URL prefilled. Only change landing template and CSS.
```

**8b Wizard**
```
Build a 3-step wizard page flow: Step 1 URL (validated server-side), Step 2 Verify ownership (shows both methods, copy buttons, Verify now), Step 3 Optional test login then "Start test". Show a progress indicator. Add the "I am authorized to test this site" checkbox, required. Only change templates and sites.py/main.py routes.
```

**8c Live progress page**
```
Add a progress page /runs/{id} that polls /runs/{id}/status every 3 seconds with small vanilla JS and shows queued/running/completed, pages checked so far, and elapsed time. On completion, redirect to the report. Show friendly messages for blocked/expired/failed states with next steps. Only change the progress template, main.py, one JS file.
```

**8d Report**
```
Improve the report page: top summary with a score and counts (pages checked, errors, broken links, avg load time), failures listed first with screenshots, a collapsible list of OK pages, a "Copy issue text" button per failure (plain text with URL, error, page), and a comparison with the previous run for the same site ("new issues", "fixed"). Add print-friendly CSS. Only change report template, CSS, small JS.
```

**8e Polish**
```
Add empty states (no sites, no runs), error pages (404/500), flash messages, loading states on buttons, keyboard-accessible forms, and a consistent navbar. Only change templates and CSS.
```

**Test:** go through the whole flow on your phone and desktop as a new user.

---

## STEP 9: Dockerize ~60 min

```
Create docker/Dockerfile.web (python slim, non-root user, uvicorn) and docker/Dockerfile.worker (based on mcr.microsoft.com/playwright/python, non-root user, runs the RQ worker). Create docker-compose.yml with services: web, worker, redis, postgres, caddy, with named volumes for postgres data and artifacts, healthchecks, restart: unless-stopped, and the worker on a separate Docker network that has outbound internet access but cannot reach postgres/redis except through the internal network. Add .env.example listing every variable (DATABASE_URL, REDIS_URL, FERNET_KEY, SECRET_KEY, LOCAL_MODE, DOMAIN) with no real values. Add a Caddyfile that serves https://{$DOMAIN} and reverse-proxies to web. Add a README section "Deploy". Only create/change these files.
```

**Test locally:** `docker compose up --build`. Register, add a site, run a test end to end. Make sure the worker container cannot connect to private ranges (see Step 10 firewall note).

---

## STEP 10: Deploy to a VPS ~90 min (you)

1. Rent a VPS (4 GB RAM minimum; Hetzner, DigitalOcean, etc.), Ubuntu 22.04 or 24.04.
2. Point your domain's A record to the VPS IP.
3. Secure the server:
   - Create a non-root user, disable password SSH login (keys only).
   - `ufw allow 22,80,443` then `ufw enable`.
   - Enable unattended security updates.
4. Install Docker and the compose plugin.
5. Copy the project (git clone). Create `.env` with strong random values (`python -c "import secrets;print(secrets.token_urlsafe(48))"` for SECRET_KEY; `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` for FERNET_KEY).
6. `docker compose up -d --build`, then run migrations: `docker compose exec web alembic upgrade head`.
7. **Block internal ranges from the worker** (defense in depth against SSRF/DNS rebinding). Example on the host:
```
sudo iptables -I DOCKER-USER -s <worker_subnet> -d 10.0.0.0/8 -j DROP
sudo iptables -I DOCKER-USER -s <worker_subnet> -d 172.16.0.0/12 -j DROP
sudo iptables -I DOCKER-USER -s <worker_subnet> -d 192.168.0.0/16 -j DROP
sudo iptables -I DOCKER-USER -s <worker_subnet> -d 169.254.0.0/16 -j DROP
```
(Adjust so the worker can still reach redis/postgres on the internal network; ask me or the agent for the exact rules for your compose network.)
8. Set up automatic Postgres backups (daily `pg_dump` to another location) and log rotation.
9. Add uptime monitoring (UptimeRobot, free) on your domain.

**Test:** visit https://yourdomain, register, verify a site, run a test, view the report.

---

## STEP 11: Pre-launch checklist (do not skip)

- [ ] `SKIP_OWNERSHIP_FOR_DEV` is NOT set in production
- [ ] Try these as a normal user: `http://localhost`, `http://127.0.0.1:5432`, `http://169.254.169.254`, a domain you don't own. All must be blocked
- [ ] A site that redirects to an internal IP is blocked
- [ ] Credentials are gone from the DB after a run, and appear in no log
- [ ] Limits work (5 runs/day, concurrency, 25 pages, 5 minutes)
- [ ] Terms and Privacy pages exist and the authorization checkbox is required
- [ ] Account deletion removes all data
- [ ] Backups restore correctly (test one)
- [ ] `.env`, `auth/`, `artifacts/`, `*.db` are not in git
- [ ] You tested the full flow on phone and desktop
- [ ] Soft launch: invite 3 to 5 people first, watch logs for a week

---

## Rules while building
- One step at a time. Test before moving on. Commit after each step.
- If the agent edits files you didn't name, reject the change.
- If something breaks, paste the full error and say: "Fix only this error, change nothing else."
- Never paste real credentials, `.env`, or `FERNET_KEY` into the agent chat.
- Security steps (3, 6, 7, 10, 11) are not optional. A public testing tool is attractive to abusers.

## Later (v3 ideas, in order of value)
1. Mode C: remote browser login for MFA/SSO sites
2. Scheduled runs and email alerts
3. axe-core accessibility checks
4. Firefox/WebKit options
5. Lighthouse scores
6. CI/CD webhook trigger
