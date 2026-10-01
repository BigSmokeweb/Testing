# AutoQA: Project Context

## Goal
A local tool that runs scripted Playwright tests against ONE company website, verifies each step with explicit assertions, and produces a trustworthy pass/fail report with evidence. Runs only on the developer's laptop. Single user. No registration, no cloud.

## Hard constraints
- The target site uses Cloudflare, SSO and MFA. NEVER automate the login or try to bypass bot protection (no stealth plugins).
- Login is done manually once; the session is saved with Playwright storageState to `auth/state.json`. All tests reuse it.
- If the session is expired, STOP the run and report "Session expired, reconnect". Never report this as a test failure.
- No passwords are stored anywhere.
- Stack: Python 3.11+, Playwright (Python), FastAPI, Jinja2, SQLModel + SQLite. No Redis, no Celery, no Cloudinary, no Next.js.
- Do NOT add features that are not listed here. If something seems necessary, ask first.
- Only change the files named in each instruction.

## Statuses
- Flow result: passed / failed / flaky / skipped. A failed flow is retried once in a fresh context; pass on retry = flaky.
- Step result: passed / failed / skipped. After a failed step, remaining steps are skipped.
- Run status: completed / session_expired.

## v1 features
1. Connect session (visible browser, manual login, save storageState)
2. Session validity check before every run
3. Flows = Python files in `flows/`; every step has an explicit assertion
4. Engines: chromium, firefox, webkit (selectable)
5. On failure: screenshot + Playwright trace zip
6. Passive monitors per flow: console errors, network responses with status >= 400, page load time
7. Guards: domain allow-list (block anything outside it), never-click list (delete, pay, submit order, logout)
8. Link check (internal links, HTTP status only)
9. Report page, run history, comparison with the previous run (highlight new failures)
10. Failure alert (Slack webhook)

## Not in v1
AI navigation, video recording, parallel runs, real-device testing, user accounts, CI/CD, Lighthouse, cloud deployment.

## Database tables (SQLite)
- suites(id, name, description)
- flows(id, suite_id, name, file_path, enabled)
- runs(id, suite_id, engine, status, started_at, finished_at, duration_ms, session_valid)
- flow_results(id, run_id, flow_id, status, attempts, duration_ms, trace_path)
- step_results(id, flow_result_id, step_index, description, status, error_message, screenshot_path, duration_ms)
- console_logs(id, flow_result_id, level, message, page_url, timestamp)
- network_failures(id, flow_result_id, url, method, status_code, page_url, timestamp)
- link_checks(id, run_id, source_url, target_url, status_code, ok)

## Folder structure
```
autoqa/
  app/
    main.py        # FastAPI routes
    config.py      # loads config.yaml
    runner.py      # runs flows, retry, classification
    session.py     # connect / validate storageState
    guards.py      # allow-list + never-click
    monitors.py    # console + network listeners
    linkcheck.py
    alerts.py
    models.py      # SQLModel tables
    templates/     # Jinja2 pages
  flows/           # one file per test flow
  auth/            # state.json (gitignored)
  artifacts/       # screenshots, traces (gitignored)
  config.yaml      # real values (gitignored)
  config.example.yaml
  PLAN.md
  requirements.txt
  .gitignore
```

## Flow format
Each file in `flows/` defines:
- `NAME` (str)
- `run(page, step, base_url)`

`step(description, fn)` runs `fn`, times it, catches errors, captures a screenshot on failure, and records the result. Assertions use `playwright.sync_api.expect`.

Example:
```python
import re
from playwright.sync_api import expect

NAME = "Dashboard loads"

def run(page, step, base_url):
    step("Open dashboard", lambda: page.goto(base_url + "/dashboard"))
    step("URL is dashboard", lambda: expect(page).to_have_url(re.compile("/dashboard")))
    step("Heading visible", lambda: expect(page.get_by_role("heading", name="Dashboard")).to_be_visible())
```

## Accuracy rules
- A pass must mean something: every step has an assertion.
- Expired session is never a test failure.
- Flaky results are labelled, never hidden.
- Every failure has a screenshot and a trace.
- Prefer role/text locators over brittle CSS selectors.
