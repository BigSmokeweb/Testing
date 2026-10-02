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


def normalize_and_validate_email(email: str) -> str:
    valid = validate_email(email, check_deliverability=False)
    return valid.normalized.lower()
