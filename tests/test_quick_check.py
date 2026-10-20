import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from sqlmodel import Session, select

from app.models import Run, Site, User, Page, LinkCheck, engine
from app.auth import hash_password
from app.jobs import enqueue_run
from app.sites import (
    verify_site_ownership,
    check_html_meta_tag,
    DISALLOWED_SHARED_PUBLIC_SUFFIXES,
)


class TestQuickCheckAndMetaVerification(unittest.TestCase):
    def setUp(self):
        with Session(engine) as session:
            # Clear active queued/running runs from DB so global caps are not hit
            active = session.exec(select(Run).where(Run.status.in_(["queued", "running"]))).all()
            for r in active:
                r.status = "completed"
            session.commit()

            # Create a test user
            self.user = User(
                email=f"quickuser_{os.urandom(4).hex()}@example.com",
                password_hash=hash_password("password123"),
            )
            session.add(self.user)
            session.commit()
            session.refresh(self.user)

            unique_domain = f"quickcheck-{os.urandom(4).hex()}.example.com"
            self.unverified_site = Site(
                user_id=self.user.id,
                url=f"https://{unique_domain}",
                domain=unique_domain,
                verify_token="testtoken12345678",
                verified_at=None,
            )
            session.add(self.unverified_site)
            session.commit()
            session.refresh(self.unverified_site)
            self.user_id = self.user.id
            self.site_id = self.unverified_site.id
            self.site_url = self.unverified_site.url
            self.site_domain = self.unverified_site.domain

    def test_unverified_site_refuses_crawl_or_credentials(self):
        # Full public crawl should be refused
        run, err = enqueue_run(self.user_id, self.site_id, mode="public")
        self.assertIsNone(run)
        self.assertIn("must be verified", err)

        # Authenticated crawl should be refused
        run_creds, err_creds = enqueue_run(self.user_id, self.site_id, mode="credentials")
        self.assertIsNone(run_creds)
        self.assertIn("must be verified", err_creds)

    def test_quick_check_enqueues_on_unverified_site(self):
        # Quick check should succeed on unverified site
        with patch("app.jobs.validate_url", return_value=(True, "")):
            run, err = enqueue_run(self.user_id, self.site_id, mode="quick")
            if run is None:
                print("ENQUEUE ERROR:", err)
            self.assertIsNotNone(run, f"Failed to enqueue run: {err}")
            self.assertIsNone(err)
            self.assertEqual(run.mode, "quick")
            self.assertEqual(run.status, "queued")

    def test_quick_check_daily_quota_limit_per_user(self):
        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with Session(engine) as session:
            # Seed 3 existing quick check runs for today
            for _ in range(3):
                session.add(
                    Run(
                        user_id=self.user_id,
                        site_id=self.site_id,
                        mode="quick",
                        status="completed",
                        started_at="",
                        finished_at="",
                        queued_at=f"{today_prefix}T10:00:00+00:00",
                    )
                )
            session.commit()

        with patch("app.jobs.validate_url", return_value=(True, "")):
            run, err = enqueue_run(self.user_id, self.site_id, mode="quick")
            self.assertIsNone(run)
            self.assertIn("Daily limit of 3 quick checks reached", err)

    def test_quick_check_domain_cap_across_users(self):
        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with Session(engine) as session:
            # Seed 10 existing quick check runs across any user for this domain
            for _ in range(10):
                session.add(
                    Run(
                        user_id=self.user_id,
                        site_id=self.site_id,
                        mode="quick",
                        status="completed",
                        started_at="",
                        finished_at="",
                        queued_at=f"{today_prefix}T09:00:00+00:00",
                    )
                )
            session.commit()

        # Create another user trying to quick-check the same domain
        with Session(engine) as session:
            other_user = User(
                email=f"other_{os.urandom(4).hex()}@example.com",
                password_hash=hash_password("pw123"),
            )
            session.add(other_user)
            session.commit()
            session.refresh(other_user)

            other_site = Site(
                user_id=other_user.id,
                url=self.site_url,
                domain=self.site_domain,
                verify_token="othertok",
            )
            session.add(other_site)
            session.commit()
            session.refresh(other_site)
            other_user_id = other_user.id
            other_site_id = other_site.id

        with patch("app.jobs.validate_url", return_value=(True, "")):
            run, err = enqueue_run(other_user_id, other_site_id, mode="quick")
            self.assertIsNone(run)
            self.assertIn("Quick checks for this site are limited right now", err)

    @patch("app.safety.safe_http_fetch")
    def test_meta_tag_verification_success_case_insensitive_and_quotes(self, mock_fetch):
        html_cases = [
            b'<html><head><meta name="autoqa-verify" content="tok123"></head><body></body></html>',
            b"<html><head><META CONTENT='tok123' NAME='AUTOQA-VERIFY'></head><body></body></html>",
            b'<html><head><meta name="AUTOQA-VERIFY" content="tok123"/></head><body></body></html>',
        ]
        for html in html_cases:
            mock_fetch.return_value = (200, html, {})
            self.assertTrue(check_html_meta_tag("https://example.com", "tok123"))

    @patch("app.safety.safe_http_fetch")
    def test_meta_tag_verification_failure_cases(self, mock_fetch):
        mock_fetch.return_value = (200, b'<html><head><meta name="autoqa-verify" content="wrong"></head></html>', {})
        self.assertFalse(check_html_meta_tag("https://example.com", "tok123"))

        mock_fetch.return_value = (200, b'<html><head></head><body><meta name="autoqa-verify" content="tok123"></body></html>', {})
        self.assertFalse(check_html_meta_tag("https://example.com", "tok123"))

        mock_fetch.return_value = (404, b'Not Found', {})
        self.assertFalse(check_html_meta_tag("https://example.com", "tok123"))

    def test_shared_public_suffix_refused(self):
        for suffix in DISALLOWED_SHARED_PUBLIC_SUFFIXES:
            site = Site(
                user_id=self.user_id,
                url=f"https://{suffix}",
                domain=suffix,
                verify_token="tok",
            )
            self.assertFalse(verify_site_ownership(site))

    def test_skip_ownership_ignored_in_production(self):
        site = Site(
            user_id=self.user_id,
            url="https://unverified-prod.example.com",
            domain="unverified-prod.example.com",
            verify_token="tok",
        )
        with patch.dict(os.environ, {"LOCAL_MODE": "0", "SKIP_OWNERSHIP_FOR_DEV": "1"}):
            with patch("app.sites.check_html_meta_tag", return_value=False), \
                 patch("app.sites.check_well_known_file", return_value=False), \
                 patch("app.sites.check_dns_txt_record", return_value=False):
                self.assertFalse(verify_site_ownership(site))

    def test_skip_ownership_honored_only_in_local_mode(self):
        site = Site(
            user_id=self.user_id,
            url="https://unverified-local.example.com",
            domain="unverified-local.example.com",
            verify_token="tok",
        )
        with patch.dict(os.environ, {"LOCAL_MODE": "1", "SKIP_OWNERSHIP_FOR_DEV": "1"}):
            self.assertTrue(verify_site_ownership(site))

    def test_quick_check_global_concurrency_cap(self):
        with Session(engine) as session:
            # Seed 2 running quick runs
            for _ in range(2):
                session.add(
                    Run(
                        user_id=self.user_id,
                        site_id=self.site_id,
                        mode="quick",
                        status="running",
                        started_at="",
                        finished_at="",
                    )
                )
            session.commit()

        with patch("app.jobs.validate_url", return_value=(True, "")):
            with patch.dict(os.environ, {"MAX_CONCURRENT_QUICK_RUNS_GLOBAL": "2"}):
                run, err = enqueue_run(self.user_id, self.site_id, mode="quick")
                self.assertIsNone(run)
                self.assertIn("Platform is busy with quick checks. Please try again in a minute.", err)

    def test_quick_and_full_runs_do_not_cross_count_global_caps(self):
        # 3 active full runs should NOT block a quick check
        with Session(engine) as session:
            # Clear active
            active = session.exec(select(Run).where(Run.status.in_(["queued", "running"]))).all()
            for r in active:
                r.status = "completed"
            for _ in range(3):
                session.add(
                    Run(
                        user_id=self.user_id,
                        site_id=self.site_id,
                        mode="public",
                        status="running",
                        started_at="",
                        finished_at="",
                    )
                )
            session.commit()

        # Another user so per-user limit isn't tripped
        other_user = None
        unique_cross_dom = f"cross-{os.urandom(4).hex()}.example.com"
        with Session(engine) as session:
            other_user = User(email=f"cross_{os.urandom(4).hex()}@example.com", password_hash="hash")
            session.add(other_user)
            session.commit()
            session.refresh(other_user)
            other_site = Site(user_id=other_user.id, url=f"https://{unique_cross_dom}", domain=unique_cross_dom, verify_token="tok")
            session.add(other_site)
            session.commit()
            session.refresh(other_site)
            uid = other_user.id
            sid = other_site.id

        with patch("app.jobs.validate_url", return_value=(True, "")):
            with patch.dict(os.environ, {"MAX_CONCURRENT_QUICK_RUNS_GLOBAL": "2", "MAX_CONCURRENT_RUNS_GLOBAL": "3"}):
                # Quick check still succeeds even though full runs hit global cap
                run, err = enqueue_run(uid, sid, mode="quick")
                self.assertIsNotNone(run, f"Expected quick run to enqueue, got error: {err}")
                self.assertIsNone(err)

    def test_worker_refuses_public_mode_on_unverified_site(self):
        from app.worker import run_job_entry

        with Session(engine) as session:
            run = Run(
                user_id=self.user_id,
                site_id=self.site_id,
                mode="public",
                status="queued",
                started_at="",
                finished_at="",
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id

        with patch.dict(os.environ, {"LOCAL_MODE": "0", "ADMIN_EMAILS": ""}):
            run_job_entry(run_id)

        with Session(engine) as session:
            refreshed = session.get(Run, run_id)
            self.assertEqual(refreshed.status, "failed")
            self.assertIn("Site is not verified", refreshed.note)

    def test_http_post_public_mode_refused_on_unverified_site(self):
        from app.main import app
        from starlette.testclient import TestClient

        client = TestClient(app, raise_server_exceptions=False)
        with patch.dict(os.environ, {"LOCAL_MODE": "0", "ADMIN_EMAILS": ""}):
            with patch("app.main.get_current_user", return_value=self.user):
                with patch("app.main.verify_csrf_token", return_value=True):
                    res = client.post(
                        f"/sites/{self.site_id}/run",
                        data={"mode": "public", "csrf_token": "token"},
                        follow_redirects=False,
                    )
                    # Redirects back to /sites with error in query param
                    self.assertEqual(res.status_code, 303)
                    self.assertIn("error=", res.headers["location"])
                    self.assertIn("must+be+verified", res.headers["location"])

    def test_normalize_domain_cases(self):
        from app.sites import normalize_domain

        # Example.com -> example.com
        self.assertEqual(normalize_domain("Example.com"), "example.com")
        # www.example.com -> example.com
        self.assertEqual(normalize_domain("www.example.com"), "example.com")
        # example.com. -> example.com
        self.assertEqual(normalize_domain("example.com."), "example.com")
        # example.com:8080 -> example.com
        self.assertEqual(normalize_domain("example.com:8080"), "example.com")
        # Subdomain must stay different
        self.assertEqual(normalize_domain("app.example.com"), "app.example.com")
        self.assertNotEqual(normalize_domain("app.example.com"), normalize_domain("example.com"))
        # Combination: www.Example.com.:8443
        self.assertEqual(normalize_domain("www.Example.com.:8443"), "example.com")

    def test_concurrent_quick_checks_quota_race(self):
        import concurrent.futures

        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with Session(engine) as session:
            # Seed 2 existing quick check runs for today (quota is 3, so only 1 more can pass)
            for _ in range(2):
                session.add(
                    Run(
                        user_id=self.user_id,
                        site_id=self.site_id,
                        mode="quick",
                        status="completed",
                        started_at="",
                        finished_at="",
                        queued_at=f"{today_prefix}T10:00:00+00:00",
                    )
                )
            session.commit()

        with Session(engine) as session:
            # Clear any active queued/running runs
            active = session.exec(select(Run).where(Run.status.in_(["queued", "running"]))).all()
            for r in active:
                r.status = "completed"
            session.commit()

        results = []
        errors = []

        def call_enqueue():
            with patch("app.jobs.validate_url", return_value=(True, "")):
                # Mock per-user concurrency check so race focuses specifically on daily quota count
                with patch("app.jobs.MAX_CONCURRENT_RUNS_PER_USER", 10):
                    r, err = enqueue_run(self.user_id, self.site_id, mode="quick")
                    return r, err

        # Fire two threads concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(call_enqueue), executor.submit(call_enqueue)]
            for f in concurrent.futures.as_completed(futures):
                r, err = f.result()
                results.append(r)
                errors.append(err)

        accepted = [r for r in results if r is not None]
        rejected = [err for err in errors if err is not None]

        # Exactly 1 should be accepted and 1 rejected due to daily quota
        self.assertEqual(len(accepted), 1, f"Expected exactly 1 accepted, got {len(accepted)}")
        self.assertEqual(len(rejected), 1, f"Expected exactly 1 rejected, got {len(rejected)}")
        self.assertIn("Daily limit of 3 quick checks reached", rejected[0])

    @unittest.skipUnless(engine.dialect.name == "postgresql", "PostgreSQL advisory lock concurrency test")
    def test_postgres_global_quick_cap_boundary_race(self):
        import concurrent.futures

        # Clean active runs
        with Session(engine) as s:
            active = s.exec(select(Run).where(Run.status.in_(["queued", "running"]))).all()
            for r in active:
                r.status = "completed"
            s.commit()

            # Seed 1 running quick run (cap is 2 -> exactly 1 slot remains)
            r1 = Run(
                user_id=self.user_id,
                site_id=self.site_id,
                mode="quick",
                status="running",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at="",
                queued_at=datetime.now(timezone.utc).isoformat(),
            )
            s.add(r1)
            s.commit()

        # Create 5 distinct users
        test_users = []
        with Session(engine) as s:
            for i in range(5):
                u = User(email=f"pg_bnd_{i}_{os.urandom(4).hex()}@example.com", password_hash="pass")
                s.add(u)
                s.commit()
                s.refresh(u)
                st = Site(user_id=u.id, url=f"https://pg-bnd-{i}.example.com", domain=f"pg-bnd-{i}.example.com", verify_token="t")
                s.add(st)
                s.commit()
                s.refresh(st)
                test_users.append((u.id, st.id))

        def call_enq(uid, sid):
            with patch("app.jobs.validate_url", return_value=(True, "")):
                with patch.dict(os.environ, {"MAX_CONCURRENT_QUICK_RUNS_GLOBAL": "2"}):
                    return enqueue_run(uid, sid, mode="quick")

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futs = [executor.submit(call_enq, uid, sid) for uid, sid in test_users]
            for f in concurrent.futures.as_completed(futs):
                results.append(f.result())

        accepted = [r for r, err in results if r is not None]
        refused = [err for r, err in results if r is None]

        self.assertEqual(len(accepted), 1, f"Expected exactly 1 accepted, got {len(accepted)}")
        self.assertEqual(len(refused), 4, f"Expected exactly 4 refused, got {len(refused)}")
        for err in refused:
            self.assertIn("Platform is busy with quick checks. Please try again in a minute.", err)





