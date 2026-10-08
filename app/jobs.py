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

# Limits from PLAN2.md
MAX_RUNS_PER_USER_PER_DAY = 5
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


def check_concurrency_limits(session: Session, user_id: int) -> Tuple[bool, str]:
    # Global running / queued runs
    active_statuses = ["queued", "running"]
    global_active = session.exec(
        select(Run).where(Run.status.in_(active_statuses))
    ).all()
    if len(global_active) >= MAX_CONCURRENT_RUNS_GLOBAL:
        return False, "Platform is currently busy (global limit reached). Please try again shortly."

    # User active runs
    user_active = session.exec(
        select(Run).where(Run.user_id == user_id, Run.status.in_(active_statuses))
    ).all()
    if len(user_active) >= MAX_CONCURRENT_RUNS_PER_USER:
        return False, f"You already have a test currently running or queued."

    return True, ""


def enqueue_run(user_id: int, site_id: int, mode: str = "public") -> Tuple[Optional[Run], Optional[str]]:
    """
    Enforces PLAN2 limits:
    - Site exists and is verified
    - URL safety passes
    - 5 runs/day/user
    - 1 concurrent run/user
    - 3 concurrent runs globally
    Creates run in 'queued' status and dispatches to RQ worker.
    """
    with Session(engine) as session:
        site = session.get(Site, site_id)
        if not site:
            return None, "Site not found."
        if site.user_id != user_id:
            return None, "Unauthorized access to site."
        if not site.verified_at and os.getenv("SKIP_OWNERSHIP_FOR_DEV", "0") != "1":
            return None, "Site ownership must be verified before running tests."

        safe, reason = validate_url(site.url)
        if not safe:
            return None, f"Site URL is not safe to test: {reason}"

        # Check concurrency
        allowed, msg = check_concurrency_limits(session, user_id)
        if not allowed:
            return None, msg

        # Check daily quota
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

    # Enqueue to Redis RQ worker if Redis is reachable, else keep queued in DB
    try:
        q = get_queue()
        q.enqueue("app.worker.run_job_entry", run_id, job_timeout=300)
    except Exception:
        # If Redis isn't running in local dev/testing, worker or test can invoke worker directly
        pass

    return run, None
