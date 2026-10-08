"""
Phase D proof suite: Reproduces confirmed findings with failing assertions.
"""
import os
import re
import uuid
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.main import app
from app.models import User, Site, Run, engine
from app.auth import create_session_token, SESSION_COOKIE_NAME, hash_password
from app.creds import get_fernet

class TestPhaseDProofs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with Session(engine) as s:
            cls.u1 = User(email=f"d_u1_{uuid.uuid4().hex[:6]}@example.com", password_hash=hash_password("Pass1234!"), email_verified=True)
            cls.u2 = User(email=f"d_u2_{uuid.uuid4().hex[:6]}@example.com", password_hash=hash_password("Pass1234!"), email_verified=True)
            s.add(cls.u1)
            s.add(cls.u2)
            s.commit()
            s.refresh(cls.u1)
            s.refresh(cls.u2)

            cls.site1 = Site(user_id=cls.u1.id, url="https://u1-site.org", domain="u1-site.org", verify_token="tok1")
            s.add(cls.site1)
            s.commit()
            s.refresh(cls.site1)

            # Run owned by u1
            cls.run_u1 = Run(user_id=cls.u1.id, site_id=cls.site1.id, engine="chromium", status="passed", mode="public", started_at="2026-01-01T00:00:00", finished_at="2026-01-01T00:01:00")
            # Run with user_id NULL
            cls.run_null = Run(user_id=None, site_id=cls.site1.id, engine="chromium", status="passed", mode="public", started_at="2026-01-01T00:00:00", finished_at="2026-01-01T00:01:00")
            s.add(cls.run_u1)
            s.add(cls.run_null)
            s.commit()
            cls.u1_id = cls.u1.id
            cls.u2_id = cls.u2.id
            cls.site1_id = cls.site1.id
            cls.run_u1_id = cls.run_u1.id
            cls.run_null_id = cls.run_null.id

        cls.c1 = TestClient(app, cookies={SESSION_COOKIE_NAME: create_session_token(cls.u1_id)})
        cls.c2 = TestClient(app, cookies={SESSION_COOKIE_NAME: create_session_token(cls.u2_id)})
        cls.c_anon = TestClient(app)

    # F1: Public docs
    def test_F1_docs_public(self):
        r = self.c_anon.get("/docs")
        self.assertEqual(r.status_code, 404, "F1: /docs should be disabled in production")

    # F4: IDOR on /report/{id}
    def test_F4_idor_report(self):
        r = self.c2.get(f"/report/{self.run_u1_id}")
        self.assertIn(r.status_code, [403, 404], f"F4: User 2 can view User 1 report (status={r.status_code})")

    # F5: IDOR on /runs/{id}/status when user_id is NULL
    def test_F5_idor_status_null_user(self):
        r = self.c2.get(f"/runs/{self.run_null_id}/status")
        self.assertIn(r.status_code, [403, 404], f"F5: User 2 can view unowned run status (status={r.status_code})")

    # F6: Missing CSRF on /wizard/start
    def test_F6_wizard_start_no_csrf(self):
        r = self.c1.post("/wizard/start", data={"url": "https://example.com"}, follow_redirects=False)
        self.assertIn(r.status_code, [400, 403], f"F6: /wizard/start accepted POST with no CSRF (status={r.status_code})")

    # F7: Artifacts served to unauthenticated / unauthorized
    def test_F7_artifacts_unauthenticated(self):
        art_file = Path("artifacts") / f"proof_f7_{self.run_u1_id}.png"
        art_file.write_bytes(b"SECRET_DATA")
        try:
            r = self.c_anon.get(f"/artifacts/{art_file.name}")
            self.assertIn(r.status_code, [401, 403, 404], f"F7: Anon can download artifact (status={r.status_code})")
        finally:
            art_file.unlink(missing_ok=True)

    # F8: /history discloses all users' runs
    def test_F8_history_isolation(self):
        r = self.c2.get("/history")
        self.assertNotIn("u1-site.org", r.text, "F8: User 2 history view discloses User 1 runs/sites")

    # F9: /runs/{id}/progress ownership bypass when user_id NULL
    def test_F9_progress_null_user(self):
        r = self.c2.get(f"/runs/{self.run_null_id}/progress", follow_redirects=False)
        self.assertIn(r.status_code, [403, 404, 303], f"F9: User 2 accessed unowned progress page directly (status={r.status_code})")
        if r.status_code == 303:
            self.assertNotEqual(r.headers.get("location"), f"/report/{self.run_null_id}", "F9: User 2 redirected to report of unowned run")

    # F12: Insecure hardcoded default Fernet key fallback prevented
    def test_F12_fernet_hardcoded_key(self):
        old_env = os.environ.pop("FERNET_KEY", None)
        old_local = os.environ.pop("LOCAL_MODE", None)
        try:
            with self.assertRaises(RuntimeError):
                get_fernet()
        finally:
            if old_env:
                os.environ["FERNET_KEY"] = old_env
            if old_local:
                os.environ["LOCAL_MODE"] = old_local

    # F14 / F19: POST /run disabled in non-local mode
    def test_F14_post_run_unowned(self):
        old_local = os.environ.pop("LOCAL_MODE", None)
        try:
            r = self.c1.post("/run", data={"engine": "chromium"}, follow_redirects=False)
            self.assertEqual(r.status_code, 404, "POST /run must return 404 in non-local mode")
        finally:
            if old_local:
                os.environ["LOCAL_MODE"] = old_local
