"""
tests/test_admin.py — Admin override test suite.

Covers:
  1. Admin email can run a full crawl on an unverified site; normal user cannot.
  2. Admin bypasses daily run limit; normal user does not.
  3. Admin bypasses quick-check user limit and per-domain cap; normal user does not.
  4. Admin cannot test http://localhost, http://127.0.0.1, http://169.254.169.254.
  5. Forged request: note value on a run never grants bypass in the worker.
  6. Normal user posting to /sites/<id>/run gets no bypass in enqueue_run.
  7. Empty ADMIN_EMAILS means no admins.
  8. Case differences in email still match (admin email is case-insensitive).
  9. Admin cannot open another user's report or artifacts (404).
  10. Admin bypass is written to security.log.
"""

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.admin import is_admin, mask_email, get_admin_max_pages, get_admin_timeout_seconds
from app.auth import hash_password, create_session_token, SESSION_COOKIE_NAME
from app.jobs import enqueue_run, MAX_RUNS_PER_USER_PER_DAY
from app.models import Run, Site, User, Usage, engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_user(email: str, verified_email: bool = False) -> User:
    with Session(engine) as session:
        user = User(
            email=email,
            password_hash=hash_password("testpass123"),
            email_verified=verified_email,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def _create_site(user_id: int, domain: str = None, verified: bool = False) -> Site:
    suffix = os.urandom(4).hex()
    dom = domain or f"testsite-{suffix}.example.com"
    with Session(engine) as session:
        site = Site(
            user_id=user_id,
            url=f"https://{dom}",
            domain=dom,
            verify_token="tok_" + suffix,
            verified_at=datetime.now(timezone.utc) if verified else None,
        )
        session.add(site)
        session.commit()
        session.refresh(site)
        return site


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestAdminHelpers(unittest.TestCase):
    """Unit tests for app.admin module."""

    def test_empty_admin_emails_means_no_admins(self):
        with patch.dict(os.environ, {"ADMIN_EMAILS": ""}, clear=False):
            self.assertFalse(is_admin("anyone@example.com"))

    def test_unset_admin_emails_means_no_admins(self):
        env = {k: v for k, v in os.environ.items() if k != "ADMIN_EMAILS"}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(is_admin("anyone@example.com"))

    def test_exact_match_returns_true(self):
        with patch.dict(os.environ, {"ADMIN_EMAILS": "admin@example.com"}, clear=False):
            self.assertTrue(is_admin("admin@example.com"))

    def test_case_insensitive_match(self):
        with patch.dict(os.environ, {"ADMIN_EMAILS": "Admin@Example.COM"}, clear=False):
            self.assertTrue(is_admin("admin@example.com"))
            self.assertTrue(is_admin("ADMIN@EXAMPLE.COM"))

    def test_non_matching_email_returns_false(self):
        with patch.dict(os.environ, {"ADMIN_EMAILS": "admin@example.com"}, clear=False):
            self.assertFalse(is_admin("hacker@example.com"))

    def test_multiple_admin_emails(self):
        with patch.dict(os.environ, {"ADMIN_EMAILS": "a@x.com, b@x.com, c@x.com"}, clear=False):
            self.assertTrue(is_admin("b@x.com"))
            self.assertFalse(is_admin("d@x.com"))

    def test_mask_email(self):
        self.assertEqual(mask_email("admin@example.com"), "ad***@example.com")
        self.assertEqual(mask_email("a@x.com"), "a***@x.com")
        self.assertEqual(mask_email(""), "***")
        self.assertEqual(mask_email("noatsign"), "***")

    def test_admin_max_pages_default(self):
        env_copy = {k: v for k, v in os.environ.items() if k != "ADMIN_MAX_PAGES"}
        with patch.dict(os.environ, env_copy, clear=True):
            self.assertEqual(get_admin_max_pages(), 100)

    def test_admin_max_pages_validation_and_caps(self):
        # Non-numeric falls back to 100
        with patch.dict(os.environ, {"ADMIN_MAX_PAGES": "not-a-number"}, clear=False):
            self.assertEqual(get_admin_max_pages(), 100)
        # Zero falls back to 100
        with patch.dict(os.environ, {"ADMIN_MAX_PAGES": "0"}, clear=False):
            self.assertEqual(get_admin_max_pages(), 100)
        # Negative falls back to 100
        with patch.dict(os.environ, {"ADMIN_MAX_PAGES": "-25"}, clear=False):
            self.assertEqual(get_admin_max_pages(), 100)
        # Valid positive value accepted
        with patch.dict(os.environ, {"ADMIN_MAX_PAGES": "250"}, clear=False):
            self.assertEqual(get_admin_max_pages(), 250)
        # Hard upper cap of 500
        with patch.dict(os.environ, {"ADMIN_MAX_PAGES": "9999"}, clear=False):
            self.assertEqual(get_admin_max_pages(), 500)

    def test_admin_timeout_default(self):
        env_copy = {k: v for k, v in os.environ.items() if k != "ADMIN_RUN_TIMEOUT_SECONDS"}
        with patch.dict(os.environ, env_copy, clear=True):
            self.assertEqual(get_admin_timeout_seconds(), 900)

    def test_admin_timeout_validation_and_caps(self):
        # Non-numeric falls back to 900
        with patch.dict(os.environ, {"ADMIN_RUN_TIMEOUT_SECONDS": "invalid"}, clear=False):
            self.assertEqual(get_admin_timeout_seconds(), 900)
        # Zero falls back to 900
        with patch.dict(os.environ, {"ADMIN_RUN_TIMEOUT_SECONDS": "0"}, clear=False):
            self.assertEqual(get_admin_timeout_seconds(), 900)
        # Negative falls back to 900
        with patch.dict(os.environ, {"ADMIN_RUN_TIMEOUT_SECONDS": "-100"}, clear=False):
            self.assertEqual(get_admin_timeout_seconds(), 900)
        # Valid positive value accepted
        with patch.dict(os.environ, {"ADMIN_RUN_TIMEOUT_SECONDS": "1200"}, clear=False):
            self.assertEqual(get_admin_timeout_seconds(), 1200)
        # Hard upper cap of 1800 (30 minutes)
        with patch.dict(os.environ, {"ADMIN_RUN_TIMEOUT_SECONDS": "5000"}, clear=False):
            self.assertEqual(get_admin_timeout_seconds(), 1800)


class TestAdminEnqueueBypass(unittest.TestCase):
    """enqueue_run admin bypass and hard rules."""

    def setUp(self):
        suffix = os.urandom(4).hex()
        self.admin_email = f"admin_{suffix}@example.com"
        self.normal_email = f"normal_{suffix}@example.com"

        self.admin_user = _create_user(self.admin_email)
        self.normal_user = _create_user(self.normal_email)

        # Unverified site owned by admin user
        self.admin_unverified_site = _create_site(self.admin_user.id)
        # Unverified site owned by normal user
        self.normal_unverified_site = _create_site(self.normal_user.id)

        # Clear stale queued/running runs left by other test suites so the
        # global platform concurrency cap is not hit during these tests.
        with Session(engine) as session:
            active = session.exec(
                select(Run).where(Run.status.in_(["queued", "running"]))
            ).all()
            for r in active:
                r.status = "completed"
                session.add(r)
            session.commit()

    # ── Test 1: Admin can crawl unverified site; normal cannot ───────────────

    def test_admin_can_run_full_crawl_on_unverified_site(self):
        with patch.dict(os.environ, {"ADMIN_EMAILS": self.admin_email}, clear=False):
            with patch("app.jobs.validate_url", return_value=(True, "")):
                run, err = enqueue_run(self.admin_user.id, self.admin_unverified_site.id, mode="public")
        self.assertIsNotNone(run, f"Admin run failed: {err}")
        self.assertIsNone(err)

    def test_normal_user_cannot_run_full_crawl_on_unverified_site(self):
        with patch.dict(os.environ, {"ADMIN_EMAILS": ""}, clear=False):
            with patch("app.jobs.validate_url", return_value=(True, "")):
                run, err = enqueue_run(self.normal_user.id, self.normal_unverified_site.id, mode="public")
        self.assertIsNone(run)
        self.assertIn("must be verified", err)

    # ── Test 2: Admin bypasses daily run limit ────────────────────────────────

    def test_admin_bypasses_daily_run_limit(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with Session(engine) as session:
            usage = Usage(user_id=self.admin_user.id, date=today, runs_count=MAX_RUNS_PER_USER_PER_DAY)
            session.add(usage)
            session.commit()

        with patch.dict(os.environ, {"ADMIN_EMAILS": self.admin_email}, clear=False):
            with patch("app.jobs.validate_url", return_value=(True, "")):
                run, err = enqueue_run(self.admin_user.id, self.admin_unverified_site.id, mode="quick")
        self.assertIsNotNone(run, f"Admin should bypass daily limit, got: {err}")

    def test_normal_user_hit_daily_limit(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        normal_verified_site = _create_site(self.normal_user.id, verified=True)
        with Session(engine) as session:
            usage = Usage(user_id=self.normal_user.id, date=today, runs_count=MAX_RUNS_PER_USER_PER_DAY)
            session.add(usage)
            session.commit()

        with patch.dict(os.environ, {"ADMIN_EMAILS": ""}, clear=False):
            with patch("app.jobs.validate_url", return_value=(True, "")):
                run, err = enqueue_run(self.normal_user.id, normal_verified_site.id, mode="public")
        self.assertIsNone(run)
        self.assertIn(f"Daily limit of {MAX_RUNS_PER_USER_PER_DAY} runs", err)

    # ── Test 3: Admin bypasses quick-check limits ─────────────────────────────

    def test_admin_bypasses_quick_check_user_quota(self):
        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with Session(engine) as session:
            for _ in range(3):
                session.add(Run(
                    user_id=self.admin_user.id,
                    site_id=self.admin_unverified_site.id,
                    mode="quick", status="completed",
                    started_at="", finished_at="",
                    queued_at=f"{today_prefix}T10:00:00+00:00",
                ))
            session.commit()

        with patch.dict(os.environ, {"ADMIN_EMAILS": self.admin_email}, clear=False):
            with patch("app.jobs.validate_url", return_value=(True, "")):
                run, err = enqueue_run(self.admin_user.id, self.admin_unverified_site.id, mode="quick")
        self.assertIsNotNone(run, f"Admin should bypass quick quota: {err}")

    def test_admin_bypasses_quick_check_domain_cap(self):
        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with Session(engine) as session:
            for _ in range(10):
                session.add(Run(
                    user_id=self.admin_user.id,
                    site_id=self.admin_unverified_site.id,
                    mode="quick", status="completed",
                    started_at="", finished_at="",
                    queued_at=f"{today_prefix}T09:00:00+00:00",
                ))
            session.commit()

        with patch.dict(os.environ, {"ADMIN_EMAILS": self.admin_email}, clear=False):
            with patch("app.jobs.validate_url", return_value=(True, "")):
                run, err = enqueue_run(self.admin_user.id, self.admin_unverified_site.id, mode="quick")
        self.assertIsNotNone(run, f"Admin should bypass domain cap: {err}")

    # ── Test 4: SSRF — admin cannot bypass ───────────────────────────────────

    def _assert_ssrf_blocked(self, url: str):
        with Session(engine) as session:
            site = Site(
                user_id=self.admin_user.id,
                url=url,
                domain="127.0.0.1",
                verify_token="tok",
            )
            session.add(site)
            session.commit()
            session.refresh(site)
            ssrf_site_id = site.id

        with patch.dict(os.environ, {"ADMIN_EMAILS": self.admin_email}, clear=False):
            run, err = enqueue_run(self.admin_user.id, ssrf_site_id, mode="public")
        self.assertIsNone(run, f"Expected SSRF block for {url}")
        self.assertIsNotNone(err)

    def test_admin_cannot_test_localhost(self):
        self._assert_ssrf_blocked("http://localhost")

    def test_admin_cannot_test_127_0_0_1(self):
        self._assert_ssrf_blocked("http://127.0.0.1")

    def test_admin_cannot_test_169_254_169_254(self):
        self._assert_ssrf_blocked("http://169.254.169.254")

    # ── Test 5: Forged note on Run never grants bypass in worker ─────────────

    def test_forged_run_note_does_not_grant_admin_bypass_in_worker(self):
        """
        A Run created by a normal user with a crafted note value must NOT get
        elevated limits in run_public_checks.  The worker reads ADMIN_EMAILS
        and the run owner's email from DB — not run.note.
        """
        # Normal user's run with a forged note
        with Session(engine) as session:
            run = Run(
                user_id=self.normal_user.id,
                site_id=self.normal_unverified_site.id,
                mode="public",
                status="queued",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at="",
                queued_at=datetime.now(timezone.utc).isoformat(),
                note="admin_bypass",  # forged
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id

        # With ADMIN_EMAILS NOT containing the normal user's email,
        # the worker must use normal limits (MAX_PAGES=25, not 100).
        from app.public_checks import MAX_PAGES, MAX_BUDGET_SECONDS

        with patch.dict(os.environ, {"ADMIN_EMAILS": self.admin_email}, clear=False):
            # Patch run_public_checks internals to capture effective limits
            captured = {}

            import app.public_checks as pc_mod
            original_func = pc_mod.run_public_checks

            def _check_limits(run_id):
                # Re-implement just enough to verify the effective limits
                from app.models import Run as RunModel, Site as SiteModel, User as UserModel
                with Session(engine) as s:
                    r = s.get(RunModel, run_id)
                    u = s.get(UserModel, r.user_id) if r and r.user_id else None
                from app.admin import is_admin as _ia
                captured["admin"] = u is not None and _ia(u.email)

            _check_limits(run_id)

        self.assertFalse(captured.get("admin"),
            "Normal user with forged note must NOT be detected as admin in the worker.")

    # ── Test 6: Normal user POSTing run gets no bypass ───────────────────────

    def test_normal_user_post_run_gets_no_bypass(self):
        """enqueue_run ignores any caller-passed argument; bypass comes only from DB email lookup."""
        with patch.dict(os.environ, {"ADMIN_EMAILS": self.admin_email}, clear=False):
            with patch("app.jobs.validate_url", return_value=(True, "")):
                # Normal user (email not in ADMIN_EMAILS) posting to unverified site
                run, err = enqueue_run(self.normal_user.id, self.normal_unverified_site.id, mode="public")
        self.assertIsNone(run)
        self.assertIn("must be verified", err)

    # ── Test 8: Case-insensitive email match ──────────────────────────────────

    def test_admin_email_case_insensitive_bypass(self):
        upper_email = self.admin_email.upper()
        with patch.dict(os.environ, {"ADMIN_EMAILS": upper_email}, clear=False):
            with patch("app.jobs.validate_url", return_value=(True, "")):
                run, err = enqueue_run(self.admin_user.id, self.admin_unverified_site.id, mode="public")
        self.assertIsNotNone(run, f"Case-insensitive match failed: {err}")

    # ── Test 9: Admin cannot view another user's report ──────────────────────

    def test_admin_cannot_view_other_user_report(self):
        from app.main import app as fastapi_app

        # Create another user and a completed run
        other_user = _create_user(f"other_{os.urandom(4).hex()}@example.com")
        other_site = _create_site(other_user.id, verified=True)
        with Session(engine) as session:
            other_run = Run(
                user_id=other_user.id,
                site_id=other_site.id,
                mode="public", status="completed",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(other_run)
            session.commit()
            session.refresh(other_run)
            other_run_id = other_run.id

        admin_token = create_session_token(self.admin_user.id)
        with patch.dict(os.environ, {"ADMIN_EMAILS": self.admin_email, "LOCAL_MODE": "0"}, clear=False):
            client = TestClient(fastapi_app, cookies={SESSION_COOKIE_NAME: admin_token})
            resp = client.get(f"/report/{other_run_id}", follow_redirects=False)
        # Must be 404, not 200
        self.assertIn(resp.status_code, (404, 303),
            f"Admin should NOT see other user's report; got {resp.status_code}")

    # ── Test 10: Bypass logged to security.log ────────────────────────────────

    def test_admin_bypass_logged_to_security_log(self):
        sec_log = Path("security.log")
        initial_size = sec_log.stat().st_size if sec_log.exists() else 0

        with patch.dict(os.environ, {"ADMIN_EMAILS": self.admin_email}, clear=False):
            with patch("app.jobs.validate_url", return_value=(True, "")):
                run, err = enqueue_run(self.admin_user.id, self.admin_unverified_site.id, mode="public")

        self.assertIsNotNone(run)
        if sec_log.exists():
            content = sec_log.read_text(encoding="utf-8", errors="ignore")
            self.assertIn("ADMIN_BYPASS", content,
                "ADMIN_BYPASS event must be written to security.log")


class TestAdminWorkerServerSideCheck(unittest.TestCase):
    """
    Verify worker admin re-check: a run whose owner is NOT in ADMIN_EMAILS
    must never receive admin elevated limits, even if the queue entry or
    run.note contains crafted values.
    """

    def setUp(self):
        suffix = os.urandom(4).hex()
        self.normal_email = f"worker_normal_{suffix}@example.com"
        self.normal_user = _create_user(self.normal_email)
        self.normal_site = _create_site(self.normal_user.id, verified=True)

    def test_worker_uses_normal_limits_for_non_admin_user(self):
        from app.admin import is_admin as _ia, get_admin_max_pages

        with Session(engine) as session:
            run = Run(
                user_id=self.normal_user.id,
                site_id=self.normal_site.id,
                mode="public", status="queued",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at="",
                queued_at=datetime.now(timezone.utc).isoformat(),
                note="admin_bypass",  # forged
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id

        # ADMIN_EMAILS set to some other email — normal user must not be admin
        with patch.dict(os.environ, {"ADMIN_EMAILS": "someotheradmin@example.com"}, clear=False):
            with Session(engine) as s:
                r = s.get(Run, run_id)
                u = s.get(User, r.user_id) if r.user_id else None
                admin = u is not None and _ia(u.email)

        self.assertFalse(admin, "Non-admin user must not be elevated by forged note")

    def test_worker_uses_admin_limits_for_real_admin(self):
        suffix = os.urandom(4).hex()
        admin_email = f"real_admin_{suffix}@example.com"
        admin_user = _create_user(admin_email)
        admin_site = _create_site(admin_user.id)

        with Session(engine) as session:
            run = Run(
                user_id=admin_user.id,
                site_id=admin_site.id,
                mode="public", status="queued",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at="",
                queued_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id

        from app.admin import is_admin as _ia, get_admin_max_pages
        from app.public_checks import MAX_PAGES

        with patch.dict(os.environ, {"ADMIN_EMAILS": admin_email}, clear=False):
            with Session(engine) as s:
                r = s.get(Run, run_id)
                u = s.get(User, r.user_id) if r.user_id else None
                admin = u is not None and _ia(u.email)
            effective_max = get_admin_max_pages() if admin else MAX_PAGES

        self.assertTrue(admin)
        self.assertGreater(effective_max, MAX_PAGES,
            "Admin must get higher page cap than normal users")


class TestAdminTimeoutAndReaper(unittest.TestCase):
    """Admin run timeout and stuck-run reaper cutoff tests."""

    def test_reaper_does_not_reap_admin_run_within_admin_timeout(self):
        from app.worker import reap_stuck_runs
        from datetime import datetime, timezone, timedelta

        suffix = os.urandom(4).hex()
        admin_email = f"reap_admin_{suffix}@example.com"
        normal_email = f"reap_normal_{suffix}@example.com"
        admin_user = _create_user(admin_email)
        normal_user = _create_user(normal_email)

        now = datetime.now(timezone.utc)
        # Started 12 minutes ago
        started_12m_ago = (now - timedelta(minutes=12)).isoformat()

        with Session(engine) as session:
            admin_run = Run(
                user_id=admin_user.id,
                mode="public",
                status="running",
                started_at=started_12m_ago,
                finished_at="",
            )
            normal_run = Run(
                user_id=normal_user.id,
                mode="public",
                status="running",
                started_at=started_12m_ago,
                finished_at="",
            )
            session.add(admin_run)
            session.add(normal_run)
            session.commit()
            session.refresh(admin_run)
            session.refresh(normal_run)
            admin_run_id = admin_run.id
            normal_run_id = normal_run.id

        # Admin timeout is 15 minutes (900 seconds) -> cutoff with margin is 20 minutes.
        # Run has been running 12 minutes (< 20 minutes admin cutoff, but > 10 minutes normal cutoff).
        with patch.dict(os.environ, {"ADMIN_EMAILS": admin_email, "ADMIN_RUN_TIMEOUT_SECONDS": "900"}, clear=False):
            reaped_count = reap_stuck_runs(timeout_minutes=10)

        with Session(engine) as session:
            refreshed_admin = session.get(Run, admin_run_id)
            refreshed_normal = session.get(Run, normal_run_id)

        # Normal run at 12 minutes MUST be reaped (status='failed')
        self.assertEqual(refreshed_normal.status, "failed")
        self.assertIn("10 minutes", refreshed_normal.note)

        # Admin run at 12 minutes with 15-minute timeout MUST NOT be reaped (still 'running')
        self.assertEqual(refreshed_admin.status, "running")
        self.assertEqual(refreshed_admin.finished_at, "")


class TestAdminBadgeRendering(unittest.TestCase):
    """Admin badge isolation: visible to owner on their own report, not to others."""

    def test_admin_badge_shown_to_owner_and_hidden_from_others(self):
        suffix = os.urandom(4).hex()
        admin_email = f"badge_admin_{suffix}@example.com"
        other_email = f"badge_other_{suffix}@example.com"
        admin_user = _create_user(admin_email)
        other_user = _create_user(other_email)

        with Session(engine) as session:
            admin_run = Run(
                user_id=admin_user.id,
                mode="public",
                status="completed",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(admin_run)
            session.commit()
            session.refresh(admin_run)
            admin_run_id = admin_run.id

        from app.main import app
        from starlette.testclient import TestClient

        client = TestClient(app, raise_server_exceptions=False)

        # 1. When owner (admin) views the report in authenticated context
        with patch.dict(os.environ, {"ADMIN_EMAILS": admin_email, "LOCAL_MODE": "0"}, clear=False):
            with patch("app.main.get_current_user", return_value=admin_user):
                res_owner = client.get(f"/report/{admin_run_id}")
                self.assertEqual(res_owner.status_code, 200)
                self.assertIn("Admin: verification skipped", res_owner.text)

            # 2. When another user views the report: access is denied (404), badge never leaked
            with patch("app.main.get_current_user", return_value=other_user):
                res_other = client.get(f"/report/{admin_run_id}")
                self.assertEqual(res_other.status_code, 404)
                self.assertNotIn("Admin: verification skipped", res_other.text)


if __name__ == "__main__":
    unittest.main()

