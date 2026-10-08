import os
import secrets
from typing import Optional
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from email_validator import validate_email, EmailNotValidError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlmodel import Session, select
from app.models import User, engine

ph = PasswordHasher()
SECRET_KEY = os.getenv("SECRET_KEY", "autoqa-insecure-secret-key-change-in-prod")
serializer = URLSafeTimedSerializer(SECRET_KEY, salt="autoqa-session")
csrf_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="autoqa-csrf")

SESSION_COOKIE_NAME = "autoqa_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, Exception):
        return False


def create_session_token(user_id: int) -> str:
    return serializer.dumps({"user_id": user_id})


def verify_session_token(token: str) -> Optional[int]:
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None


def generate_csrf_token(session_id: str) -> str:
    return csrf_serializer.dumps({"sid": session_id})


def verify_csrf_token(token: str, session_id: str) -> bool:
    try:
        data = csrf_serializer.loads(token, max_age=3600 * 24)
        return data.get("sid") == session_id
    except (BadSignature, SignatureExpired):
        return False


def get_current_user_from_token(token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    user_id = verify_session_token(token)
    if not user_id:
        return None
    with Session(engine) as session:
        return session.get(User, user_id)


def delete_user_account(user_id: int) -> bool:
    """
    Permanently deletes user account and all associated data:
    - Sites, verification records, credentials
    - Runs, pages, link checks, flow results, steps, console logs, network failures
    - Artifact directories and screenshots
    - Usage records
    - User record
    """
    import shutil
    from pathlib import Path
    from app.models import Site, SiteCredential, Run, Page, LinkCheck, FlowResultModel, StepResultModel, ConsoleLog, NetworkFailure, Usage

    artifacts_base = Path("artifacts")

    with Session(engine) as session:
        user = session.get(User, user_id)
        if not user:
            return False

        # Get all sites for user
        user_sites = session.exec(select(Site).where(Site.user_id == user_id)).all()
        site_ids = [s.id for s in user_sites]

        # Delete site credentials
        if site_ids:
            creds = session.exec(select(SiteCredential).where(SiteCredential.site_id.in_(site_ids))).all()
            for c in creds:
                session.delete(c)

        # Get all runs for user
        user_runs = session.exec(select(Run).where(Run.user_id == user_id)).all()
        run_ids = [r.id for r in user_runs]

        if run_ids:
            # Delete pages
            pages = session.exec(select(Page).where(Page.run_id.in_(run_ids))).all()
            for p in pages:
                session.delete(p)

            # Delete link checks
            link_checks = session.exec(select(LinkCheck).where(LinkCheck.run_id.in_(run_ids))).all()
            for lc in link_checks:
                session.delete(lc)

            # Delete flow results and children
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

            # Delete artifacts folders on disk for each run
            for rid in run_ids:
                run_folder = artifacts_base / str(rid)
                if run_folder.is_dir():
                    shutil.rmtree(run_folder, ignore_errors=True)

            # Delete runs
            for r in user_runs:
                session.delete(r)

        # Delete sites
        for s in user_sites:
            session.delete(s)

        # Delete usages
        usages = session.exec(select(Usage).where(Usage.user_id == user_id)).all()
        for u in usages:
            session.delete(u)

        # Delete user
        session.delete(user)
        session.commit()
        return True


def normalize_and_validate_email(email: str) -> str:
    valid = validate_email(email, check_deliverability=False)
    return valid.normalized.lower()


