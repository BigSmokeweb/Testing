# AUDIT.md: Full-Repo Bug Hunt Instructions for the Agent

Save this file in the project root. When the user says **"run audit"** (or "scan the repo"), follow every section below in order. Read `PLAN.md` and `PLAN2.md` first; they define what the project is supposed to do.

## 0. Your job
Scan the ENTIRE repository, find bugs yourself, prove they are real, fix the clear ones safely, and **stop and ask me** whenever a decision needs my opinion. Do not guess about product behaviour. Do not hide problems.

## 1. Ground rules
1. Never skip files. If you cannot read something (binary, too large, generated), list it under "Not reviewed" with the reason.
2. Never claim a bug without evidence: a failing test, a reproduction command, a stack trace, or the exact code line plus the reasoning. Mark anything unproven as **"Suspected"**.
3. Never claim something works unless you ran it. Say "ran and passed" or "not run".
4. Do not add features. Do not refactor for style. Do not change behaviour that PLAN.md / PLAN2.md define. Fix bugs only.
5. Do not touch secrets: never print, copy, or commit `.env`, `auth/state.json`, `FERNET_KEY`, passwords, or tokens. If you find one committed in git, report it immediately.
6. Make one small commit per fix, with a message that names the bug. Never rewrite git history or force push.
7. Before changing anything, make sure the work tree is committed or stashed so every fix can be rolled back.
8. Never delete data, drop tables, or run anything against a real company/production site. Use the demo site (`config.demo.yaml`) or local test data.

## 2. Phase A: Map the repo (do this first, show me the result)
1. List every file and folder (respect `.gitignore`, but also check that ignored files such as `.env`, `auth/`, `artifacts/`, `*.db` are not tracked: `git ls-files`).
2. Write a short map: entry points, routes, DB models, background jobs, templates, config, tests, scripts.
3. Identify the dependency list and flag unpinned, unused, or vulnerable packages (run `pip list --outdated` and `pip-audit` if available).
4. Check that the app starts: run the install, migrations, and start commands from README. Record any failure as a bug.

Output a section titled **"Repo map"** before moving on.

## 3. Phase B: Run everything that can be run
1. Run existing tests (`pytest`). Record failures.
2. Run linters/type checks if configured (`ruff`, `flake8`, `mypy`). If none exist, run `python -m compileall .` and `python -m pyflakes .` (install if needed).
3. Run the demo suite: `AUTOQA_CONFIG=config.demo.yaml python -m app.runner suite chromium` with the demo server on port 8001. Expected: 2 flows pass, 1 fails on purpose, never-click guard skips "Delete account", 1 broken link. Any difference is a bug.
4. Start the web app and hit every route (GET and POST) with valid, empty, and malicious input. Record 500 errors, tracebacks, and unescaped output.

## 4. Phase C: Read every file with these checklists

For each file, check all categories that apply.

### C1. Correctness
- Off-by-one, wrong operators, inverted conditions, wrong default values
- Unhandled `None`, empty lists, missing keys, wrong types
- Exceptions swallowed silently (`except: pass`) hiding failures
- Resource leaks: browsers, contexts, pages, files, DB sessions, threads not closed on error paths
- Race conditions: shared state between threads/workers, double-clicking Run, concurrent runs
- Time handling: naive vs timezone-aware datetimes, comparisons between them
- Paths: Windows vs Linux separators, relative paths depending on the working directory
- Status logic: flaky / failed / skipped / session_expired classified correctly; an expired session must NEVER be reported as a test failure

### C2. Testing accuracy (this is a testing tool, false results are the worst bug)
- A step can pass without any real assertion
- A failure can be reported as pass, or a pass as failure
- Retry logic marks the wrong status or keeps the wrong evidence
- Screenshots/traces missing or attached to the wrong step/run
- Console and network monitors miss events or record duplicates
- Load-time measurement wrong or zero when it should not be
- Link checker false positives (redirects, HEAD vs GET, auth cookies) or false negatives
- The "new failures since last run" comparison compares the wrong runs/engines

### C3. Security (highest priority for v2)
- **SSRF:** any place a user-supplied URL is fetched or opened without `validate_url`; redirects not re-validated; DNS rebinding; IPv6; decimal/octal/hex IP forms; `user:pass@host`; non-http schemes
- **Ownership verification:** can it be bypassed, reused by another user, or forged
- **AuthN/AuthZ:** every route that returns user data checks login AND ownership (IDOR: change `/report/5` to `/report/6`)
- **Passwords/sessions:** hashed with argon2, cookies HttpOnly/Secure/SameSite, session fixation, logout really invalidates
- **CSRF** on every state-changing POST
- **Injection:** SQL (raw queries/f-strings), template injection, command injection (`subprocess`, `os.system`), path traversal in file serving (`artifacts/`), unsafe deserialization
- **XSS:** untrusted data (page titles, console messages, URLs, error text) rendered unescaped (`|safe`, `innerHTML`)
- **Secrets:** hardcoded keys, tokens in logs, credentials in reports or screenshots, `extra_headers` leaking to third-party domains, `state.json` tracked in git
- **Credentials handling:** encrypted at rest, deleted after the run, never logged
- **Rate limits and quotas** actually enforced (not just displayed)
- **DoS:** unbounded crawl, huge pages, infinite redirects, missing timeouts, unbounded uploads, queue flooding
- **Docker/deploy:** containers running as root, exposed ports (Postgres/Redis open to the internet), debug mode on, default passwords

### C4. Reliability and operations
- Missing timeouts on network calls and Playwright waits
- Jobs stuck in `running` after a crash (no recovery)
- Cleanup jobs that delete the wrong things or never run
- Migrations missing or not matching models
- Logging: too little to debug, or too much sensitive data
- Config: missing keys crash the app with unclear errors

### C5. UI/UX bugs
- Broken links and routes, 404s, templates referencing missing variables
- Forms with no validation messages, double-submit, lost input on error
- Empty states and error states missing
- Mobile layout broken, unreadable contrast, missing alt text/labels
- Polling/progress page never finishing or looping

### C6. Code health that causes bugs
- Duplicate logic that has already diverged
- Dead code that hides a real code path
- Misleading names or comments that contradict behaviour
- Missing tests for security-critical code (`safety.py`, `auth.py`, `creds.py`)

## 5. Phase D: Prove each finding
For every finding, do one of these before reporting it as confirmed:
- Write a failing test (preferred) in `tests/`, or
- Give an exact reproduction (command + input + actual vs expected output)

If you cannot prove it, label it **Suspected** and say what evidence is missing.

## 6. Phase E: When to FIX and when to ASK

### Fix without asking (then report) only if ALL are true
- The bug is clear-cut (a crash, typo, wrong operator, missing `await`/`close()`, unescaped output, missing timeout)
- The correct behaviour is stated in PLAN.md / PLAN2.md or is obvious
- The fix touches a small, local area and does not change user-visible behaviour
- You can add or run a test that proves the fix

### STOP and ASK ME when ANY of these is true
- The fix changes **what users see or how the product behaves** (wording, flow, defaults, limits, statuses)
- The plans do not say what the correct behaviour is, or two parts of the plans contradict each other
- There are **multiple valid fixes** with different trade-offs (e.g. block vs warn, fail vs skip, store vs delete)
- The fix needs a **new dependency, new service, schema change, or migration**
- The fix touches **security policy** (what URLs are allowed, limits, retention, what is logged)
- The fix could **delete or migrate existing data**
- It affects **cost, performance, or hosting** (e.g. needs more RAM, a paid service)
- You are unsure whether something is a bug or intended
- A change would be **large** (more than about 50 lines or more than 3 files)
- I would need to supply information you do not have (domain names, API keys, legal text, branding, company rules)

### How to ask
Ask in this exact format, one decision at a time (maximum 3 questions per message):

```
DECISION NEEDED: <short title>
Where: <file:line>
What I found: <1-2 sentences, with evidence>
Options:
  A) <option> - <effect, risk>
  B) <option> - <effect, risk>
  C) <option, if any>
My recommendation: <A/B/C> because <reason>
Default if you do not answer: no change
```

Do NOT continue on that finding until I answer. You may continue auditing other areas while waiting. Never silently choose for me on a decision that matches the list above.

## 7. Phase F: Report
When the audit finishes, produce `AUDIT_REPORT.md` in the repo root with these sections:

1. **Summary**: counts by severity, what was run, what was not, overall risk in 3 sentences
2. **Repo map** (from Phase A)
3. **Confirmed bugs**: table with ID, severity, file:line, description, evidence, status (Fixed / Open / Waiting for my decision)
4. **Suspected issues**: with what evidence is missing
5. **Fixes made**: commit hash + one-line explanation each
6. **Decisions I need to make**: all open DECISION NEEDED items
7. **Not reviewed**: files/areas skipped and why
8. **Tests added**: list
9. **Recommended next steps**: ordered by risk

Severity scale:
- **Critical**: security hole, data leak, false test results, app cannot start
- **High**: feature broken, data loss, crash on common path
- **Medium**: wrong behaviour on edge cases, missing limits/timeouts
- **Low**: cosmetic, minor UX, code health

## 8. Honesty rules
- Say clearly what you did not verify.
- Do not pad the report with style opinions. No bug, no entry.
- If you find nothing in a category, write "No issues found in <category> (checked: <what you checked>)". Do not invent findings.
- If a tool is not installed or a command fails, say so and try an alternative; do not skip the check silently.
- If you are about to run out of context or time, stop, save progress to `AUDIT_REPORT.md`, and tell me exactly where you stopped so the audit can resume.

## 9. Quick commands I may use
- `run audit`: execute Phases A to F
- `audit security`: only C3 + Phase D to F
- `audit tests`: only Phase B, C2 + report
- `audit ui`: only C5 + report
- `recheck <bug id>`: re-verify a specific finding after a fix
- `resume audit`: continue from `AUDIT_REPORT.md`
