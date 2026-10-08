import os
import sys
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger("autoqa_worker")
import redis
from rq import Worker, Queue
from sqlmodel import Session, select
from app.models import Run, engine
from app.public_checks import run_public_checks

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = "autoqa_runs"


def run_job_entry(run_id: int):
    """
    RQ worker entrypoint:
    - Sets run status to 'running'
    - Executes public checks crawler
    - Enforces 5-minute timeout budget
    - Updates status to 'completed' or 'failed'
    """
    with Session(engine) as session:
        run = session.get(Run, run_id)
        if not run:
            logger.warning(f"Run {run_id} not found in database; skipping.")
            return
        if run.status != "queued":
            logger.info(f"Run {run_id} status is '{run.status}' (expected 'queued'); skipping execution.")
            return
        run.status = "running"
        session.add(run)
        session.commit()

    start_time = time.time()
    try:
        run_public_checks(run_id)
        status = "completed"
        err = None
    except Exception as e:
        status = "failed"
        err = str(e)
        logger.error(f"Run {run_id} failed with error: {e}", exc_info=True)

    duration_ms = int((time.time() - start_time) * 1000)
    finished_str = datetime.now(timezone.utc).isoformat()

    with Session(engine) as session:
        run = session.get(Run, run_id)
        if run:
            if run.status not in ("expired", "blocked"):
                run.status = status
                if err and status == "failed":
                    # Store failure reason (truncated, no secrets)
                    run.note = str(err)[:500]
            run.finished_at = finished_str
            run.duration_ms = duration_ms
            session.add(run)
            session.commit()



def reap_stuck_runs(timeout_minutes: int = 10, queued_timeout_minutes: int = 15) -> int:
    """
    Reaps:
    - Runs stuck in 'running' for more than timeout_minutes (10 min).
    - Runs stuck in 'queued' for more than queued_timeout_minutes (15 min).
    Marks them as 'failed' with finished_at timestamp.
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
    cutoff_iso = cutoff.isoformat()
    queued_cutoff = datetime.now(timezone.utc) - timedelta(minutes=queued_timeout_minutes)
    queued_cutoff_iso = queued_cutoff.isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    reaped = 0

    with Session(engine) as session:
        # 1. Stuck running runs
        stuck_runs = session.exec(
            select(Run).where(Run.status == "running", Run.started_at < cutoff_iso)
        ).all()
        for r in stuck_runs:
            r.status = "failed"
            r.finished_at = now_iso
            r.note = "Worker died or timed out (no response for >10 minutes)"
            session.add(r)
            reaped += 1

        # 2. Stuck queued runs (e.g. Redis crash or worker failure to pick up)
        from sqlalchemy import or_
        stuck_queued = session.exec(
            select(Run).where(
                Run.status == "queued",
                or_(
                    Run.queued_at < queued_cutoff_iso,
                    (Run.queued_at == None) & (Run.started_at < queued_cutoff_iso),
                )
            )
        ).all()
        for r in stuck_queued:
            r.status = "failed"
            r.finished_at = now_iso
            r.note = "Job was never picked up"
            session.add(r)
            reaped += 1

        if reaped:
            session.commit()
    return reaped


def run_retention_cleanup(retention_days: int = 30) -> int:
    """
    Retention cleanup job:
    - Reaps stuck runs
    - Deletes expired credentials
    - Deletes runs and associated pages, links, and disk artifacts older than retention_days (or RETENTION_DAYS env)
    """
    reap_stuck_runs(timeout_minutes=10)
    import shutil
    from pathlib import Path
    from datetime import timedelta
    from sqlmodel import select
    from app.creds import cleanup_expired_credentials
    from app.models import Page, LinkCheck, FlowResultModel, StepResultModel, ConsoleLog, NetworkFailure

    # 1. Clean expired credentials
    cleanup_expired_credentials()

    # Check env override
    env_days = os.getenv("RETENTION_DAYS")
    if env_days:
        try:
            retention_days = int(env_days)
        except ValueError:
            pass

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_iso = cutoff_dt.isoformat()
    artifacts_base = Path("artifacts")
    deleted_runs_count = 0

    with Session(engine) as session:
        # Find runs older than cutoff (started_at < cutoff_iso)
        old_runs = session.exec(select(Run).where(Run.started_at < cutoff_iso)).all()
        run_ids = [r.id for r in old_runs]

        if run_ids:
            pages = session.exec(select(Page).where(Page.run_id.in_(run_ids))).all()
            for p in pages:
                session.delete(p)

            link_checks = session.exec(select(LinkCheck).where(LinkCheck.run_id.in_(run_ids))).all()
            for lc in link_checks:
                session.delete(lc)

            flow_results = session.exec(select(FlowResultModel).where(FlowResultModel.run_id.in_(run_ids))).all()
            fr_ids = [fr.id for fr in flow_results]
            if fr_ids:
                steps = session.exec(select(StepResultModel).where(StepResultModel.flow_result_id.in_(fr_ids))).all()
                for s in steps:
                    session.delete(s)
                logs = session.exec(select(ConsoleLog).where(ConsoleLog.flow_result_id.in_(fr_ids))).all()
                for l in logs:
                    session.delete(l)
                net_fails = session.exec(select(NetworkFailure).where(NetworkFailure.flow_result_id.in_(fr_ids))).all()
                for nf in net_fails:
                    session.delete(nf)
                for fr in flow_results:
                    session.delete(fr)

            for rid in run_ids:
                run_folder = artifacts_base / str(rid)
                if run_folder.is_dir():
                    shutil.rmtree(run_folder, ignore_errors=True)

            for r in old_runs:
                session.delete(r)

            deleted_runs_count = len(old_runs)
            session.commit()

    return deleted_runs_count


def start_worker():
    from app.creds import cleanup_expired_credentials
    # 1. Purge expired credentials on worker start
    cleanup_expired_credentials()
    # 2. Reap any stuck runs from prior crashes
    reap_stuck_runs(timeout_minutes=10)

    conn = redis.from_url(REDIS_URL)
    q = Queue(QUEUE_NAME, connection=conn)
    worker = Worker([q], connection=conn)
    print(f"[*] AutoQA RQ Worker listening on queue '{QUEUE_NAME}'...")
    worker.work()


if __name__ == "__main__":
    start_worker()

