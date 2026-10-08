import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from cryptography.fernet import Fernet
from sqlmodel import Session, select
from app.models import SiteCredential, engine

def get_fernet() -> Fernet:
    key = os.getenv("FERNET_KEY")
    if not key:
        if os.getenv("LOCAL_MODE", "0") == "1":
            # Temporary in-memory key for local test/dev mode only
            key = "ffHyO8bP0IdwkhA2f5XVHH-wWigpQ5q1ObMPbqUh-TA="
        else:
            raise RuntimeError("FERNET_KEY environment variable is required in production.")
    if isinstance(key, str):
        key_bytes = key.encode("utf-8")
    else:
        key_bytes = key
    return Fernet(key_bytes)



def encrypt_value(value: str) -> str:
    f = get_fernet()
    return f.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(token: str) -> str:
    f = get_fernet()
    return f.decrypt(token.encode("utf-8")).decode("utf-8")


def store_credentials(
    site_id: int, login_url: str, username: str, password: str, expires_in_hours: int = 1
) -> SiteCredential:
    """Stores encrypted username & password with 1 hour expiration."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=expires_in_hours)

    username_enc = encrypt_value(username)
    password_enc = encrypt_value(password)

    with Session(engine) as session:
        # Delete any existing credentials for this site
        existing = session.exec(
            select(SiteCredential).where(SiteCredential.site_id == site_id)
        ).all()
        for e in existing:
            session.delete(e)

        cred = SiteCredential(
            site_id=site_id,
            login_url=login_url,
            username_enc=username_enc,
            password_enc=password_enc,
            created_at=now,
            expires_at=expires_at,
        )
        session.add(cred)
        session.commit()
        session.refresh(cred)
        return cred


def get_credentials(site_id: int) -> Optional[Tuple[str, str, str]]:
    """
    Returns (login_url, decrypted_username, decrypted_password)
    or None if expired or non-existent.
    """
    with Session(engine) as session:
        cred = session.exec(
            select(SiteCredential).where(SiteCredential.site_id == site_id)
        ).first()
        if not cred:
            return None
        now = datetime.now(timezone.utc)
        if cred.expires_at < now:
            session.delete(cred)
            session.commit()
            return None

        username = decrypt_value(cred.username_enc)
        password = decrypt_value(cred.password_enc)
        return cred.login_url, username, password


def delete_credentials(site_id: int) -> None:
    """Deletes credentials row for a site."""
    with Session(engine) as session:
        creds = session.exec(
            select(SiteCredential).where(SiteCredential.site_id == site_id)
        ).all()
        for c in creds:
            session.delete(c)
        session.commit()


def cleanup_expired_credentials() -> int:
    """Deletes all expired credential records across all sites."""
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        expired = session.exec(
            select(SiteCredential).where(SiteCredential.expires_at <= now)
        ).all()
        count = len(expired)
        for c in expired:
            session.delete(c)
        session.commit()
        return count
