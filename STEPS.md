# AutoQA: Step-by-Step Build Guide (Antigravity)

Do the steps in order. Do not start the next step until the current "Test" passes. Commit to git after every working step.

---

## STEP 0: Project setup (you, in terminal) ~10 min

1. Create a folder called `autoqa` and open it in Antigravity.
2. Put `PLAN.md` (the other file) in the folder root.
3. Open the terminal and run:

```
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux
pip install playwright fastapi uvicorn jinja2 sqlmodel pyyaml requests
playwright install
git init
```

4. Create `.gitignore`:

```
venv/
auth/
artifacts/
config.yaml
*.db
__pycache__/
.env
```

5. Create `config.example.yaml`:

```yaml
base_url: "https://your-company-site.example.com"
login_url_hints:
  - "login"
  - "signin"
  - "okta"
  - "microsoftonline"
  - "accounts.google"
allowed_domains:
  - "your-company-site.example.com"
never_click:
  - "delete"
  - "remove"
  - "pay"
  - "place order"
  - "submit order"
  - "logout"
  - "sign out"
extra_headers: {}
alert:
  type: "none"
  slack_webhook: ""
engines:
  - chromium
```

6. Copy it to `config.yaml` and put your real company URL and domain in it. (`config.yaml` is gitignored.)

7. Run `git add . && git commit -m "setup"`.

**Test:** `python -c "import playwright, fastapi, sqlmodel; print('ok')"` prints `ok`.

---

## STEP 1: Give the agent its rules (once) ~2 min

Paste this to the Antigravity agent:

```
Read PLAN.md fully and follow it strictly. Work on one step at a time, only change the files I name, and do not add features that are not in PLAN.md. After each step, tell me exactly how to run and test it. Do not launch your own browser to log into the company site; I will do logins manually. Never ask me for passwords.
```

---

## STEP 2: Scaffold ~5 min

Paste:

```
Create the folder structure from PLAN.md with empty placeholder files (app/, flows/, auth/, artifacts/, app/templates/). Create requirements.txt (playwright, fastapi, uvicorn, jinja2, sqlmodel, pyyaml, requests). Write app/config.py that loads config.yaml (fall back with a clear error if it is missing) and exposes the values as a simple object. Only touch those files.
```

**Test:** `python -c "from app.config import load_config; print(load_config())"` (or whatever the agent tells you) prints your config.

---

## STEP 3: Session connect + check (MOST IMPORTANT) ~30 min

Paste:

```
Write app/session.py with:
1. connect(): opens a visible Chromium at base_url from config, waits until I press Enter in the terminal, then saves storageState to auth/state.json.
2. is_valid(): opens a headless browser with that storage state, visits base_url, returns False if the final URL contains any of the login_url_hints from config.yaml or if the state file is missing.
3. A CLI: `python -m app.session connect` and `python -m app.session check` (check prints VALID or EXPIRED).
Only change app/session.py and app/config.py.
```

**Test (you do this yourself, not the agent):**
1. Run `python -m app.session connect`.
2. In the browser, log in manually through SSO + MFA.
3. Return to the terminal and press Enter.
4. Run `python -m app.session check`. It must print `VALID`.
5. Delete `auth/state.json` and run check again. It must print `EXPIRED`.

**If Cloudflare blocks the browser:** set `base_url` to `https://www.saucedemo.com` temporarily and continue building. Ask IT for a skip rule for your IP or a secret header (then put the header in `extra_headers`).

**If it says EXPIRED right after a good login:** your SSO may reject saved sessions from automated browsers. Stop and tell me before continuing.

Commit.

---

## STEP 4: Runner core ~60 min

Paste:

```
Write app/runner.py and flows/example_flow.py.

runner.py:
- Load a flow file from flows/ (it defines NAME and run(page, step, base_url)).
- Create a Playwright (sync) browser context for the chosen engine (chromium, firefox or webkit) using auth/state.json and extra_headers from config.
- Start tracing before the flow.
- Implement step(description, fn): time it, catch exceptions, on failure capture a screenshot into artifacts/, record status and error message, and mark all remaining steps as skipped.
- If the flow fails, retry it once in a fresh context. If the retry passes, status = "flaky".
- Save the trace zip into artifacts/ only when the flow failed or was flaky.
- Return a structured result (dataclasses). No database yet.
- CLI: python -m app.runner flows/example_flow.py chromium

flows/example_flow.py: 3 steps against base_url using expect() assertions (URL check, element visible, text present).
Only change these two files.
```

**Test:**
1. Run `python -m app.runner flows/example_flow.py chromium`. It should print all steps passed.
2. Break one assertion on purpose (wrong text). Run again. You should see a failed step, a skipped remaining step, a screenshot in `artifacts/`, and a trace zip.
3. Open the trace: `playwright show-trace artifacts/<file>.zip`.
4. Fix the assertion back.

Commit.

---

## STEP 5: Monitors ~30 min

Paste:

```
Write app/monitors.py with attach(page, collector) that records: console messages of type "error", network responses with status >= 400 (url, method, status, page url, timestamp), and page load time from navigation timing. Integrate it into runner.py so each flow result includes these lists. Only change monitors.py and runner.py.
```

**Test:** run the example flow. The output should now list console errors and failed requests (likely a few on a real site, possibly none on a clean one). Point a step at a non-existent URL on your site to confirm a 404 is recorded.

Commit.

---

## STEP 6: Database ~30 min

Paste:

```
Write app/models.py with SQLModel tables exactly as in PLAN.md, using SQLite (autoqa.db). Add save_run(result) that stores a full run: run, flow_results, step_results, console_logs, network_failures. Then in runner.py add run_suite(engine): run all .py files in flows/ (except files starting with underscore), check session validity first (if invalid: store a run with status "session_expired" and stop), run each flow, save everything with save_run. Add CLI: python -m app.runner suite chromium. Only change models.py and runner.py.
```

**Test:**
1. Run `python -m app.runner suite chromium`.
2. Open `autoqa.db` with any SQLite viewer (or `sqlite3 autoqa.db "select * from runs;"`) and confirm rows exist.
3. Delete `auth/state.json`, run the suite again, and confirm a run is stored with status `session_expired` and no flows ran.
4. Reconnect the session (Step 3).

Commit.

---

## STEP 7: Dashboard ~60 min

Paste:

```
Build app/main.py (FastAPI) with Jinja2 templates in app/templates/. Pages:
1. Home: shows session status (valid/expired), an engine dropdown, a Run button that starts run_suite in a background thread, and the latest run summary. Show a clear "Session expired, run: python -m app.session connect" message when expired.
2. History: table of runs with date, engine, status, counts of passed/failed/flaky flows.
3. Report: per-flow results, per-step results with status and error messages, screenshots inline, trace file download links, console errors and failed network requests.
Serve artifacts/ as static files. Plain, clean CSS in a single file, no JS frameworks. Run with: uvicorn app.main:app --reload
Only change app/main.py, app/templates/, and a static CSS file.
```

**Test:** open http://127.0.0.1:8000, click Run, wait for it to finish, open the report. Confirm failed steps show screenshots and trace links.

Commit.

---

## STEP 8: Your real flows ~45 min

You decide the assertions. For each flow, write down on paper first: page URL, what proves it loaded, what proves the key action worked. Then paste (fill in the brackets):

```
Create flows/dashboard_loads.py for my company site. Steps: go to base_url + "[PATH]", assert the URL contains "[TEXT]", assert the heading "[HEADING TEXT]" is visible, assert "[ELEMENT/TEXT]" is visible. Use get_by_role / get_by_text locators. Follow the flow format in PLAN.md.
```

Make 2 to 3 flows (suggestion: dashboard loads, main navigation menu works, one key form validates). Do NOT script anything that deletes, pays, or submits real data.

**Test:** run the full suite from the dashboard. Break something on purpose (wrong heading) and confirm the tool reports it as failed.

Commit. **End of tonight's target.**

---

## STEP 9 (tomorrow): Retry/flaky polish + comparison ~20 min

```
Update the report so flaky flows are shown in a separate colour, and add a "New failures since last run" section that compares the latest run to the previous run for the same engine. Only change main.py and the templates.
```

## STEP 10 (tomorrow): Guards ~30 min

```
Write app/guards.py: block any request outside allowed_domains from config (use page.route to abort them and log it), and provide a safe_click(locator) helper that refuses to click any element whose text or aria-label matches an entry in never_click and records the step as skipped with the reason. Integrate into runner.py. Only change guards.py and runner.py.
```

**Test:** add a step that clicks a button labelled "Logout" and confirm it is refused.

## STEP 11 (tomorrow): Link check ~30 min

```
Write app/linkcheck.py: from start pages listed in config.yaml (add a link_check_pages list), collect internal links with Playwright, then check each with an HTTP request using the saved session cookies (status only, never click). Store results in link_checks and show broken links in the report. Only change linkcheck.py, models.py, main.py, templates.
```

## STEP 12 (tomorrow): Alerts ~15 min

```
Write app/alerts.py: if a run has any failed flows, send a Slack webhook message with the summary and a link to the report page. Config-driven; do nothing if alert.type is "none". Only change alerts.py and runner.py.
```

---

## Rules while building
- One step at a time. Test it yourself before moving on.
- If the agent edits files you didn't name, reject the change.
- If something breaks, paste the full error and say: "Fix only this error, change nothing else."
- Never paste `state.json`, passwords, or real company URLs into chats or public repos.
- Commit after every working step so you can roll back.

## Before posting on LinkedIn
- Get your company's OK.
- Demo against a public practice site (for example saucedemo.com), not your company site.
- Commit `config.example.yaml` only; confirm `auth/`, `artifacts/`, `config.yaml` and `*.db` are not in the repo.
