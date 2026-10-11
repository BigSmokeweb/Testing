"""
app/admin.py — Admin override helpers for AutoQA.

Admin status is determined at request time by comparing the logged-in user's
email against the ADMIN_EMAILS environment variable (comma-separated, case-
insensitive). No is_admin column is stored in the database.

Hard rules that admins CANNOT bypass (enforced elsewhere):
  - SSRF protection (validate_url, request guard, redirect re-validation, size caps)
  - Authentication, CSRF, cookie security, session version checks
  - Other users' data (ownership checks unchanged)
  - Global concurrent browser cap (MAX_CONCURRENT_RUNS_GLOBAL)

Limits admins CAN bypass:
  - Domain ownership verification
  - Daily run quota
  - Quick-check quota (per-user and per-domain)
  - Per-user concurrent run limit

All bypasses are logged to security.log via log_security_event (called by the
caller — this module does not import main.py to avoid circular imports).
"""

import logging
import os

logger = logging.getLogger("autoqa_admin")

# Higher limits for admin runs — configurable via env.
_DEFAULT_ADMIN_MAX_PAGES = 100
_DEFAULT_ADMIN_TIMEOUT_SECONDS = 900  # 15 minutes


def _get_admin_emails() -> set:
    """Return the set of lowercase admin emails from ADMIN_EMAILS env var."""
    raw = os.getenv("ADMIN_EMAILS", "").strip()
    if not raw:
        return set()
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_admin(email: str) -> bool:
    """
    Return True if *email* (case-insensitive) is in ADMIN_EMAILS.
    Re-reads the env var on every call so tests can patch os.environ without
    reloading the module.
    Empty or unset ADMIN_EMAILS means no admins.
    """
    if not email:
        return False
    return email.strip().lower() in _get_admin_emails()


def mask_email(email: str) -> str:
    """
    Mask an email address for log output: first 2 chars visible, rest of
    local part replaced with '***', then '@domain'.
    e.g. 'admin@example.com' -> 'ad***@example.com'
    """
    if not email or "@" not in email:
        return "***"
    local, domain = email.rsplit("@", 1)
    visible = local[:2] if len(local) >= 2 else local[:1]
    return f"{visible}***@{domain}"


def get_admin_max_pages() -> int:
    """
    Return the page cap for admin runs (env ADMIN_MAX_PAGES, default 100).
    Non-numeric, zero, or negative values fall back to default (100).
    Hard upper cap: 500 pages.
    """
    raw = os.getenv("ADMIN_MAX_PAGES", str(_DEFAULT_ADMIN_MAX_PAGES))
    try:
        val = int(raw)
        if val <= 0:
            return _DEFAULT_ADMIN_MAX_PAGES
        return min(val, 500)
    except (ValueError, TypeError):
        return _DEFAULT_ADMIN_MAX_PAGES


def get_admin_timeout_seconds() -> int:
    """
    Return the run timeout for admin runs in seconds (env ADMIN_RUN_TIMEOUT_SECONDS, default 900).
    Non-numeric, zero, or negative values fall back to default (900 seconds = 15 min).
    Hard upper cap: 1800 seconds (30 minutes).
    """
    raw = os.getenv("ADMIN_RUN_TIMEOUT_SECONDS", str(_DEFAULT_ADMIN_TIMEOUT_SECONDS))
    try:
        val = int(raw)
        if val <= 0:
            return _DEFAULT_ADMIN_TIMEOUT_SECONDS
        return min(val, 1800)
    except (ValueError, TypeError):
        return _DEFAULT_ADMIN_TIMEOUT_SECONDS


def warn_unregistered_admin_emails() -> None:
    """
    Called at application startup.  For each email in ADMIN_EMAILS that has no
    registered User row, emit a WARNING to the admin logger.  The email is
    masked in the log output.
    """
    admin_emails = _get_admin_emails()
    if not admin_emails:
        return

    # Import here to avoid circular import at module load time.
    from app.models import User, engine
    from sqlmodel import Session, select

    with Session(engine) as session:
        for email in admin_emails:
            existing = session.exec(
                select(User).where(User.email == email)
            ).first()
            if not existing:
                logger.warning(
                    "Admin email %s is not registered yet. "
                    "Register it first before setting ADMIN_EMAILS.",
                    mask_email(email),
                )
