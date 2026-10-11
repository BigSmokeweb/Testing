import os
from datetime import datetime, timezone
from typing import Optional, Tuple
import redis
from rq import Queue
from sqlmodel import Session, select
from app.models import Run, Site, Usage, engine
from app.safety import validate_url

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = "autoqa_runs"

# Limits from PLAN2.md (set to 50 for local dev / testing; change to 5 for production deployment)
MAX_RUNS_PER_USER_PER_DAY = int(os.getenv("MAX_RUNS_PER_USER_PER_DAY", "50"))
MAX_CONCURRENT_RUNS_PER_USER = 1
MAX_CONCURRENT_RUNS_GLOBAL = 3


def get_redis_connection():
    return redis.from_url(REDIS_URL)


def get_queue():
    conn = get_redis_connection()
    return Queue(QUEUE_NAME, connection=conn)


def check_and_increment_daily_usage(session: Session, user_id: int) -> Tuple[bool, str]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage = session.exec(
        select(Usage).where(Usage.user_id == user_id, Usage.date == today)
    ).first()

    if not usage:
        usage = Usage(user_id=user_id, date=today, runs_count=0)
        session.add(usage)
        session.commit()
        session.refresh(usage)

    if usage.runs_count >= MAX_RUNS_PER_USER_PER_DAY:
        return False, f"Daily limit of {MAX_RUNS_PER_USER_PER_DAY} runs reached for today."

    usage.runs_count += 1
    session.add(usage)
    session.commit()
    return True, ""


def check_concurrency_limits(session: Session, user_id: int, mode: str = "public") -> Tuple[bool, str]:
    """
    Checks concurrency limits.
    Quick checks (mode='quick') are single-page instant fetches, so they
    bypass the global platform limit but still respect the per-user 1-run limit.
    """
    active_statuses = ["queued", "running"]

    # Global limit only applies to full crawl / credentials runs
    if mode != "quick":
        global_active = session.exec(
            select(Run).where(Run.status.in_(active_statuses))
        ).all()
        if len(global_active) >= MAX_CONCURRENT_RUNS_GLOBAL:
            return False, "Platform is currently busy (global limit reached). Please try again shortly."

    # Per-user 1-run limit always applies (including quick checks)
    user_active = session.exec(
        select(Run).where(Run.user_id == user_id, Run.status.in_(active_statuses))
    ).all()
    if len(user_active) >= MAX_CONCURRENT_RUNS_PER_USER:
        return False, "You already have a test currently running or queued."

    return True, ""


MAX_QUICK_CHECKS_PER_USER_PER_DAY = 3
MAX_QUICK_CHECKS_PER_DOMAIN_PER_DAY = 10


def check_quick_check_limits(session: Session, user_id: int, site: Site) -> Tuple[bool, str]:
    """
    Counts existing runs from DB queued today in UTC with mode='quick'.
    No schema change or extra table columns required.
    """
    today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. User daily quick check limit (max 3/day)
    user_quick_runs = session.exec(
        select(Run).where(
            Run.user_id == user_id,
            Run.mode == "quick",
            Run.queued_at.startswith(today_prefix),
        )
    ).all()
    if len(user_quick_runs) >= MAX_QUICK_CHECKS_PER_USER_PER_DAY:
        return False, f"Daily limit of {MAX_QUICK_CHECKS_PER_USER_PER_DAY} quick checks reached for today. Verify domain to unlock full tests."

    # 2. Per-target-domain cap across all users (max 10/day)
    domain_quick_runs = session.exec(
        select(Run).where(
            Run.mode == "quick",
            Run.queued_at.startswith(today_prefix),
        )
    ).all()
    # Filter by domain matching the target site's domain
    domain_count = 0
    for r in domain_quick_runs:
        s = session.get(Site, r.site_id) if r.site_id else None
        if s and s.domain == site.domain:
            domain_count += 1
    if domain_count >= MAX_QUICK_CHECKS_PER_DOMAIN_PER_DAY:
        return False, f"Daily quick-check limit of {MAX_QUICK_CHECKS_PER_DOMAIN_PER_DAY} reached for {site.domain} across all users. Please verify domain or try tomorrow."

    return True, ""


def enqueue_run(user_id: int, site_id: int, mode: str = "public") -> Tuple[Optional[Run], Optional[str]]:
    """
    Enforces quality limits:
    - If mode == 'quick':
      - Site may be unverified (SSRF checks still strictly enforced).
      - Max 3 quick checks per user per day.
      - Max 10 quick checks per domain per day across all users.
      - 1 concurrent run per user.
    - If mode in ('public', 'credentials'):
      - Site MUST be verified.
      - Standard daily quota (Usage table).
    """
    with Session(engine) as session:
        site = session.get(Site, site_id)
        if not site:
            return None, "Site not found."
        if site.user_id != user_id:
            return None, "Unauthorized access to site."

        is_dev_skip = os.getenv("LOCAL_MODE", "0") == "1" and os.getenv("SKIP_OWNERSHIP_FOR_DEV", "0") == "1"

        if mode != "quick":
            if not site.verified_at and not is_dev_skip:
                return None, "Site ownership must be verified before running full crawl or authenticated tests."
            if mode == "credentials" and not site.verified_at and not is_dev_skip:
                return None, "Site must be verified to run authenticated credentials tests."

        safe, reason = validate_url(site.url)
        if not safe:
            return None, f"Site URL is not safe to test: {reason}"

        # Concurrency check (quick checks bypass global limit; all check per-user limit)
        allowed, msg = check_concurrency_limits(session, user_id, mode=mode)
        if not allowed:
            return None, msg

        if mode == "quick":
            allowed, msg = check_quick_check_limits(session, user_id, site)
            if not allowed:
                return None, msg
        else:
            allowed, msg = check_and_increment_daily_usage(session, user_id)
            if not allowed:
                return None, msg

        now_str = datetime.now(timezone.utc).isoformat()
        run = Run(
            user_id=user_id,
            site_id=site_id,
            mode=mode,
            engine="chromium",
            status="queued",
            started_at=now_str,
            finished_at="",
            duration_ms=0,
            session_valid=True,
            queued_at=now_str,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    try:
        q = get_queue()
        q.enqueue("app.worker.run_job_entry", run_id, job_timeout=300)
    except Exception:
        pass

    return run, None
