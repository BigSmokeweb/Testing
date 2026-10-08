import ipaddress
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from sqlmodel import Session, select

from app.creds import (
    cleanup_expired_credentials,
    delete_credentials,
    get_credentials,
    store_credentials,
)
from app.models import Page, Run, Site, SiteCredential, User, engine
from app.public_checks import attempt_login, run_public_checks


class TestStep6Credentials(unittest.TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:6]
        with Session(engine) as session:
            user = User(
                email=f"creds_u_{suffix}@example.com",
                password_hash="pw_hash",
                email_verified=True,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            self.user_id = user.id

            site = Site(
                user_id=user.id,
                url="https://saucedemo.com",
                domain="saucedemo.com",
                verify_token="tok_creds_test",
                verified_at=datetime.now(timezone.utc),
            )
            session.add(site)
            session.commit()
            session.refresh(site)
            self.site_id = site.id

            run = Run(
                user_id=user.id,
                site_id=site.id,
                mode="credentials",
                engine="chromium",
                status="queued",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at="",
                duration_ms=0,
                session_valid=True,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            self.run_id = run.id

    def test_creds_encryption_lifecycle_and_cleanup(self):
        # 1. Store credentials
        cred = store_credentials(
            site_id=self.site_id,
            login_url="https://saucedemo.com/login",
            username="standard_user",
            password="secret_password_123",
        )
        self.assertIsNotNone(cred.id)
        self.assertNotEqual(cred.username_enc, "standard_user")
        self.assertNotEqual(cred.password_enc, "secret_password_123")

        # 2. Retrieve credentials
        res = get_credentials(self.site_id)
        self.assertIsNotNone(res)
        url, u, p = res
        self.assertEqual(url, "https://saucedemo.com/login")
        self.assertEqual(u, "standard_user")
        self.assertEqual(p, "secret_password_123")

        # 3. Delete credentials
        delete_credentials(self.site_id)
        self.assertIsNone(get_credentials(self.site_id))

    def test_attempt_login_captcha_detection(self):
        mock_page = MagicMock()
        mock_page.url = "https://saucedemo.com/login"
        # Simulate captcha iframe found
        mock_loc = MagicMock()
        mock_loc.count.return_value = 1
        mock_page.locator.side_effect = lambda sel: mock_loc if "recaptcha" in sel else MagicMock(count=lambda: 0)

        success, reason = attempt_login(
            mock_page,
            login_url="https://saucedemo.com/login",
            username="user",
            password="pwd",
            base_domain="saucedemo.com",
        )
        self.assertFalse(success)
        self.assertIn("CAPTCHA detected", reason)

    def test_attempt_login_mfa_detection(self):
        mock_page = MagicMock()
        mock_page.url = "https://saucedemo.com/login"
        # First return password and username locators, then after click return MFA input
        mock_user = MagicMock()
        mock_user.count.return_value = 1
        mock_user.first.count.return_value = 1
        mock_pwd = MagicMock()
        mock_pwd.count.return_value = 1
        mock_pwd.first.count.return_value = 1
        mock_btn = MagicMock()
        mock_btn.count.return_value = 1
        mock_btn.first.count.return_value = 1

        mock_mfa = MagicMock()
        mock_mfa.count.return_value = 1
        mock_mfa.first.count.return_value = 1

        def locator_side_effect(sel):
            if "type='password'" in sel:
                return mock_pwd
            if "type='text'" in sel or "user" in sel:
                return mock_user
            if "button" in sel or "submit" in sel:
                return mock_btn
            if "otp" in sel or "mfa" in sel:
                return mock_mfa
            m = MagicMock()
            m.count.return_value = 0
            m.first.count.return_value = 0
            return m

        mock_page.locator.side_effect = locator_side_effect


        success, reason = attempt_login(
            mock_page,
            login_url="https://saucedemo.com/login",
            username="user",
            password="pwd",
            base_domain="saucedemo.com",
        )
        self.assertFalse(success)
        self.assertIn("MFA", reason)

    @patch("app.public_checks.sync_playwright")
    @patch("app.public_checks.requests.get")
    @patch("app.safety.resolve_hostname_ips")
    def test_mode_a_run_cleans_up_credentials_always(
        self, mock_resolve_ips, mock_requests_get, mock_sync_pw
    ):
        mock_resolve_ips.return_value = [ipaddress.ip_address("93.184.216.34")]
        # Store test creds
        store_credentials(
            site_id=self.site_id,
            login_url="https://saucedemo.com/login",
            username="standard_user",
            password="secret_sauce",
        )
        # Ensure credentials row exists
        with Session(engine) as session:
            count = len(session.exec(select(SiteCredential).where(SiteCredential.site_id == self.site_id)).all())
            self.assertEqual(count, 1)

        # Setup mock playwright
        mock_pw = MagicMock()
        mock_sync_pw.return_value.__enter__.return_value = mock_pw
        mock_browser = MagicMock()
        mock_pw.chromium.launch.return_value = mock_browser
        mock_context = MagicMock()
        mock_browser.new_context.return_value = mock_context
        mock_page = MagicMock()
        mock_page.url = "https://saucedemo.com/inventory.html"
        mock_context.new_page.return_value = mock_page

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_page.goto.return_value = mock_resp
        mock_page.eval_on_selector_all.return_value = []


        # Run checks with attempt_login patched
        with patch("app.public_checks.attempt_login", return_value=(True, None)):
            run_public_checks(self.run_id)


        # Verify credentials row was completely deleted
        with Session(engine) as session:
            count_after = len(session.exec(select(SiteCredential).where(SiteCredential.site_id == self.site_id)).all())
            self.assertEqual(count_after, 0)


if __name__ == "__main__":
    unittest.main()
