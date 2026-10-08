import os
import shutil
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.auth import create_session_token, delete_user_account, hash_password, SESSION_COOKIE_NAME
from app.creds import store_credentials
from app.main import app, log_security_event
from app.models import Page, Run, Site, SiteCredential, User, engine
from app.worker import run_retention_cleanup


class TestStep7RetentionAndAbuse(unittest.TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:6]
        with Session(engine) as session:
            user = User(
                email=f"abuse_{suffix}@example.com",
                password_hash=hash_password("pw12345678"),
                email_verified=True,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            self.user_id = user.id

            site = Site(
                user_id=user.id,
                url="https://retention.example.com",
                domain="retention.example.com",
                verify_token="tok_abuse",
                verified_at=datetime.now(timezone.utc),
            )
            session.add(site)
            session.commit()
            session.refresh(site)
            self.site_id = site.id

            now_str = datetime.now(timezone.utc).isoformat()
            run = Run(
                user_id=user.id,
                site_id=site.id,
                mode="public",
                engine="chromium",
                status="completed",
                started_at=now_str,
                finished_at=now_str,
                duration_ms=1000,
                session_valid=True,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            self.run_id = run.id

            page = Page(
                run_id=run.id,
                url="https://retention.example.com/test",
                status_code=200,
                load_ms=100,
            )
            session.add(page)
            session.commit()

        # Create dummy artifacts folder on disk
        self.run_folder = Path("artifacts") / str(self.run_id)
        self.run_folder.mkdir(parents=True, exist_ok=True)
        (self.run_folder / "dummy.png").write_text("fake image data")

        self.user_token = create_session_token(self.user_id)

    def test_security_event_logging(self):
        log_security_event("TEST_SECURITY_EVENT", "127.0.0.1", "details=none")
        sec_file = Path("security.log")
        self.assertTrue(sec_file.is_file())
        content = sec_file.read_text(encoding="utf-8")
        self.assertIn("TEST_SECURITY_EVENT", content)

    def test_account_deletion_cleans_up_all_data_and_files(self):
        # Store credential
        store_credentials(self.site_id, "https://retention.example.com/login", "user", "pass")

        # Verify folder and DB entries exist
        self.assertTrue(self.run_folder.is_dir())

        # Perform deletion
        success = delete_user_account(self.user_id)
        self.assertTrue(success)

        # Verify DB entries deleted
        with Session(engine) as session:
            self.assertIsNone(session.get(User, self.user_id))
            self.assertEqual(len(session.exec(select(Site).where(Site.user_id == self.user_id)).all()), 0)
            self.assertEqual(len(session.exec(select(Run).where(Run.user_id == self.user_id)).all()), 0)
            self.assertEqual(len(session.exec(select(SiteCredential).where(SiteCredential.site_id == self.site_id)).all()), 0)
            self.assertEqual(len(session.exec(select(Page).where(Page.run_id == self.run_id)).all()), 0)

        # Verify folder deleted from disk
        self.assertFalse(self.run_folder.is_dir())

    def test_retention_cleanup_removes_old_runs_and_artifacts(self):
        # Set run started_at to 35 days ago
        old_time = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
        with Session(engine) as session:
            r = session.get(Run, self.run_id)
            r.started_at = old_time
            session.add(r)
            session.commit()

        # Run cleanup with 30-day retention
        deleted = run_retention_cleanup(retention_days=30)
        self.assertGreaterEqual(deleted, 1)

        # Check run and folder are gone
        with Session(engine) as session:
            self.assertIsNone(session.get(Run, self.run_id))
            self.assertEqual(len(session.exec(select(Page).where(Page.run_id == self.run_id)).all()), 0)

        self.assertFalse(self.run_folder.is_dir())


if __name__ == "__main__":
    unittest.main()
