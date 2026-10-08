import json
from pathlib import Path
from typing import List, Dict
from urllib.parse import urlparse, urljoin

import requests
from playwright.sync_api import sync_playwright

from app.config import load_config

AUTH_STATE_PATH = Path("auth/state.json")


def _get_session_cookies() -> Dict[str, str]:
    """Extract cookies from auth/state.json as a plain dict for use with requests."""
    if not AUTH_STATE_PATH.is_file():
        return {}
    with open(AUTH_STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)
    return {c["name"]: c["value"] for c in state.get("cookies", [])}


def _is_internal(href: str, allowed_domains: List[str]) -> bool:
    """Return True if href belongs to one of the allowed_domains."""
    if not href or href.startswith("#") or href.startswith("javascript:"):
        return False
    if href.startswith("/"):
        return True
    allowed_set = {d.lower() for d in allowed_domains}
    try:
        hostname = (urlparse(href).hostname or "").lower()
        return any(hostname == d or hostname.endswith("." + d) for d in allowed_set)
    except Exception:
        return False


def collect_internal_links(start_url: str, allowed_domains: List[str]) -> List[tuple]:
    """Open start_url with Playwright (using saved session) and collect all

    unique internal anchor hrefs. Returns list of (source_url, target_url).
    """
    base_parsed = urlparse(start_url)
    base_root = f"{base_parsed.scheme}://{base_parsed.netloc}"
    links = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx_kwargs = {}
        if AUTH_STATE_PATH.is_file():
            ctx_kwargs["storage_state"] = str(AUTH_STATE_PATH)
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded")

        # Collect all hrefs via JS — never click anything
        raw_hrefs = page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.getAttribute('href'))"
        )
        browser.close()

    seen = set()
    for href in raw_hrefs:
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        # Resolve relative URLs against base
        if href.startswith("//"):
            href = base_parsed.scheme + ":" + href
        elif href.startswith("/"):
            href = base_root + href
        elif not href.startswith("http"):
            href = urljoin(start_url, href)

        if _is_internal(href, allowed_domains) and href not in seen:
            seen.add(href)
            links.append((start_url, href))

    return links


def check_links(run_id: int) -> List[dict]:
    """Collect internal links from link_check_pages and HTTP-check each one.

    Uses saved session cookies so authenticated pages are checked correctly.
    Returns a list of result dicts ready for the database.
    """
    config = load_config()
    pages = config.link_check_pages
    if not pages:
        return []

    cookies = _get_session_cookies()
    headers = {"User-Agent": "AutoQA-LinkChecker/1.0"}
    results = []

    for page_path in pages:
        start_url = (
            page_path
            if page_path.startswith("http")
            else config.base_url.rstrip("/") + "/" + page_path.lstrip("/")
        )
        collected = collect_internal_links(start_url, config.allowed_domains)

        for source_url, target_url in collected:
            try:
                from app.safety import safe_http_fetch
                status_code, _, _ = safe_http_fetch(
                    target_url,
                    cookies=cookies,
                    headers=headers,
                    timeout=10,
                    max_redirects=5,
                    max_bytes=100 * 1024,
                )
                ok = status_code < 400
            except Exception:
                status_code = 0
                ok = False

            results.append(
                {
                    "run_id": run_id,
                    "source_url": source_url,
                    "target_url": target_url,
                    "status_code": status_code,
                    "ok": ok,
                }
            )

    return results
