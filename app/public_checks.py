import os
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from playwright.sync_api import sync_playwright
from sqlmodel import Session, select

from app.creds import delete_credentials, get_credentials
from app.models import ConsoleLog, FlowResultModel, LinkCheck, NetworkFailure, Page, Run, Site, engine
from app.monitors import MonitorCollector, attach, record_load_time
from app.safety import install_request_guard, validate_url, safe_http_fetch

MAX_PAGES = 25
MAX_DEPTH = 2
MAX_BUDGET_SECONDS = 300  # 5 minutes
ARTIFACTS_DIR = Path("artifacts")


def _normalize_url(raw_url: str) -> str:
    """Strip fragments and trailing query spaces for crawl normalization."""
    url, _ = urldefrag(raw_url)
    return url.strip()


def _is_same_domain(url: str, base_domain: str) -> bool:
    try:
        host = urlparse(url).hostname
        if not host:
            return False
        return host.lower() == base_domain.lower()
    except Exception:
        return False


def attempt_login(page, login_url: str, username: str, password: str, base_domain: str) -> Tuple[bool, Optional[str]]:
    """
    Submits login credentials using sensible heuristics:
    - Finds password input
    - Finds nearest text/email input for username
    - Finds submit button
    - Masks/never logs credentials
    - Does NOT screenshot page after entering credentials
    Detects and reports separately:
    - CAPTCHA elements
    - MFA prompts (one-time code fields)
    - SSO redirects to external domains
    Returns (success, reason_if_expired_or_failed).
    """
    # Navigate to login URL
    try:
        page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        return False, f"Could not load login page: {str(e)}"

    # Check for SSO redirect off-domain
    if not _is_same_domain(page.url, base_domain):
        return False, f"SSO redirect to external domain '{urlparse(page.url).netloc}' detected. Login not automatable."

    # Detect CAPTCHA elements
    captcha_selectors = [
        "iframe[src*='recaptcha']",
        "iframe[src*='hcaptcha']",
        "iframe[src*='turnstile']",
        ".g-recaptcha",
        ".h-captcha",
        "#cf-turnstile",
    ]
    for sel in captcha_selectors:
        try:
            if page.locator(sel).count() > 0:
                return False, "CAPTCHA detected on login page. Login not automatable."
        except Exception:
            pass

    # Find password input
    pwd_locator = page.locator("input[type='password']").first
    if pwd_locator.count() == 0:
        return False, "No password field found on login page."

    # Find username/email input (text/email or nearest previous input)
    user_locator = None
    for user_sel in [
        "input[type='email']",
        "input[name*='user']",
        "input[name*='email']",
        "input[name*='login']",
        "input[type='text']",
    ]:
        loc = page.locator(user_sel).first
        if loc.count() > 0:
            user_locator = loc
            break

    if not user_locator or user_locator.count() == 0:
        return False, "No username/email input found on login page."

    # Fill username and password
    try:
        user_locator.fill(username)
        pwd_locator.fill(password)
    except Exception as e:
        return False, f"Failed filling credentials: {str(e)}"

    # Find submit button
    btn_locator = None
    for btn_sel in [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Log in')",
        "button:has-text('Sign in')",
        "button:has-text('Login')",
        "button",
    ]:
        loc = page.locator(btn_sel).first
        if loc.count() > 0:
            btn_locator = loc
            break

    if not btn_locator:
        return False, "No submit button found on login page."

    # Submit
    try:
        with page.expect_navigation(timeout=15000):
            btn_locator.click()
    except Exception:
        # Fallback if navigation happened without expect_navigation catching it
        page.wait_for_timeout(2000)

    # Check for off-domain SSO redirect after submission
    if not _is_same_domain(page.url, base_domain):
        return False, f"SSO redirect to external domain '{urlparse(page.url).netloc}' detected after submit. Login not automatable."

    # Detect MFA prompts (OTP, Authenticator code, SMS code)
    mfa_selectors = [
        "input[name*='otp']",
        "input[name*='mfa']",
        "input[name*='2fa']",
        "input[name*='code']",
        "input[autocomplete='one-time-code']",
        "text='Two-factor authentication'",
        "text='Verification code'",
    ]
    for sel in mfa_selectors:
        try:
            if page.locator(sel).count() > 0:
                return False, "MFA/Two-factor verification prompt detected. Login not automatable."
        except Exception:
            pass

    # Decide success: URL left login page or password field disappeared
    post_url = page.url
    has_pwd_field = False
    try:
        has_pwd_field = (page.locator("input[type='password']").count() > 0)
    except Exception:
        pass

    if _normalize_url(post_url) != _normalize_url(login_url) or not has_pwd_field:
        return True, None

    return False, "Login submission did not transition away from login form."


def run_public_checks(run_id: int) -> None:
    """
    Step 5 & 6 Checks Engine:
    - Supports Mode B (public crawl) and Mode A (test-credentials login)
    - Mode A: attempts login, detects CAPTCHA/MFA/SSO and marks expired if not automatable
    - Deletes credentials when run ends (try / finally)
    - Never logs credentials, masks passwords, no screenshots with typed credentials
    - Crawls verified site starting at its URL:
        * same domain only
        * max 25 pages, depth 2, 5-minute budget
    - For each page records status, load time, console errors, network failures, screenshot
    - Collects & checks internal links
    - Computes score
    """
    with Session(engine) as session:
        run = session.get(Run, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found.")
        site_id = run.site_id
        site = session.get(Site, site_id) if site_id else None
        if not site:
            raise ValueError(f"Site for run {run_id} not found.")
        start_url = site.url
        base_domain = site.domain
        run_mode = run.mode or "public"

    start_ts = time.time()
    run_artifacts_dir = ARTIFACTS_DIR / str(run_id)
    run_artifacts_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Queue of (url, depth)
        queue: deque = deque([(start_url, 0)])
        visited_urls: Set[str] = set()
        discovered_internal_links: Set[Tuple[str, str]] = set()

        crawled_pages_count = 0
        ok_pages_count = 0

        # Ensure FlowResult exists so foreign key constraints on ConsoleLog/NetworkFailure succeed
        flow_result_id = None
        with Session(engine) as session:
            fr = FlowResultModel(
                run_id=run_id,
                flow_id=None,
                status="passed",
                attempts=1,
                duration_ms=0,
            )
            session.add(fr)
            session.commit()
            session.refresh(fr)
            flow_result_id = fr.id

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            install_request_guard(context)

            try:
                # Mode A: Test-credentials login
                if run_mode == "credentials" and site_id:
                    creds = get_credentials(site_id)
                    if creds:
                        login_url, username, password = creds
                        login_page = context.new_page()
                        try:
                            success, reason = attempt_login(
                                login_page, login_url, username, password, base_domain
                            )
                            if not success:
                                # Mark run as expired with reason
                                with Session(engine) as session:
                                    r = session.get(Run, run_id)
                                    if r:
                                        r.status = "expired"
                                        session.add(r)
                                        session.commit()
                                # Add page record describing failure
                                with Session(engine) as session:
                                    session.add(
                                        Page(
                                            run_id=run_id,
                                            url=login_url,
                                            status_code=401,
                                            load_ms=0,
                                            error=reason or "Login failed",
                                        )
                                    )
                                    session.commit()
                                return
                        finally:
                            login_page.close()

                while queue and (crawled_pages_count < MAX_PAGES):
                    if (time.time() - start_ts) >= MAX_BUDGET_SECONDS:
                        break

                    current_url, depth = queue.popleft()
                    norm_current = _normalize_url(current_url)

                    if norm_current in visited_urls:
                        continue

                    if not _is_same_domain(norm_current, base_domain):
                        continue

                    visited_urls.add(norm_current)
                    crawled_pages_count += 1

                    collector = MonitorCollector()
                    page = context.new_page()
                    attach(page, collector)

                    status_code = 0
                    error_msg = None
                    screenshot_rel_path = None

                    page_start_time = time.time()
                    try:
                        is_safe, reason = validate_url(norm_current)
                        if not is_safe:
                            status_code = 0
                            error_msg = f"Blocked URL: {reason}"
                        else:
                            response = page.goto(norm_current, wait_until="domcontentloaded", timeout=30000)
                            if response:
                                status_code = response.status
                            else:
                                status_code = 200

                            record_load_time(page, collector)
                    except Exception as e:
                        error_msg = str(e)
                        if status_code == 0:
                            status_code = 500

                    page_load_ms = collector.page_load_time_ms
                    if page_load_ms is None or page_load_ms <= 0:
                        page_load_ms = int((time.time() - page_start_time) * 1000)

                    # Extract internal links
                    if status_code < 400 and not error_msg:
                        try:
                            hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
                            for href in hrefs:
                                if not href or href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:") or href.startswith("#"):
                                    continue
                                abs_link = urljoin(norm_current, href)
                                abs_link_clean = _normalize_url(abs_link)
                                if _is_same_domain(abs_link_clean, base_domain):
                                    discovered_internal_links.add((norm_current, abs_link_clean))
                                    if depth < MAX_DEPTH and abs_link_clean not in visited_urls:
                                        queue.append((abs_link_clean, depth + 1))
                        except Exception:
                            pass

                    is_ok = (status_code > 0 and status_code < 400 and not error_msg)
                    if is_ok:
                        ok_pages_count += 1

                    # Screenshots: on HTTP error, exception error, console errors, or first page
                    has_errors = (not is_ok) or (len(collector.console_errors) > 0)
                    try:
                        if has_errors or crawled_pages_count == 1:
                            shot_filename = f"page_{crawled_pages_count}_{int(time.time()*1000)}.png"
                            shot_path = run_artifacts_dir / shot_filename
                            page.screenshot(path=str(shot_path), full_page=False)
                            screenshot_rel_path = f"artifacts/{run_id}/{shot_filename}"
                    except Exception:
                        screenshot_rel_path = None

                    page.close()

                    with Session(engine) as session:
                        db_page = Page(
                            run_id=run_id,
                            url=norm_current,
                            status_code=status_code,
                            load_ms=page_load_ms,
                            screenshot_path=screenshot_rel_path,
                            error=error_msg,
                        )
                        session.add(db_page)

                        for c_err in collector.console_errors:
                            session.add(
                                ConsoleLog(
                                    flow_result_id=flow_result_id,
                                    level="error",
                                    message=c_err.message,
                                    page_url=c_err.page_url or norm_current,
                                    timestamp=c_err.timestamp,
                                )
                            )

                        for n_fail in collector.network_failures:
                            session.add(
                                NetworkFailure(
                                    flow_result_id=flow_result_id,
                                    url=n_fail.url,
                                    method=n_fail.method,
                                    status_code=n_fail.status_code,
                                    page_url=n_fail.page_url or norm_current,
                                    timestamp=n_fail.timestamp,
                                )
                            )
                        session.commit()

            finally:
                context.close()
                browser.close()

        # Link check verification
        link_results = []
        headers = {"User-Agent": "AutoQA-PublicChecks/2.0"}
        for source_url, target_url in list(discovered_internal_links)[:50]:
            if (time.time() - start_ts) >= MAX_BUDGET_SECONDS:
                break
            try:
                safe, _ = validate_url(target_url)
                if not safe:
                    link_results.append({
                        "run_id": run_id,
                        "source_url": source_url,
                        "target_url": target_url,
                        "status_code": 0,
                        "ok": False,
                    })
                    continue

                status, _, _ = safe_http_fetch(target_url, headers=headers, timeout=5, max_redirects=5, max_bytes=100*1024)
                link_results.append({
                    "run_id": run_id,
                    "source_url": source_url,
                    "target_url": target_url,
                    "status_code": status,
                    "ok": (status < 400),
                })
            except Exception:
                link_results.append({
                    "run_id": run_id,
                    "source_url": source_url,
                    "target_url": target_url,
                    "status_code": 0,
                    "ok": False,
                })

        if link_results:
            with Session(engine) as session:
                for lr in link_results:
                    session.add(
                        LinkCheck(
                            run_id=lr["run_id"],
                            source_url=lr["source_url"],
                            target_url=lr["target_url"],
                            status_code=lr["status_code"],
                            ok=lr["ok"],
                        )
                    )
                session.commit()

        score = 100
        if crawled_pages_count > 0:
            score = int((ok_pages_count / crawled_pages_count) * 100)

        with Session(engine) as session:
            run = session.get(Run, run_id)
            if run:
                run.score = score
                session.add(run)
                session.commit()

    finally:
        # Mandatory cleanup: delete credentials immediately when run ends
        if site_id:
            delete_credentials(site_id)
