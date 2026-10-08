"""
Phase E follow-up tests: F7 traversal, F13 reaper, F20 cleanup,
F22 terms/privacy, F23 comparison scope.
"""
import os
import uuid
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.auth import create_session_token, hash_password, SESSION_COOKIE_NAME
from app.models import User, Site, Run, Page, SiteCredential, engine
from app.worker import reap_stuck_runs, run_retention_cleanup
from app.main import app


def _mk_user(s: Session) -> User:
    u = User(
        email=f"e2test_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Pass1234!"),
        email_verified=True,
    )
    s.add(u)
    s.commit()
    s.refresh(u)
    return u


def _mk_site(s: Session, user_id: int, domain_suffix: str = "") -> Site:
    site = Site(
        user_id=user_id,
        url=f"https://site-{domain_suffix}.example.com",
        domain=f"site-{domain_suffix}.example.com",
        verify_token="tok",
    )
    s.add(site)
    s.commit()
    s.refresh(site)
    return site


def _mk_run(s: Session, user_id, site_id, status="completed", started_at=None) -> Run:
    now_str = started_at or datetime.now(timezone.utc).isoformat()
    r = Run(
        user_id=user_id,
        site_id=site_id,
        engine="chromium",
        status=status,
        started_at=now_str,
        finished_at=now_str,
        mode="public",
    )
    s.add(r)
    s.commit()
    s.refresh(r)
    return r


# ── F7: artifact traversal & cross-user access ───────────────────────────────

class TestF7ArtifactSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Force production-mode ownership checking
        cls._old_local = os.environ.pop("LOCAL_MODE", None)
        os.environ["LOCAL_MODE"] = "0"

        with Session(engine) as s:
            cls.u1 = _mk_user(s)
            cls.u2 = _mk_user(s)
            site = _mk_site(s, cls.u1.id, "f7")
            cls.run1 = _mk_run(s, cls.u1.id, site.id)
            cls.run1_id = cls.run1.id
            cls.u1_id = cls.u1.id
            cls.u2_id = cls.u2.id

        # Create a real file in the run's subdirectory
        cls.art_dir = Path("artifacts") / str(cls.run1_id)
        cls.art_dir.mkdir(parents=True, exist_ok=True)
        cls.art_file = cls.art_dir / "secret.png"
        cls.art_file.write_bytes(b"OWNER_SECRET")

        cls.c1 = TestClient(app, cookies={SESSION_COOKIE_NAME: create_session_token(cls.u1_id)})
        cls.c2 = TestClient(app, cookies={SESSION_COOKIE_NAME: create_session_token(cls.u2_id)})
        cls.c_anon = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.art_dir, ignore_errors=True)
        if cls._old_local is not None:
            os.environ["LOCAL_MODE"] = cls._old_local
        else:
            os.environ.pop("LOCAL_MODE", None)

    def test_owner_can_access_artifact(self):
        r = self.c1.get(f"/artifacts/{self.run1_id}/secret.png", follow_redirects=False)
        # Owner should get 200 or redirect (not 403/404)
        self.assertIn(r.status_code, [200, 302, 303],
                      f"Owner could not access their artifact: {r.status_code}")

    def test_other_user_cannot_access_artifact(self):
        r = self.c2.get(f"/artifacts/{self.run1_id}/secret.png", follow_redirects=False)
        self.assertIn(r.status_code, [403, 404],
                      f"User 2 could access User 1 artifact: {r.status_code}")

    def test_anon_cannot_access_artifact(self):
        r = self.c_anon.get(f"/artifacts/{self.run1_id}/secret.png", follow_redirects=False)
        self.assertIn(r.status_code, [401, 403, 404],
                      f"Anon could access artifact: {r.status_code}")

    def test_path_traversal_dotdot_rejected(self):
        r = self.c1.get(f"/artifacts/{self.run1_id}/../secret.png", follow_redirects=False)
        self.assertIn(r.status_code, [400, 403, 404],
                      f"Path traversal ../ not blocked: {r.status_code}")

    def test_path_traversal_encoded_rejected(self):
        r = self.c1.get(f"/artifacts/{self.run1_id}/%2e%2e/secret.png", follow_redirects=False)
        self.assertIn(r.status_code, [400, 403, 404],
                      f"Encoded traversal %2e%2e not blocked: {r.status_code}")


# ── F13: reaper marks stuck runs as failed ───────────────────────────────────

class TestF13Reaper(unittest.TestCase):
    def setUp(self):
        with Session(engine) as s:
            u = _mk_user(s)
            site = _mk_site(s, u.id, "f13")
            # Run started 15 minutes ago, still "running"
            old = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
            self.run = _mk_run(s, u.id, site.id, status="running", started_at=old)
            self.run_id = self.run.id

    def test_reaper_marks_stuck_run_failed(self):
        reaped = reap_stuck_runs(timeout_minutes=10)
        self.assertGreaterEqual(reaped, 1, "Reaper should have reaped at least 1 stuck run")
        with Session(engine) as s:
            run = s.get(Run, self.run_id)
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "failed",
                             f"Stuck run should be 'failed', got '{run.status}'")
            self.assertIsNotNone(run.finished_at,
                                 "finished_at should be set after reaping")

    def test_fresh_run_not_reaped(self):
        """A run started 2 min ago should NOT be reaped."""
        with Session(engine) as s:
            u = _mk_user(s)
            site = _mk_site(s, u.id, "f13fresh")
            fresh_run = _mk_run(s, u.id, site.id, status="running")
            fresh_id = fresh_run.id

        reap_stuck_runs(timeout_minutes=10)
        with Session(engine) as s:
            run = s.get(Run, fresh_id)
            self.assertEqual(run.status, "running",
                             "Fresh run must not be reaped")

    def test_reaper_marks_stuck_queued_run_failed(self):
        with Session(engine) as s:
            u = _mk_user(s)
            site = _mk_site(s, u.id, "f13queued")
            old_queued = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
            stuck_q_run = _mk_run(s, u.id, site.id, status="queued", started_at=old_queued)
            stuck_q_run.queued_at = old_queued
            s.add(stuck_q_run)
            s.commit()
            s.refresh(stuck_q_run)
            q_id = stuck_q_run.id

        reaped = reap_stuck_runs(timeout_minutes=10, queued_timeout_minutes=15)
        self.assertGreaterEqual(reaped, 1)
        with Session(engine) as s:
            run = s.get(Run, q_id)
            self.assertEqual(run.status, "failed")
            self.assertEqual(run.note, "Job was never picked up")
            self.assertIsNotNone(run.finished_at)


# ── F20: cleanup deletes expired credentials and old runs ─────────────────────

class TestF20Cleanup(unittest.TestCase):
    def setUp(self):
        from app.creds import store_credentials

        with Session(engine) as s:
            u = _mk_user(s)
            self.site = _mk_site(s, u.id, "f20")
            self.site_id = self.site.id
            self.u_id = u.id

            # Old run (35 days old)
            old = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
            self.old_run = _mk_run(s, u.id, self.site_id, status="completed", started_at=old)
            self.old_run_id = self.old_run.id

            # Recent run (stays)
            self.new_run = _mk_run(s, u.id, self.site_id, status="completed")
            self.new_run_id = self.new_run.id

        # Store a credential that is already expired
        with Session(engine) as s:
            cred = SiteCredential(
                site_id=self.site_id,
                login_url="https://example.com/login",
                username_enc="x",
                password_enc="x",
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # already expired
            )
            s.add(cred)
            s.commit()
            self.cred_id = cred.id

        # Create artifact folder for old run
        self.art_dir = Path("artifacts") / str(self.old_run_id)
        self.art_dir.mkdir(parents=True, exist_ok=True)
        (self.art_dir / "dummy.png").write_bytes(b"old_data")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.art_dir, ignore_errors=True)

    def test_cleanup_removes_old_run(self):
        run_retention_cleanup(retention_days=30)
        with Session(engine) as s:
            self.assertIsNone(s.get(Run, self.old_run_id),
                              "Old run (35d) should be deleted by cleanup")
            self.assertIsNotNone(s.get(Run, self.new_run_id),
                                 "Recent run should survive cleanup")

    def test_cleanup_deletes_expired_credentials(self):
        run_retention_cleanup(retention_days=30)
        with Session(engine) as s:
            cred = s.get(SiteCredential, self.cred_id)
            self.assertIsNone(cred, "Expired credential should be deleted by cleanup")

    def test_cleanup_removes_artifact_dir(self):
        run_retention_cleanup(retention_days=30)
        self.assertFalse(self.art_dir.is_dir(),
                         "Artifact directory for deleted run should be removed")


# ── F22: /terms and /privacy return real text ────────────────────────────────

class TestF22TermsPrivacy(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_terms_contains_text(self):
        r = self.client.get("/terms")
        self.assertEqual(r.status_code, 200)
        body = r.text
        self.assertIn("Terms", body, "/terms page contains no 'Terms' text")
        self.assertGreater(len(body.strip()), 200,
                           "/terms page is suspiciously empty")

    def test_privacy_contains_text(self):
        r = self.client.get("/privacy")
        self.assertEqual(r.status_code, 200)
        body = r.text
        self.assertIn("Privacy", body, "/privacy page contains no 'Privacy' text")
        self.assertGreater(len(body.strip()), 200,
                           "/privacy page is suspiciously empty")


# ── F23: comparison scoped to same user, site, engine ────────────────────────

class TestF23ComparisonScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with Session(engine) as s:
            cls.u1 = _mk_user(s)
            cls.u2 = _mk_user(s)
            site1 = _mk_site(s, cls.u1.id, "f23a")
            site2 = _mk_site(s, cls.u2.id, "f23b")

            # u1 has two runs on site1 (same engine) → comparison should work
            cls.run_u1_prev = _mk_run(s, cls.u1.id, site1.id)
            cls.run_u1_cur  = _mk_run(s, cls.u1.id, site1.id)

            # u2 has a run on site2 (different user/site)
            cls.run_u2 = _mk_run(s, cls.u2.id, site2.id)

            cls.u1_id = cls.u1.id
            cls.u2_id = cls.u2.id
            cls.run_u1_prev_id = cls.run_u1_prev.id
            cls.run_u1_cur_id  = cls.run_u1_cur.id
            cls.run_u2_id      = cls.run_u2.id

        cls.c1 = TestClient(app, cookies={SESSION_COOKIE_NAME: create_session_token(cls.u1_id)})
        cls.c2 = TestClient(app, cookies={SESSION_COOKIE_NAME: create_session_token(cls.u2_id)})

    def test_previous_run_is_own_run(self):
        """Report for u1's second run must link previous=u1's first run, not u2's run."""
        r = self.c1.get(f"/report/{self.run_u1_cur_id}")
        self.assertEqual(r.status_code, 200)
        # The u2 run id must not appear as "previous run" in the response
        self.assertNotIn(f"previous_run_id={self.run_u2_id}", r.text)

    def test_comparison_not_cross_user(self):
        """u2 report must not see u1's run as previous."""
        r = self.c2.get(f"/report/{self.run_u2_id}")
        self.assertEqual(r.status_code, 200)
        # u1 run ids must not appear as previous run in u2's report
        self.assertNotIn(f"/report/{self.run_u1_prev_id}", r.text)
        self.assertNotIn(f"/report/{self.run_u1_cur_id}", r.text)


# ── S1 & run.note: Session versioning & failure notes ─────────────────────────

class TestSessionVersionLogout(unittest.TestCase):
    def setUp(self):
        with Session(engine) as s:
            self.user = _mk_user(s)
            self.user_id = self.user.id
            self.orig_version = self.user.session_version

    @unittest.skipIf(__import__("os").getenv("LOCAL_MODE", "0") == "1", "Local mode bypasses auth checks by design")
    def test_copied_cookie_invalid_after_logout(self):
        # Client 1 logs in or creates token
        token = create_session_token(self.user_id, session_version=self.orig_version)
        client = TestClient(app, cookies={SESSION_COOKIE_NAME: token})

        # Can access /history
        r = client.get("/history")
        self.assertEqual(r.status_code, 200)

        # Logout via POST /logout with CSRF
        from app.auth import generate_csrf_token
        csrf = generate_csrf_token(token)
        r_logout = client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)
        self.assertEqual(r_logout.status_code, 303)

        # Copied old token must now be rejected
        attacker_client = TestClient(app, cookies={SESSION_COOKIE_NAME: token})
        r_after = attacker_client.get("/history", follow_redirects=False)
        self.assertIn(r_after.status_code, (302, 303, 307))
        self.assertIn("/login", r_after.headers.get("location", ""))

    @unittest.skipIf(__import__("os").getenv("LOCAL_MODE", "0") == "1", "Local mode bypasses auth checks by design")
    def test_old_version_cookie_rejected(self):
        # Token with version 0 or older
        old_token = create_session_token(self.user_id, session_version=self.orig_version - 1)
        client = TestClient(app, cookies={SESSION_COOKIE_NAME: old_token})
        r = client.get("/history", follow_redirects=False)
        self.assertIn(r.status_code, (302, 303, 307))
        self.assertIn("/login", r.headers.get("location", ""))

    def test_get_logout_does_not_invalidate_session(self):
        token = create_session_token(self.user_id, session_version=self.orig_version)
        client = TestClient(app, cookies={SESSION_COOKIE_NAME: token})

        # GET /logout returns confirmation HTML page, does NOT logout
        r = client.get("/logout")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Confirm Logout", r.text)

        # Session is still valid
        r_hist = client.get("/history")
        self.assertEqual(r_hist.status_code, 200)

        # User version unchanged in DB
        with Session(engine) as s:
            u = s.get(User, self.user_id)
            self.assertEqual(u.session_version, self.orig_version)

    def test_post_logout_without_csrf_fails(self):
        token = create_session_token(self.user_id, session_version=self.orig_version)
        client = TestClient(app, cookies={SESSION_COOKIE_NAME: token})
        r = client.post("/logout", data={"csrf_token": "invalid_csrf"})
        self.assertEqual(r.status_code, 400)
        # Session still active
        r_hist = client.get("/history")
        self.assertEqual(r_hist.status_code, 200)


class TestRunNoteDisplay(unittest.TestCase):
    def test_failed_run_note_shown_in_report(self):
        with Session(engine) as s:
            u = _mk_user(s)
            site = _mk_site(s, u.id, "runnote")
            run = _mk_run(s, u.id, site.id)
            run.status = "failed"
            run.note = "worker died or timed out"
            s.add(run)
            s.commit()
            s.refresh(run)
            run_id = run.id
            user_id = u.id

        client = TestClient(app, cookies={SESSION_COOKIE_NAME: create_session_token(user_id, 1)})
        r = client.get(f"/report/{run_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("worker died or timed out", r.text)
        self.assertIn("run-note-banner", r.text)


if __name__ == "__main__":
    unittest.main()

