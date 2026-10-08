import secrets
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, Tuple
import dns.resolver
import requests
from sqlmodel import Session, select
from app.models import Site, engine
from app.safety import validate_url

MAX_SITES_PER_USER = 2


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
    except Exception:
        pass
    return False


def check_well_known_file(url: str, token: str) -> bool:
    """
    Checks if <url>/.well-known/autoqa-<token>.txt returns the token.
    Uses 5s timeout and avoids redirects to other domains.
    """
    file_url = f"{url.rstrip('/')}/.well-known/autoqa-{token}.txt"
    try:
        resp = requests.get(file_url, timeout=5, allow_redirects=False)
        if resp.status_code == 200:
            if resp.text.strip() == token:
                return True
    except Exception:
        pass
    return False


def verify_site_ownership(site: Site) -> bool:
    import os
    if os.getenv("SKIP_OWNERSHIP_FOR_DEV", "0") == "1":
        return True
    # 1. DNS TXT check
    if check_dns_txt_record(site.domain, site.verify_token):
        return True
    # 2. Well-known file check
    if check_well_known_file(site.url, site.verify_token):
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

        existing = session.exec(
            select(Site).where(Site.user_id == user_id, Site.domain == domain)
        ).first()
        if existing:
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
    with Session(engine) as session:
        return session.exec(
            select(Site).where(Site.user_id == user_id).order_by(Site.id.desc())
        ).all()
