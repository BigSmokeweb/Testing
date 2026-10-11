import secrets
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, Tuple
import dns.resolver
import requests
from sqlmodel import Session, select
from app.models import Site, engine
from app.safety import validate_url

import os

MAX_SITES_PER_USER = int(os.getenv("MAX_SITES_PER_USER", "50"))


def normalize_site_url(raw_url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Normalizes a given URL to scheme + domain (e.g., https://example.com).
    Returns (normalized_url, domain, error_message).
    """
    raw = raw_url.strip()
    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = "https://" + raw

    parsed = urllib.parse.urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return None, None, "Invalid URL format."

    domain = parsed.netloc.split(":")[0].lower()
    if "." not in domain or domain.endswith("."):
        return None, None, "Invalid domain name."

    norm_url = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    return norm_url, domain, None


def generate_verify_token() -> str:
    return secrets.token_hex(16)


import logging
logger = logging.getLogger("autoqa_sites")

MAX_VERIFY_FILE_BYTES = 100 * 1024  # 100 KB cap


def check_dns_txt_record(domain: str, token: str) -> bool:
    """
    Checks if _autoqa.<domain> has a TXT record with value 'autoqa-verify=<token>'.
    """
    record_name = f"_autoqa.{domain}"
    expected = f"autoqa-verify={token}"
    try:
        answers = dns.resolver.resolve(record_name, "TXT", lifetime=5)
        for rdata in answers:
            for txt_string in rdata.strings:
                if txt_string.decode("utf-8").strip() == expected:
                    return True
    except Exception as e:
        logger.warning(f"DNS TXT resolution failed for {record_name}: {e}")
    return False


def check_well_known_file(url: str, token: str) -> bool:
    """
    Checks if <url>/.well-known/autoqa-<token>.txt returns the token.
    Uses safe_http_fetch (5s timeout, stream=True, caps size to 100KB, validates IPs).
    """
    file_url = f"{url.rstrip('/')}/.well-known/autoqa-{token}.txt"
    try:
        from app.safety import safe_http_fetch
        status_code, content, _ = safe_http_fetch(
            file_url,
            timeout=5,
            max_redirects=0,
            max_bytes=MAX_VERIFY_FILE_BYTES,
        )
        if status_code == 200 and content.decode("utf-8", errors="ignore").strip() == token:
            return True
    except Exception as e:
        logger.warning(f"Well-known verification fetch failed for {file_url}: {e}")
    return False


from html.parser import HTMLParser


DISALLOWED_SHARED_PUBLIC_SUFFIXES = {
    "vercel.app",
    "github.io",
    "netlify.app",
    "herokuapp.com",
    "azurewebsites.net",
    "pages.dev",
    "gitlab.io",
    "firebaseapp.com",
    "web.app",
}


class MetaTagVerifyParser(HTMLParser):
    def __init__(self, expected_token: str):
        super().__init__()
        self.expected_token = expected_token
        self.found = False
        self.in_head = False

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower == "head":
            self.in_head = True
        elif tag_lower == "meta" and self.in_head:
            attr_dict = {k.lower(): v for k, v in attrs if k}
            name_val = attr_dict.get("name", "").strip().lower()
            content_val = attr_dict.get("content", "").strip()
            if name_val == "autoqa-verify" and content_val == self.expected_token:
                self.found = True

    def handle_endtag(self, tag):
        if tag.lower() == "head":
            self.in_head = False


def check_html_meta_tag(url: str, token: str) -> bool:
    """
    Checks if <url> has <meta name="autoqa-verify" content="<token>"> inside <head>.
    Uses safe_http_fetch with SSRF guards and 100 KB limit.
    """
    try:
        from app.safety import safe_http_fetch
        status_code, content, _ = safe_http_fetch(
            url,
            timeout=5,
            max_redirects=2,
            max_bytes=MAX_VERIFY_FILE_BYTES,
        )
        if status_code != 200:
            return False

        html_text = content.decode("utf-8", errors="ignore")
        # Extract <head> section only to avoid parsing huge body
        head_end = html_text.lower().find("</head>")
        if head_end != -1:
            head_snippet = html_text[:head_end + 7]
        else:
            head_snippet = html_text[:20000]

        parser = MetaTagVerifyParser(token)
        parser.feed(head_snippet)
        return parser.found
    except Exception as e:
        logger.warning(f"Meta tag verification failed for {url}: {e}")
        return False


def verify_site_ownership(site: Site) -> bool:
    import os
    # Refuse to verify root shared public suffixes directly (e.g. vercel.app itself)
    domain_clean = site.domain.lower().strip()
    if domain_clean in DISALLOWED_SHARED_PUBLIC_SUFFIXES:
        logger.warning(f"Refusing to verify shared public suffix domain: {domain_clean}")
        return False

    # SKIP_OWNERSHIP_FOR_DEV is honored ONLY when LOCAL_MODE=1, strictly ignored in production
    if os.getenv("LOCAL_MODE", "0") == "1" and os.getenv("SKIP_OWNERSHIP_FOR_DEV", "0") == "1":
        return True

    # 1. HTML Meta Tag check (easiest, checked first)
    if check_html_meta_tag(site.url, site.verify_token):
        return True
    # 2. Well-known file check
    if check_well_known_file(site.url, site.verify_token):
        return True
    # 3. DNS TXT check
    if check_dns_txt_record(site.domain, site.verify_token):
        return True
    return False


def add_site_for_user(user_id: int, raw_url: str) -> Tuple[Optional[Site], Optional[str]]:
    norm_url, domain, err = normalize_site_url(raw_url)
    if err:
        return None, err

    safe, reason = validate_url(norm_url)
    if not safe:
        return None, f"Invalid or unsafe URL: {reason}"

    with Session(engine) as session:
        count = session.exec(select(Site).where(Site.user_id == user_id)).all()
        if len(count) >= MAX_SITES_PER_USER:
            return None, f"Maximum limit of {MAX_SITES_PER_USER} sites reached."

        # If domain already added, allow adding or re-using
        existing = session.exec(
            select(Site).where(Site.user_id == user_id, Site.domain == domain)
        ).first()
        if existing and os.getenv("ALLOW_DUPLICATE_DOMAINS", "1") != "1":
            return None, "You have already added this domain."

        site = Site(
            user_id=user_id,
            url=norm_url,
            domain=domain,
            verify_token=generate_verify_token(),
        )
        session.add(site)
        session.commit()
        session.refresh(site)
        return site, None


def get_user_sites(user_id: int) -> list[Site]:
    """Return one site per domain (the most recently added), ordered newest first."""
    with Session(engine) as session:
        all_sites = session.exec(
            select(Site).where(Site.user_id == user_id).order_by(Site.id.desc())
        ).all()

    # Deduplicate: first-seen per domain wins because we iterate newest→oldest
    seen: set[str] = set()
    unique: list[Site] = []
    for site in all_sites:
        if site.domain not in seen:
            seen.add(site.domain)
            unique.append(site)
    return unique
